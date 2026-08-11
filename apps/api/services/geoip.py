"""GeoIP resolution: local MaxMind GeoLite2-City first, free ip-api.com second.

Two-tier cache: L1 process-local dict (zero latency), L2 Redis (24h TTL).

Provider ladder inside ``resolve_geoip_full`` (first hit wins):
  1. ``geoip_city.lookup_city`` — local .mmdb, offline, unlimited, and the only
     source of a real ``accuracy_km``. DORMANT while ``maxmind_city_db_path`` is
     "" (the default), which makes this whole rung a no-op until an operator
     installs the artifact.
  2. ip-api.com — 45 requests/minute on the free tier (the ceiling counts
     REQUESTS, not fields, so widening the field mask costs nothing).

The City DB supplies geo only; ``isp``/``org``/``as`` remain ip-api's. See
``config.maxmind_city_db_path`` for why the ASN DB must be installed alongside it.

Two public entry points over ONE provider call:

* ``resolve_geoip(ip) -> (country_code, region)`` — the long-standing ingest
  path (``routers/events.py``). Signature and return values are frozen; it is a
  thin wrapper over ``resolve_geoip_full`` and must stay byte-identical.
* ``resolve_geoip_full(ip) -> GeoResult | None`` — the widened view (city,
  lat/lon, isp, org, as) used by the onboarding location reveal.

CACHE KEY SPLIT (deliberate, do not "simplify"): the full result lives under a
NEW ``geoip2:`` prefix holding JSON. The legacy ``geoip:`` prefix keeps its
pipe-joined ``"US|California"`` value. Overloading the old key would mean that
during a rolling deploy an old pod reads a JSON blob, splits it on ``"|"``, and
writes garbage into ``country_code`` on every ingested event.
"""

import json

import httpx
import structlog

from apps.api.config import settings

logger = structlog.get_logger()

_geoip_cache: dict[str, tuple[str, str]] = {}
_geoip_full_cache: dict[str, "GeoResult"] = {}
_CACHE_MAX_SIZE = 500
_REDIS_PREFIX = "geoip:"        # legacy: "CC|Region" — never write JSON here
_REDIS_PREFIX_FULL = "geoip2:"  # widened: JSON
_REDIS_TTL = 86400
# ip-api answers 429 with an ``X-Ttl`` header (seconds until the window resets).
# While this key exists we skip the provider entirely rather than burning a
# request that is guaranteed to fail.
_BACKOFF_KEY = "geoip:backoff"
_BACKOFF_DEFAULT = 60

_FIELDS = "status,countryCode,regionName,city,lat,lon,isp,org,as"


