"""Shared rate limiter instance for all routers.

Uses slowapi with Redis backend when available, falls back to in-memory.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from apps.api.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url,
    default_limits=[],
)
