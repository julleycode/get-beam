"""PII crypto helpers — blind index (hashing) + encryption at rest.

Two primitives, used together to encrypt PII while keeping it searchable:

- ``email_hash`` — deterministic keyed hash (HMAC-SHA256) of a normalized email.
  A blind index: lets us look an address up (equality / uniqueness) WITHOUT
  storing plaintext. Same input → same hash, always.
- ``encrypt_pii`` / ``decrypt_pii`` — Fernet (AES-128-CBC + HMAC) for the stored
  value itself. Non-deterministic ciphertext (so it can't be a lookup key —
  that's what the blind index is for).

Keys come from ``PII_HMAC_KEY`` / ``PII_ENCRYPTION_KEY`` when set, else fall
back to ``ENCRYPTION_KEY`` (a valid Fernet key, always present and validated at
boot) so this ships without new mandatory env vars.

Decryption is tolerant: a value that isn't valid Fernet ciphertext (e.g. a
plaintext row not yet backfilled, or a no-key passthrough) is returned as-is,
so read paths work across the mixed-data window during Phase 05 rollout.
"""

import hashlib
import hmac
from typing import Optional

import structlog
from cryptography.fernet import Fernet, InvalidToken

from apps.api.config import settings

logger = structlog.get_logger()

_fernet: Optional[Fernet] = None


def _hmac_key() -> bytes:
    key = settings.pii_hmac_key or settings.encryption_key
    if not key:
        raise RuntimeError(
            "PII blind-index key missing: set PII_HMAC_KEY or ENCRYPTION_KEY. "
            "Refusing to hash with a known constant — that would defeat the blind index."
        )
    return key.encode()


def _get_fernet() -> Optional[Fernet]:
    """Lazy-init the Fernet cipher from PII_ENCRYPTION_KEY (or ENCRYPTION_KEY)."""
    global _fernet
    if _fernet is not None:
        return _fernet
    key = settings.pii_encryption_key or settings.encryption_key
    if not key:
        return None
    try:
        _fernet = Fernet(key.encode())
    except Exception as exc:  # malformed key — degrade to passthrough, never crash
        logger.warning("pii_fernet_init_failed", error=str(exc))
        return None
    return _fernet


def normalize_email(email: str) -> str:
    """Lowercase + strip — the canonical form used everywhere email is matched."""
    return (email or "").strip().lower()


def email_hash(email: str) -> str:
    """Deterministic HMAC-SHA256 hex digest of a normalized email (blind index)."""
    return hmac.new(
        _hmac_key(), normalize_email(email).encode(), hashlib.sha256
    ).hexdigest()


def encrypt_pii(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt a PII value for storage. None/empty → None. No key → passthrough."""
    if not plaintext:
        return None
    fernet = _get_fernet()
    if fernet is None:
        logger.warning("pii_encrypt_no_key_passthrough")
        return plaintext
    return fernet.encrypt(plaintext.encode()).decode()


def decrypt_pii(ciphertext: Optional[str]) -> Optional[str]:
    """Decrypt a stored PII value. None → None. Non-ciphertext → returned as-is."""
    if ciphertext is None:
        return None
    fernet = _get_fernet()
    if fernet is None:
        return ciphertext
    try:
        return fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        # Plaintext (pre-backfill) or passthrough value — return unchanged.
        return ciphertext
    except Exception as exc:
        logger.warning("pii_decrypt_failed", error=str(exc))
        return ciphertext
