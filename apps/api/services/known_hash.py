"""Self-contained email blind-index for known-contacts matching.

Deliberately standalone: the known-contacts feature (Phase 03a of the
visitor-filter work) must deploy WITHOUT depending on the separate, not-yet-
committed PII/GDPR module (services/pii_crypto.py). The algorithm intentionally
matches that module — HMAC-SHA256 of a normalized email — so the two can be
unified once the PII work lands, but this file relies only on settings that
already exist in production (ENCRYPTION_KEY).
"""

import hashlib
import hmac

from apps.api.config import settings


def normalize_email(email: str) -> str:
    """Lowercase + strip — the canonical form used for matching."""
    return (email or "").strip().lower()


def _hmac_key() -> bytes:
    # pii_hmac_key may not exist on the deployed config; fall back to the
    # always-present ENCRYPTION_KEY. Never fall back to a constant — a known key
    # turns the blind index into a public membership oracle.
    key = getattr(settings, "pii_hmac_key", None) or getattr(settings, "encryption_key", None)
    if not key:
        raise RuntimeError(
            "Known-contacts blind-index key missing: set PII_HMAC_KEY or ENCRYPTION_KEY. "
            "Refusing to hash with a known constant."
        )
    return key.encode()


def email_hash(email: str) -> str:
    """Deterministic HMAC-SHA256 hex digest of a normalized email (blind index)."""
    return hmac.new(
        _hmac_key(), normalize_email(email).encode(), hashlib.sha256
    ).hexdigest()