class GeoResult:
    """Full geo view of one IP. Plain class (not a dataclass) so it stays
    trivially JSON round-trippable through Redis via ``to_dict``/``from_dict``."""

    __slots__ = (
        "country_code", "region", "city", "lat", "lon", "isp", "org", "as_str",
        "accuracy_km",
    )

    def __init__(
        self,
        country_code: str = "",
        region: str = "",
        city: str = "",
        lat: float | None = None,
        lon: float | None = None,
        isp: str = "",
        org: str = "",
        as_str: str = "",
        accuracy_km: int | None = None,
    ) -> None:
        self.country_code = country_code
        self.region = region
        self.city = city
        self.lat = lat
        self.lon = lon
        self.isp = isp
        self.org = org
        self.as_str = as_str
        # Real per-IP confidence radius in km. Only the local GeoLite2-City DB
        # supplies it; ip-api returns nothing comparable, so it stays None there
        # and the caller keeps its fixed honest estimate.
        self.accuracy_km = accuracy_km

    def to_dict(self) -> dict:
        return {
            "country_code": self.country_code,
            "region": self.region,
            "city": self.city,
            "lat": self.lat,
            "lon": self.lon,
            "isp": self.isp,
            "org": self.org,
            "as_str": self.as_str,
            "accuracy_km": self.accuracy_km,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GeoResult":
        return cls(
            country_code=d.get("country_code") or "",
            region=d.get("region") or "",
            city=d.get("city") or "",
            lat=d.get("lat"),
            lon=d.get("lon"),
            isp=d.get("isp") or "",
            org=d.get("org") or "",
            as_str=d.get("as_str") or "",
            # ``.get`` not ``[]``: a JSON blob written by a pod that ran before
            # the City rung existed has no such key and must still parse.
            accuracy_km=d.get("accuracy_km"),
        )

    def __eq__(self, other: object) -> bool:  # tests compare by value
        return isinstance(other, GeoResult) and self.to_dict() == other.to_dict()

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"GeoResult({self.to_dict()})"


def _mock_geo(ip: str) -> GeoResult:
    """Deterministic fake for ``settings.mock_external_apis`` (repo-wide rule —
    every external provider must work keyless offline). Fixed values so a local
    demo and a test assert the same thing on every run."""
    return GeoResult(
        country_code="US",
        region="California",
        city="Mountain View",
        lat=37.386,
        lon=-122.084,
        isp="Mock ISP",
        org="Mock Org",
        as_str="AS15169 Mock AS",
    )


async def resolve_geoip(ip: str) -> tuple[str, str]:
    """Resolve IP address to (country_code, region).

    FROZEN SIGNATURE — called synchronously by the ingest hot path
    (``routers/events.py``). Returns ("", "") on failure — never raises.
    """
    if not ip or ip in ("", "127.0.0.1", "::1"):
        return ("", "")

    if ip in _geoip_cache:
        return _geoip_cache[ip]

    # Legacy L2 key first: a pod that ran before the widening already wrote it,
    # and honouring it keeps ingest on the cheap path during a rolling deploy.
    legacy = await _legacy_redis_get(ip)
    if legacy is not None:
        _l1_store(ip, legacy)
        return legacy

    full = await resolve_geoip_full(ip)
    if full is None:
        return ("", "")

    result = (full.country_code, full.region)
    _l1_store(ip, result)
    await _legacy_redis_set(ip, result)
    return result


async def resolve_geoip_full(ip: str) -> GeoResult | None:
    """Resolve an IP to the full geo view. ``None`` on failure — never raises."""
    # MOCK FIRST, ahead of the loopback guard, on purpose. In local dev the
    # caller's IP IS 127.0.0.1, so guarding first meant `geo: null` and the
    # location reveal could never be demoed or hand-tested offline — which the
    # plan's degraded-paths table explicitly requires it to be
    # ("MOCK_EXTERNAL_APIS=true returns a deterministic fake so it demos
    # locally"). `resolve_geoip` keeps its OWN loopback guard above this call,
    # so the ingest hot path still short-circuits 127.0.0.1 before ever getting
    # here and its ("", "") contract is untouched.
    if settings.mock_external_apis:
        return _mock_geo(ip)

    if not ip or ip in ("", "127.0.0.1", "::1"):
        return None

    cached_l1 = _geoip_full_cache.get(ip)
    if cached_l1 is not None:
        return cached_l1

    try:
        from apps.api.services.redis_client import get_redis

        redis = get_redis()
        raw = await redis.get(_REDIS_PREFIX_FULL + ip)
        if raw:
            result = GeoResult.from_dict(json.loads(raw))
            _l1_store_full(ip, result)
            return result
    except Exception:
        pass

    # RUNG 1: the local MaxMind GeoLite2-City DB. Free, offline, unlimited, and
    # the only source of a real accuracy_radius. Dormant (returns None instantly)
    # while settings.maxmind_city_db_path is "" — which it is by default — so the
    # ip-api path below is untouched until an operator installs the artifact.
    #
    # It fills geo ONLY. isp/org/as stay empty because the City DB does not carry
    # them; the network label's own ladder then leans on the local ASN DB (same
    # license key — see config.maxmind_city_db_path KNOWN LIMITATIONS).
    city = _lookup_city_safe(ip)
    if city is not None:
        result = GeoResult(
            country_code=city.country_code,
            region=city.region,
            city=city.city,
            lat=city.lat,
            lon=city.lon,
            accuracy_km=city.accuracy_km,
        )
        _l1_store_full(ip, result)
        await _redis_set_full(ip, result)
        return result

    # RUNG 2: ip-api.com over the network.
    if await _in_backoff():
        logger.debug("geoip_backoff_skip", ip=ip[:10])
        return None

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"http://ip-api.com/json/{ip}",
                params={"fields": _FIELDS},
            )
            if resp.status_code == 429:
                await _set_backoff(resp.headers.get("X-Ttl"))
                logger.warning("geoip_rate_limited", ip=ip[:10])
                return None
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    result = GeoResult(
                        country_code=(data.get("countryCode") or "")[:5],
                        region=(data.get("regionName") or "")[:100],
                        city=(data.get("city") or "")[:100],
                        lat=_as_float(data.get("lat")),
                        lon=_as_float(data.get("lon")),
                        isp=(data.get("isp") or "")[:200],
                        org=(data.get("org") or "")[:200],
                        as_str=(data.get("as") or "")[:200],
                    )
                    _l1_store_full(ip, result)
                    await _redis_set_full(ip, result)
                    return result
    except Exception as e:
        logger.debug("geoip_lookup_failed", ip=ip[:10], error=str(e))

    return None


