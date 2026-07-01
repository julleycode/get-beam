"""Local MaxMind GeoLite2-ASN lookups — free, unlimited, offline IP→ASN.

Reads a GeoLite2-ASN.mmdb (download via scripts/download_geolite2_asn.py with a
free MaxMind license key; path from settings.maxmind_asn_db_path). The reader is
a memory-mapped, thread-safe, sub-microsecond in-memory lookup — no network, no
rate limit, unlike the per-IP IPinfo call it replaces for datacenter detection.

Lazy-loaded once. Fail-open: returns (None, None) when the DB is absent or
unreadable, so callers transparently fall back to their network provider and a
missing/corrupt DB never blocks a real visitor.
"""
import threading

import structlog

logger = structlog.get_logger()

_reader = None
_reader_lock = threading.Lock()
_load_attempted = False


def _get_reader():
    """Lazily open the GeoLite2-ASN reader once. Returns None if unavailable."""
    global _reader, _load_attempted
    if _load_attempted:
        return _reader
    with _reader_lock:
        if _load_attempted:
            return _reader
        _load_attempted = True
        from apps.api.config import settings

        path = settings.maxmind_asn_db_path
        if not path:
            return None
        try:
            import geoip2.database

            _reader = geoip2.database.Reader(path)
            logger.info("maxmind_asn_db_loaded", path=path)
        except Exception as exc:
            logger.warning("maxmind_asn_db_load_failed", path=path, error=str(exc))
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


def lookup_asn(ip: str) -> tuple[int | None, str | None]:
    """Return (asn_number, asn_org) for `ip` from the local GeoLite2-ASN DB.

    (None, None) when the DB is unavailable or the IP isn't in it — the caller
    then falls back to its network provider."""
    if not ip:
        return (None, None)
    reader = _get_reader()
    if reader is None:
        return (None, None)
    try:
        r = reader.asn(ip)
        return (r.autonomous_system_number, r.autonomous_system_organization)
    except Exception:
        # AddressNotFoundError (IP not in DB) or any read error → no result.
        return (None, None)
