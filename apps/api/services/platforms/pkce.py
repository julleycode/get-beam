"""PKCE (Proof Key for Code Exchange) utilities for OAuth 2.0.

Used by Twitter/X and TikTok which require PKCE with S256 method.
"""

import base64
import hashlib
import secrets
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional


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


# ── In-memory PKCE store ──────────────────────────────────
# TODO: Replace with Redis in production for multi-process support.
# This works fine for single-process dev server (uvicorn --reload).

_store: dict[str, tuple[str, datetime]] = {}
_lock = threading.Lock()
_TTL = timedelta(minutes=10)  # PKCE codes expire after 10 minutes


def store_code_verifier(state: str, code_verifier: str) -> None:
    """Store code_verifier keyed by OAuth state parameter."""
    with _lock:
        # Clean expired entries
        now = datetime.now(timezone.utc)
        expired = [k for k, (_, ts) in _store.items() if now - ts > _TTL]
        for k in expired:
            del _store[k]
        _store[state] = (code_verifier, now)


def get_code_verifier(state: str) -> Optional[str]:
    """Retrieve and remove code_verifier for the given state."""
    with _lock:
        entry = _store.pop(state, None)
        if entry is None:
            return None
        verifier, ts = entry
        if datetime.now(timezone.utc) - ts > _TTL:
            return None  # Expired
        return verifier
