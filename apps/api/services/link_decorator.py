"""UTM link decoration: encrypt/decrypt email → _bid parameter.

Usage:
  bid = generate_bid("user@example.com")
  # → append ?_bid=<bid> to any outbound link in Beam-generated emails

  email = decode_bid(bid)
  # → "user@example.com" (or None if invalid/tampered)

The encryption key comes from settings.encryption_key (Fernet 32-byte key,
base64-encoded). If the key is not configured, generate_bid raises RuntimeError
and decode_bid returns None — callers must handle this gracefully.
"""

import structlog
from cryptography.fernet import Fernet, InvalidToken

from apps.api.config import settings

logger = structlog.get_logger()


def _get_fernet() -> Fernet | None:
    """Return a Fernet instance using settings.encryption_key, or None if unconfigured."""
    key = settings.encryption_key
    if not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:
        logger.warning("link_decorator_invalid_key", error=str(exc))
        return None


def generate_bid(email: str) -> str:
    """Encrypt an email address into a URL-safe _bid token.

    Raises RuntimeError if ENCRYPTION_KEY is not configured.
    """
    fernet = _get_fernet()
    if fernet is None:
        raise RuntimeError(
            "ENCRYPTION_KEY is not configured — cannot generate _bid tokens. "
            "Set a valid Fernet key in your environment."
        )
    token: bytes = fernet.encrypt(email.encode("utf-8"))
    # Fernet tokens are already URL-safe base64
    return token.decode("ascii")


def decode_bid(bid: str) -> str | None:
    """Decrypt a _bid token back to an email address.

    Returns None if the token is invalid, tampered, expired, or the key is
    not configured — never raises.
    """
    fernet = _get_fernet()
    if fernet is None:
        logger.debug("link_decorator_decode_skipped_no_key")
        return None
    try:
        plaintext: bytes = fernet.decrypt(bid.encode("ascii") if isinstance(bid, str) else bid)
        return plaintext.decode("utf-8")
    except InvalidToken:
        logger.warning("link_decorator_invalid_token", bid_prefix=bid[:12] if bid else "")
        return None
    except Exception as exc:
        logger.warning("link_decorator_decode_error", error=str(exc))
        return None


def generate_unsubscribe_token(email: str) -> str:
    """Encrypt an email address into a signed, URL-safe unsubscribe token.

    Same Fernet instance/key as generate_bid. Raises RuntimeError if
    ENCRYPTION_KEY is not configured.
    """
    return generate_bid(email)


def decode_unsubscribe_token(token: str) -> str | None:
    """Decode a signed unsubscribe token back to an email address.

    Returns None if the token is invalid, forged, tampered, expired, or the
    key is not configured — never raises.
    """
    return decode_bid(token)
