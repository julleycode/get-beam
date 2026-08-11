"""Local MaxMind GeoLite2-City lookups — free, unlimited, offline IP→city/lat-lon.

The City sibling of ``asn_lookup.py`` and deliberately identical in shape: one
lazily-opened, memory-mapped, thread-safe reader; a module-level lock; a
``_load_attempted`` guard so a missing DB costs exactly one failed open per
process; and fail-open ``None`` on every error path so a missing or corrupt
artifact can never block a real visitor.

Why this exists: it replaces the ip-api.com call in ``geoip.resolve_geoip_full``
for the geo half of the lookup. ip-api's free tier is plaintext HTTP, capped at
45 requests/minute, and its terms restrict commercial use — all three go away
with a local DB. It also returns something ip-api does not: ``accuracy_radius``,
the real per-IP confidence radius, which the onboarding location reveal draws
instead of a hard-coded 25km estimate.

ONE LICENSE KEY, TWO DATABASES. The same free ``maxmind_license_key`` that
downloads this City DB also downloads GeoLite2-ASN. That matters because the ASN
rung of the network-label ladder (``asn_lookup.lookup_asn``) is DEAD in every
environment today — ``maxmind_asn_db_path`` defaults to ``""`` and no ``.mmdb``
is shipped — so the network line currently falls all the way through to ip-api's
``org``/``isp``. Installing City WITHOUT ASN would skip the ip-api call that is
presently the only source of those fields and silently drop the network line
entirely. Download both, always. See ``scripts/download_geolite2_city.py`` and
``scripts/download_geolite2_asn.py``.

Dormant until ``settings.maxmind_city_db_path`` is set: with the default empty
path every lookup short-circuits to ``None`` and the caller keeps using ip-api,
byte-for-byte as before.
"""

import threading

import structlog

logger = structlog.get_logger()

_reader = None
_reader_lock = threading.Lock()
_load_attempted = False


class CityResult:
    """Geo view of one IP from the local City DB.

    A local type rather than ``geoip.GeoResult``: ``geoip`` imports this module,
    so importing back would be circular. It also carries only what the City DB
    actually knows — no ``isp``/``org``/``as``, which live in the ASN DB.
    """

    __slots__ = ("country_code", "region", "city", "lat", "lon", "accuracy_km")

    def __init__(
        self,
        country_code: str = "",
        region: str = "",
        city: str = "",
        lat: float | None = None,
        lon: float | None = None,
        accuracy_km: int | None = None,
    ) -> None:
        self.country_code = country_code
        self.region = region
        self.city = city
        self.lat = lat
        self.lon = lon
        self.accuracy_km = accuracy_km

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return (
            f"CityResult(country_code={self.country_code!r}, region={self.region!r}, "
            f"city={self.city!r}, lat={self.lat!r}, lon={self.lon!r}, "
            f"accuracy_km={self.accuracy_km!r})"
        )


def _get_reader():
    """Lazily open the GeoLite2-City reader once. Returns None if unavailable."""
    global _reader, _load_attempted
    if _load_attempted:
        return _reader
    with _reader_lock:
        if _load_attempted:
            return _reader
        _load_attempted = True
        from apps.api.config import settings

        path = settings.maxmind_city_db_path
        if not path:
            return None
        try:
            import geoip2.database

            _reader = geoip2.database.Reader(path)
            logger.info("maxmind_city_db_loaded", path=path)
        except Exception as exc:
            logger.warning("maxmind_city_db_load_failed", path=path, error=str(exc))
            _reader = None
    return _reader


def reset_reader_cache() -> None:
    """Force the next lookup to re-open the DB (tests / after a fresh download)."""
    global _reader, _load_attempted
    with _reader_lock:
        try:
            if _reader is not None:
                _reader.close()
        except Exception:
            pass
        _reader = None
        _load_attempted = False


def lookup_city(ip: str) -> CityResult | None:
    """Return a ``CityResult`` for `ip` from the local GeoLite2-City DB.

    ``None`` when the DB is unavailable, the IP isn't in it, or the record has
    no coordinates — the caller then falls back to its network provider. A
    record without lat/lon is treated as a MISS rather than a partial hit: a
    reveal with a country but no pin is worse than one ip-api call.
    """
    if not ip:
        return None
    reader = _get_reader()
    if reader is None:
        return None
    try:
        r = reader.city(ip)
        lat = r.location.latitude
        lon = r.location.longitude
        if lat is None or lon is None:
            return None
        # `subdivisions.most_specific` is always present (an empty record when
        # the DB has none), so `.name` is None rather than an AttributeError.
        region = getattr(r.subdivisions.most_specific, "name", None)
        radius = r.location.accuracy_radius
        return CityResult(
            country_code=(r.country.iso_code or "")[:5],
            region=(region or "")[:100],
            city=(r.city.name or "")[:100],
            lat=float(lat),
            lon=float(lon),
            accuracy_km=int(radius) if radius is not None else None,
        )
    except Exception:
        # AddressNotFoundError (IP not in DB) or any read error → no result.
        return None
