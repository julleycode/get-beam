"""Encrypt / decrypt OAuth tokens at rest using Fernet (AES-128-CBC + HMAC).

If TOKEN_ENCRYPTION_KEY is not set, encryption is a no-op (plaintext passthrough)
so existing dev setups keep working. In production, always set the key.

Generate a key:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Note: This is the *graceful* encryption service for OAuth tokens.
For strict BYOK API key encryption, see key_vault.py.
"""

from typing import Optional

import structlog
from cryptography.fernet import Fernet, InvalidToken

from apps.api.config import settings

logger = structlog.get_logger()

_fernet: Optional[Fernet] = None


def _get_fernet() -> Optional[Fernet]:
    """Lazy-init the Fernet cipher. Returns None if no key is configured."""
    global _fernet
    if _fernet is not None:
        return _fernet
    key = settings.token_encryption_key
    if not key:
        return None
    try:
        _fernet = Fernet(key.encode())
        return _fernet
    except Exception:
        logger.error("invalid_token_encryption_key", hint="Must be a valid Fernet key")
        return None


def encrypt_token(plaintext: str) -> str:
    """Encrypt a token string. Returns ciphertext or plaintext if no key."""
    f = _get_fernet()
    if f is None:
        return plaintext
    return f.encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a token string. Returns plaintext if decryption fails or no key."""
    f = _get_fernet()
    if f is None:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        # Token was stored before encryption was enabled -- return as-is
        logger.warning("token_decrypt_failed_returning_raw")
        return ciphertext
