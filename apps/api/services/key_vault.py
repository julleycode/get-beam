"""Encrypt and decrypt user-provided API keys at rest using Fernet."""

import structlog
from cryptography.fernet import Fernet, InvalidToken

from apps.api.config import settings

logger = structlog.get_logger()

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = settings.encryption_key
        if not key:
            raise RuntimeError(
                "ENCRYPTION_KEY env var is required for BYOK key management. "
                "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt_key(plaintext: str) -> str:
    """Encrypt an API key. Returns base64-encoded ciphertext."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_key(ciphertext: str) -> str:
    """Decrypt an API key. Raises ValueError if the key is corrupted."""
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        logger.error("key_decrypt_failed", hint="encryption key may have changed")
        raise ValueError("Failed to decrypt API key — encryption key may have changed")


def make_key_hint(api_key: str) -> str:
    """Return a safe display hint like '...abc1' (last 4 chars)."""
    if len(api_key) <= 4:
        return "****"
    return f"...{api_key[-4:]}"
