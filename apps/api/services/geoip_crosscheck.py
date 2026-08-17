"""Second-opinion geo lookup: is the city we are about to claim actually real?

WHY THIS MODULE EXISTS — a measured failure, not a hypothetical. One residential
FPT Telecom address (AS18403, ``42.117.132.191``) resolves to:

    ip-api.com   ->  Hanoi      (21.018, 105.846)
    ipinfo.io    ->  Haiphong   (20.865, 106.683)
    the human    ->  Ho Chi Minh City

Three answers, one IP, ~1100 km of error — against an accuracy circle that
claims 25 km. ip-api geolocates most non-US residential ranges by ASN
REGISTRATION (its ``org`` for that IP is literally "Vietnam Internet Network
Information Center", a registry), so on carriers that register wide blocks under
one HQ the city name is a coin flip. A confidently wrong city is strictly worse
than no city at all in a moment whose whole job is to look omniscient.

So: ask a second free provider, measure the distance between the two points, and
let ``build_geo`` weaken its claim when they disagree. Agreement is not proof of
correctness — both providers can be wrong the same way — but DISAGREEMENT is
proof of unreliability, and that is the signal worth acting on.

DELIBERATELY OUT OF THE INGEST PATH. ``resolve_geoip`` (``routers/events.py``)
must stay one provider call on the hot path; this second round-trip is only ever
made by the onboarding reveal, which is one request per new user. Nothing here
is imported by ``geoip.py``.

Fail-open everywhere: a dead second provider yields ``checked=False``, which the
caller renders exactly as today's single-provider behaviour.
"""

import json
import math

import httpx
import structlog

from apps.api.config import settings

logger = structlog.get_logger()

# (lat, lon, city, country) — the city rides along so `crosscheck_geo` can name
# the disagreeing answer in a log line without a second cache; the country is the
# D4 hardening input (a country card must be ~100% right when we show one).
_L1: dict[str, tuple[float, float, str, str] | None] = {}
_L1_MAX = 500
_REDIS_PREFIX = "geoipx:"  # third key namespace; see geoip.py's CACHE KEY SPLIT
_REDIS_TTL = 86400
_TIMEOUT = 3.0

_EARTH_RADIUS_KM = 6371.0


class CrossCheck:
    """Verdict on one primary geo result.

    ``checked=False`` means no second opinion was obtainable (flag off, provider
    down, no coordinates). It is NOT the same as agreement, and the caller must
    not upgrade its confidence on the strength of it.
    """

    __slots__ = (
        "checked",
        "agreed",
        "distance_km",
        "second_city",
        "second_country",
        "country_agreed",
    )

    def __init__(
        self,
        checked: bool = False,
        agreed: bool = False,
        distance_km: float | None = None,
        second_city: str = "",
        second_country: str = "",
        country_agreed: bool | None = None,
    ) -> None:
        self.checked = checked
        self.agreed = agreed
        self.distance_km = distance_km
        self.second_city = second_city
        # "" = unknown second-provider country.
        self.second_country = second_country
        # None = unknown (allowed — see the plan's accepted residual risk);
        # False = a POSITIVE disagreement, which suppresses the country card.
        self.country_agreed = country_agreed

    def to_dict(self) -> dict:
        return {
            "checked": self.checked,
            "agreed": self.agreed,
            "distance_km": self.distance_km,
            "second_city": self.second_city,
            "second_country": self.second_country,
            "country_agreed": self.country_agreed,
        }

    def __eq__(self, other: object) -> bool:  # tests compare by value
        return isinstance(other, CrossCheck) and self.to_dict() == other.to_dict()

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"CrossCheck({self.to_dict()})"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km. Pure — the honesty rule is unit-testable.

    Haversine rather than a flat euclidean approximation because the errors this
    detects are hundreds of km at ~20°N, where a degree of longitude is ~6%
    shorter than a degree of latitude; a flat metric would systematically
    overstate east-west disagreement.
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


