"""Shared rate limiter instance for all routers.

Uses slowapi with Redis backend when available, falls back to in-memory.
"""

import structlog
from slowapi import Limiter
from slowapi.util import get_remote_address

from apps.api.config import settings

logger = structlog.get_logger()


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
            logger.warning("rate_limiter_redis_unavailable", fallback="memory://")
            return "memory://"
    return uri


limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_storage_uri(),
    default_limits=[],
)
