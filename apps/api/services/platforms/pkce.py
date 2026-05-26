"""PKCE (Proof Key for Code Exchange) utilities for OAuth 2.0.

Used by Twitter/X and TikTok which require PKCE with S256 method.

Uses Redis for multi-process safety (required for production with
multiple uvicorn workers). Falls back to in-memory store if Redis
is unavailable (dev only).
"""

import base64
import hashlib
import secrets
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional

import structlog

logger = structlog.get_logger()


def generate_code_verifier(length: int = 64) -> str:
    """Generate a random code_verifier (43-128 unreserved chars)."""
    # Use URL-safe base64 chars without padding
    return secrets.token_urlsafe(length)[:128]


def generate_code_challenge(code_verifier: str) -> str:
    """Compute S256 code_challenge from code_verifier.

    code_challenge = BASE64URL(SHA256(code_verifier))
    """
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ── Store configuration ─────────────────────────────────

_TTL_SECONDS = 600  # 10 minutes
_REDIS_PREFIX = "pkce_verifier:"


# ── Redis-backed store (production) ─────────────────────

async def _redis_store(state: str, code_verifier: str) -> bool:
    """Try to store in Redis. Returns True on success."""
    try:
        from apps.api.services.redis_client import get_redis

        r = get_redis()
        await r.set(f"{_REDIS_PREFIX}{state}", code_verifier, ex=_TTL_SECONDS)
        return True
    except Exception:
        logger.warning("pkce_redis_unavailable_falling_back_to_memory")
        return False


async def _redis_get(state: str) -> Optional[str]:
    """Try to retrieve and delete from Redis."""
    try:
        from apps.api.services.redis_client import get_redis

        r = get_redis()
        pipe = r.pipeline()
        pipe.get(f"{_REDIS_PREFIX}{state}")
        pipe.delete(f"{_REDIS_PREFIX}{state}")
        results = await pipe.execute()
        return results[0]
    except Exception:
        logger.warning("pkce_redis_get_failed")
        return None


# ── In-memory fallback (dev only) ───────────────────────

_mem_store: dict[str, tuple[str, datetime]] = {}
_mem_lock = threading.Lock()


def _memory_store(state: str, code_verifier: str) -> None:
    with _mem_lock:
        now = datetime.now(timezone.utc)
        expired = [k for k, (_, ts) in _mem_store.items() if now - ts > timedelta(seconds=_TTL_SECONDS)]
        for k in expired:
            del _mem_store[k]
        _mem_store[state] = (code_verifier, now)


def _memory_get(state: str) -> Optional[str]:
    with _mem_lock:
        entry = _mem_store.pop(state, None)
        if entry is None:
            return None
        verifier, ts = entry
        if datetime.now(timezone.utc) - ts > timedelta(seconds=_TTL_SECONDS):
            return None
        return verifier


# ── Public API ──────────────────────────────────────────

async def store_code_verifier(state: str, code_verifier: str) -> None:
    """Store code_verifier keyed by OAuth state parameter."""
    stored = await _redis_store(state, code_verifier)
    if not stored:
        _memory_store(state, code_verifier)


async def get_code_verifier(state: str) -> Optional[str]:
    """Retrieve and remove code_verifier for the given state."""
    result = await _redis_get(state)
    if result is not None:
        return result
    return _memory_get(state)
