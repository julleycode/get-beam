"""Email blind-index for known-contacts matching.

Historically this was a deliberately standalone, byte-identical second copy of
the HMAC-SHA256 blind index in ``services/pii_crypto.py`` — the known-contacts
feature had to ship before the PII/GDPR module landed. That condition is now
met: ``pii_crypto`` is in production, so ``email_hash`` here delegates to it
directly. Keeping a single implementation removes the silent-divergence hazard
(same key/algorithm today, but two copies could drift apart if either changed
independently). The public ``email_hash`` / ``normalize_email`` names are
preserved so existing known-contacts call sites are untouched.
"""

# ``settings`` is re-exported (imported by tests that monkeypatch
# ``known_hash.settings`` to exercise the shared blind-index key fallback).
from apps.api.config import settings  # noqa: F401
from apps.api.services import pii_crypto


def normalize_email(email: str) -> str:
    """Lowercase + strip — the canonical form used for matching."""
    return (email or "").strip().lower()


def email_hash(email: str) -> str:
    """Deterministic HMAC-SHA256 hex digest of a normalized email (blind index).

    Delegates to ``pii_crypto.email_hash`` — the single source of truth — so the
    known-contacts blind index can never diverge from the PII-module one.
    """
    return pii_crypto.email_hash(email)