def _lookup_city_safe(ip: str):
    """Local City DB lookup that cannot throw. ``None`` = miss, fall through.

    ``lookup_city`` is already fail-open; this second belt exists because the
    import itself can fail (geoip2 missing from a slim image) and geo resolution
    must degrade rather than break the ingest wrapper above it.
    """
    try:
        from apps.api.services.geoip_city import lookup_city

        return lookup_city(ip)
    except Exception:
        return None


async def _redis_set_full(ip: str, result: "GeoResult") -> None:
    """Write the widened JSON under the ``geoip2:`` prefix. Never raises."""
    try:
        from apps.api.services.redis_client import get_redis

        redis = get_redis()
        await redis.setex(
            _REDIS_PREFIX_FULL + ip, _REDIS_TTL, json.dumps(result.to_dict())
        )
    except Exception:
        pass


def _as_float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def _legacy_redis_get(ip: str) -> tuple[str, str] | None:
    """Read the legacy pipe-joined key. Tolerates a malformed value (never
    raises, never mis-parses into a crash) — worst case we re-resolve."""
    try:
        from apps.api.services.redis_client import get_redis

        redis = get_redis()
        cached = await redis.get(_REDIS_PREFIX + ip)
        if not cached:
            return None
        if isinstance(cached, bytes):
            cached = cached.decode("utf-8", "replace")
        parts = cached.split("|", 1)
        return (parts[0][:5], parts[1][:100] if len(parts) > 1 else "")
    except Exception:
        return None


async def _legacy_redis_set(ip: str, result: tuple[str, str]) -> None:
    try:
        from apps.api.services.redis_client import get_redis

        redis = get_redis()
        await redis.setex(_REDIS_PREFIX + ip, _REDIS_TTL, f"{result[0]}|{result[1]}")
    except Exception:
        pass


async def _in_backoff() -> bool:
    try:
        from apps.api.services.redis_client import get_redis

        redis = get_redis()
        return bool(await redis.get(_BACKOFF_KEY))
    except Exception:
        return False


async def _set_backoff(x_ttl: str | None) -> None:
    try:
        ttl = int(x_ttl) if x_ttl else _BACKOFF_DEFAULT
    except (TypeError, ValueError):
        ttl = _BACKOFF_DEFAULT
    ttl = max(1, min(ttl, 300))
    try:
        from apps.api.services.redis_client import get_redis

        redis = get_redis()
        await redis.setex(_BACKOFF_KEY, ttl, "1")
    except Exception:
        pass


def _l1_store(ip: str, result: tuple[str, str]) -> None:
    if len(_geoip_cache) >= _CACHE_MAX_SIZE:
        _geoip_cache.clear()
    _geoip_cache[ip] = result


def _l1_store_full(ip: str, result: GeoResult) -> None:
    if len(_geoip_full_cache) >= _CACHE_MAX_SIZE:
        _geoip_full_cache.clear()
    _geoip_full_cache[ip] = result
