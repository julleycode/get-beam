"""Lightweight GeoIP resolution using free ip-api.com service.

Rate limit: 45 requests/minute (free tier, no key needed).
For production scale, switch to MaxMind GeoLite2 local database.
"""

import httpx
import structlog

logger = structlog.get_logger()

# In-memory cache to avoid repeated lookups for same IP within a request cycle
_geoip_cache: dict[str, tuple[str, str]] = {}
_CACHE_MAX_SIZE = 500


async def resolve_geoip(ip: str) -> tuple[str, str]:
    """Resolve IP address to (country_code, region).

    Returns ("", "") on failure — never raises.
    """
    if not ip or ip in ("", "127.0.0.1", "::1"):
        return ("", "")

    # Check in-memory cache
    if ip in _geoip_cache:
        return _geoip_cache[ip]

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"http://ip-api.com/json/{ip}",
                params={"fields": "status,countryCode,regionName"},
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    result = (
                        data.get("countryCode", "")[:5],
                        data.get("regionName", "")[:100],
                    )
                    # Cache result
                    if len(_geoip_cache) >= _CACHE_MAX_SIZE:
                        _geoip_cache.clear()
                    _geoip_cache[ip] = result
                    return result
    except Exception as e:
        logger.debug("geoip_lookup_failed", ip=ip[:10], error=str(e))

    return ("", "")