async def crosscheck_geo(ip: str, primary) -> CrossCheck:
    """Compare ``primary`` against a second provider. Never raises.

    ``primary`` is a ``geoip.GeoResult`` (duck-typed: only ``lat``/``lon`` are
    read, so a test double needs nothing else).
    """
    if not settings.geo_crosscheck_enabled:
        return CrossCheck()

    lat = getattr(primary, "lat", None) if primary is not None else None
    lon = getattr(primary, "lon", None) if primary is not None else None
    if lat is None or lon is None:
        return CrossCheck()

    if settings.mock_external_apis:
        # Deterministic agreement: the repo-wide rule is that every external
        # provider works keyless offline, and a mock that manufactured a
        # disagreement would make the local demo permanently render the
        # degraded copy.
        # second_country matches `_mock_geo.country_code` ("US") so the mock
        # fixture keeps landing on the map path (plan Section E / AC-13).
        return CrossCheck(checked=True, agreed=True, distance_km=0.0,
                          second_city="Mountain View",
                          second_country="US", country_agreed=True)

    second = await _lookup_second(ip)
    if second is None:
        return CrossCheck()

    second_lat, second_lon, second_city, second_country = second
    distance = haversine_km(float(lat), float(lon), second_lat, second_lon)
    agreed = distance <= max(1, settings.geo_crosscheck_disagree_km)

    # D4 country hardening. Compared only when BOTH sides are non-empty: an
    # unknown country is `None` (= allowed), never a disagreement. Blocking on a
    # missing second opinion would gut the country-card fallback path entirely.
    primary_country = str(getattr(primary, "country_code", "") or "").strip().upper()
    second_country_norm = str(second_country or "").strip().upper()
    if primary_country and second_country_norm:
        country_agreed: bool | None = primary_country == second_country_norm
    else:
        country_agreed = None

    if country_agreed is False:
        logger.info(
            "geo_country_disagreement",
            ip=ip[:8],
            primary_country=primary_country,
            second_country=second_country_norm,
        )

    if not agreed:
        # Truncated IP only — the same PII posture as the rest of this surface.
        # City names are logged because they are what makes the line actionable
        # ("ip-api said Hanoi, ipinfo said Haiphong"); neither is PII on its own.
        logger.info(
            "geo_crosscheck_disagreement",
            ip=ip[:8],
            distance_km=round(distance, 1),
            second_city=second_city,
        )

    return CrossCheck(
        checked=True,
        agreed=agreed,
        distance_km=distance,
        second_city=second_city,
        second_country=second_country_norm,
        country_agreed=country_agreed,
    )


async def _lookup_second(ip: str) -> tuple[float, float, str, str] | None:
    """ipinfo.io coordinates for ``ip``. ``None`` on any failure.

    ipinfo answers WITHOUT a token (rate-limited, ~1k/day/IP), which is why this
    works in an environment where ``ipinfo_token`` is "" — the same environment
    in which the local GeoLite2-City rung is dormant and ip-api is therefore
    unchallenged. The token is sent when present purely to lift that ceiling.
    """
    if not ip:
        return None

    if ip in _L1:
        return _L1[ip]

    try:
        from apps.api.services.redis_client import get_redis

        redis = get_redis()
        raw = await redis.get(_REDIS_PREFIX + ip)
        if raw:
            point = _point_from(json.loads(raw))
            _store(ip, point)
            return point
    except Exception:
        pass

    params = {"token": settings.ipinfo_token} if settings.ipinfo_token else None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"https://ipinfo.io/{ip}/json", params=params)
            if resp.status_code != 200:
                # 429 (keyless ceiling) and 4xx alike: no second opinion today.
                # Deliberately NOT cached — a rate-limit window is minutes, and
                # caching the miss for 24h would disable the check for a day.
                return None
            data = resp.json()
    except Exception as e:  # noqa: BLE001 — a reveal must never 500 on this
        logger.debug("geo_crosscheck_failed", ip=ip[:8], error=str(e))
        return None

    point = _point_from(data)
    if point is None:
        return None

    _store(ip, point)
    try:
        from apps.api.services.redis_client import get_redis

        redis = get_redis()
        await redis.setex(
            _REDIS_PREFIX + ip,
            _REDIS_TTL,
            # NO key-namespace bump: a pre-existing cache line simply has no
            # "country", which `_point_from` degrades to "" = unknown = allowed.
            json.dumps({
                "loc": data.get("loc"),
                "city": data.get("city") or "",
                "country": data.get("country") or "",
            }),
        )
    except Exception:
        pass

    return point


def _point_from(data: dict) -> tuple[float, float, str, str] | None:
    """ipinfo returns geo as one ``"20.8648,106.6834"`` string, not two floats."""
    loc = (data or {}).get("loc") or ""
    if not isinstance(loc, str) or "," not in loc:
        return None
    lat_s, _, lon_s = loc.partition(",")
    try:
        lat, lon = float(lat_s), float(lon_s)
    except (TypeError, ValueError):
        return None
    # Null Island is ipinfo's shape of "no idea"; treating it as a real point
    # would manufacture a ~10,000 km disagreement for every unknown IP.
    if lat == 0.0 and lon == 0.0:
        return None
    # ipinfo returns a 2-letter code in "country". Absent / non-str degrades to
    # "" = unknown, which the caller reads as `country_agreed=None` (allowed).
    raw_country = (data or {}).get("country")
    country = raw_country.strip().upper()[:2] if isinstance(raw_country, str) else ""
    return (lat, lon, str((data or {}).get("city") or "")[:100], country)


def _store(ip: str, point: tuple[float, float, str, str] | None) -> None:
    if len(_L1) >= _L1_MAX:
        _L1.clear()
    _L1[ip] = point
