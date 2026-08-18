"""Shared rate limiter instance for all routers.

Uses slowapi with Redis backend when available, falls back to in-memory.
"""

import structlog
from slowapi import Limiter

from apps.api.config import settings
from apps.api.services.ip_resolution import client_ip_key_func

logger = structlog.get_logger()

# True when _storage_uri() had to fall back to in-process memory:// because Redis
# was unreachable at import time. In that state limits are PER REPLICA, not
# global — surfaced by the ingest-health endpoint (P5) rather than silently lost.
STORAGE_DEGRADED = False


def _storage_uri() -> str:
    """Return Redis URI if reachable, otherwise memory:// for in-process limiting."""
    uri = settings.redis_url
    if not uri or uri.startswith("redis://localhost"):
        try:
            import redis
            r = redis.Redis.from_url(uri, socket_connect_timeout=2)
            r.ping()
            return uri
        except Exception:
            global STORAGE_DEGRADED
            STORAGE_DEGRADED = True
            # Emitted ONCE at import, not per request — a per-request warning on a
            # degraded backend would be its own self-inflicted log flood.
            logger.warning("rate_limiter_redis_unavailable", fallback="memory://")
            return "memory://"
    return uri


# E4: resolve ONCE and share the resolved URI with every Limiter below, so a
# second Limiter doesn't re-ping Redis and re-emit the degraded warning at boot.
STORAGE_URI = _storage_uri()


def storage_backend() -> str:
    """Human-readable limiter backend, for the operator ingest-health surface."""
    return "memory (degraded)" if STORAGE_DEGRADED else "redis"


limiter = Limiter(
    key_func=client_ip_key_func,
    storage_uri=STORAGE_URI,
    default_limits=[],
)

# Second, INDEPENDENT limiter keyed on site_id rather than client IP (P3). A
# rotating-IP flood spreads across many IPs so every per-IP bucket stays under
# its allowance; only a site-scoped ceiling sees the aggregate. Shares
# STORAGE_URI so both limiters degrade together rather than disagreeing about
# whether Redis is available.
site_limiter = Limiter(
    key_func=lambda request: getattr(request.state, "site_id", None) or "unknown",
    storage_uri=STORAGE_URI,
    default_limits=[],
)


def site_ceiling_tripped(site_id: str) -> bool:
    """Record one ingest hit for ``site_id`` and report whether it is over ceiling.

    Caller (ingest) hard-rejects with 429 and writes 0 rows when this is True
    (F3 / Validation S1). Velocity (P4) stays flag-but-store — only the site
    ceiling is a hard reject. Fail-open: a storage error returns False (never
    block), matching the datacenter-IP and proxy/VPN checks on the same path.
    """
    if not settings.site_ingest_limit_enabled:
        return False
    try:
        from limits import RateLimitItemPerMinute

        item = RateLimitItemPerMinute(settings.site_ingest_limit_per_minute)
        # .hit() returns False once the window's allowance is exhausted.
        return not site_limiter.limiter.hit(item, "site_ingest", site_id)
    except Exception as exc:
        logger.warning("site_ceiling_check_failed", error=str(exc))
        return False
