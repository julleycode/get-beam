"""OAuth state store -- CSRF protection for OAuth callbacks.

Stores the OAuth state along with the user_id who initiated the flow.
On callback we validate the state exists and retrieve the user_id.

TODO: Replace with Redis for multi-process production.
"""

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass
class OAuthStateEntry:
    user_id: str
    created_at: datetime


_store: dict[str, OAuthStateEntry] = {}
_lock = threading.Lock()
_TTL = timedelta(minutes=10)


def store_oauth_state(state: str, user_id: str) -> None:
    """Store an OAuth state parameter with the user who initiated it."""
    with _lock:
        now = datetime.now(timezone.utc)
        expired = [k for k, v in _store.items() if now - v.created_at > _TTL]
        for k in expired:
            del _store[k]
        _store[state] = OAuthStateEntry(user_id=user_id, created_at=now)


def validate_oauth_state(state: str) -> Optional[str]:
    """Validate and consume an OAuth state. Returns user_id or None if invalid/expired."""
    with _lock:
        entry = _store.pop(state, None)
        if entry is None:
            return None
        if datetime.now(timezone.utc) - entry.created_at > _TTL:
            return None
        return entry.user_id
