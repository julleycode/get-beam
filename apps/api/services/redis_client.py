"""Shared async Redis client for the application.

Used by OAuth state store, PKCE store, and other services that need
a multi-process-safe ephemeral key-value store.
"""

from typing import Optional

import structlog
from redis.asyncio import Redis

from apps.api.config import settings

logger = structlog.get_logger()

_client: Optional[Redis] = None


def get_redis() -> Redis:
    """Get or create the shared async Redis client."""
    global _client
    if _client is None:
        _client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            # A Redis that accepts the connection and then hangs would otherwise
            # block every awaited call forever. socket_timeout bounds the read;
            # retry_on_timeout=False surfaces the TimeoutError to the caller
            # instead of silently retrying (every caller already degrades on a
            # Redis exception). Unflagged by design: an infinite hang becomes a
            # bounded error.
            socket_timeout=5,
            retry_on_timeout=False,
        )
    return _client


async def close_redis() -> None:
    """Close the Redis connection pool. Call on app shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
        logger.info("redis_connection_closed")
