"""OAuth state store -- CSRF protection for OAuth callbacks.

Stores the OAuth state along with the user_id who initiated the flow.
On callback we validate the state exists and retrieve the user_id.

Uses Redis for multi-process safety (required for production with
multiple uvicorn workers). Falls back to in-memory store if Redis
is unavailable (dev only).
"""

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()

_TTL_SECONDS = 600  # 10 minutes


# ── Redis-backed store (production) ─────────────────────

_REDIS_PREFIX = "oauth_state:"


async def _redis_store(state: str, user_id: str) -> bool:
    """Try to store in Redis. Returns True on success."""
    try:
        from apps.api.services.redis_client import get_redis

        r = get_redis()
        await r.set(f"{_REDIS_PREFIX}{state}", user_id, ex=_TTL_SECONDS)
        return True
    except Exception:
        logger.warning("oauth_state_redis_unavailable_falling_back_to_memory")
        return False


async def _redis_validate(state: str) -> Optional[str]:
    """Try to validate from Redis. Returns user_id, None, or raises if Redis unavailable."""
    try:
        from apps.api.services.redis_client import get_redis

        r = get_redis()
        # GET + DELETE atomically via pipeline
        pipe = r.pipeline()
        pipe.get(f"{_REDIS_PREFIX}{state}")
        pipe.delete(f"{_REDIS_PREFIX}{state}")
        results = await pipe.execute()
        return results[0]  # The GET result (str or None)
    except Exception:
        logger.warning("oauth_state_redis_validate_failed")
        return None


# ── In-memory fallback (dev only) ───────────────────────

@dataclass
class _OAuthStateEntry:
    user_id: str
    created_at: datetime


_mem_store: dict[str, _OAuthStateEntry] = {}
_mem_lock = threading.Lock()


def _memory_store(state: str, user_id: str) -> None:
    with _mem_lock:
        now = datetime.now(timezone.utc)
        expired = [k for k, v in _mem_store.items() if now - v.created_at > timedelta(seconds=_TTL_SECONDS)]
        for k in expired:
            del _mem_store[k]
        _mem_store[state] = _OAuthStateEntry(user_id=user_id, created_at=now)


def _memory_validate(state: str) -> Optional[str]:
    with _mem_lock:
        entry = _mem_store.pop(state, None)
        if entry is None:
            return None
        if datetime.now(timezone.utc) - entry.created_at > timedelta(seconds=_TTL_SECONDS):
            return None
        return entry.user_id


# ── Public API ──────────────────────────────────────────

async def store_oauth_state(state: str, user_id: str) -> None:
    """Store an OAuth state parameter with the user who initiated it."""
    stored = await _redis_store(state, user_id)
    if not stored:
        _memory_store(state, user_id)


async def validate_oauth_state(state: str) -> Optional[str]:
    """Validate and consume an OAuth state. Returns user_id or None if invalid/expired."""
    result = await _redis_validate(state)
    if result is not None:
        return result
    # Fall back to memory (in case it was stored there)
    return _memory_validate(state)
