"""Lightweight GeoIP resolution using free ip-api.com service.

Two-tier cache: L1 process-local dict (zero latency), L2 Redis (24h TTL).
Rate limit: 45 requests/minute (free tier, no key needed).
For production scale, switch to MaxMind GeoLite2 local database.
"""

import httpx
import structlog

logger = structlog.get_logger()

_geoip_cache: dict[str, tuple[str, str]] = {}
_CACHE_MAX_SIZE = 500
_REDIS_PREFIX = "geoip:"
_REDIS_TTL = 86400


async def resolve_geoip(ip: str) -> tuple[str, str]:
    """Resolve IP address to (country_code, region).

    Returns ("", "") on failure — never raises.
    """
    if not ip or ip in ("", "127.0.0.1", "::1"):
        return ("", "")

    if ip in _geoip_cache:
        return _geoip_cache[ip]

    try:
        from apps.api.services.redis_client import get_redis
        redis = get_redis()
        cached = await redis.get(_REDIS_PREFIX + ip)
        if cached:
            parts = cached.split("|", 1)
            result = (parts[0], parts[1] if len(parts) > 1 else "")
            _l1_store(ip, result)
            return result
    except Exception:
        pass

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
                    _l1_store(ip, result)
                    try:
                        redis = get_redis()
                        await redis.setex(
                            _REDIS_PREFIX + ip,
                            _REDIS_TTL,
                            f"{result[0]}|{result[1]}",
                        )
                    except Exception:
                        pass
                    return result
    except Exception as e:
        logger.debug("geoip_lookup_failed", ip=ip[:10], error=str(e))

    return ("", "")


def _l1_store(ip: str, result: tuple[str, str]) -> None:
    if len(_geoip_cache) >= _CACHE_MAX_SIZE:
        _geoip_cache.clear()
    _geoip_cache[ip] = result
