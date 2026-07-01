"""UTM link decoration: encrypt/decrypt email → _bid parameter.

Usage:
  bid = generate_bid("user@example.com")
  # → append ?_bid=<bid> to any outbound link in Beam-generated emails

  email = decode_bid(bid)
  # → "user@example.com" (or None if invalid/tampered)

  html = decorate_links(html, "user@example.com", "acme.com")
  # → every link to acme.com carries ?_bid=<bid>; a click resolves the visitor
  #   deterministically when they land on the Beam-pixel'd site.

The encryption key comes from settings.encryption_key (Fernet 32-byte key,
base64-encoded). If the key is not configured, generate_bid raises RuntimeError
and decode_bid returns None — callers must handle this gracefully.
"""

import re
from urllib.parse import urlsplit, urlunsplit

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


_URL_RE = re.compile(r'https?://[^\s"\'<>)]+')


def _bare_host(netloc: str) -> str:
    """Lowercased host from a URL netloc, minus userinfo/port and a www. prefix."""
    h = netloc.lower().split("@")[-1].split(":")[0]
    return h[4:] if h.startswith("www.") else h


def decorate_links(html: str, email: str, site_host: str | None) -> str:
    """Append ?_bid=<token> to every link in `html` that points to `site_host`.

    A click then lands on the customer's Beam-pixel'd site with the encrypted
    email, resolving the visitor DETERMINISTICALLY — the residential-safe, MPP-
    proof identity signal (clicks fire from the real device, unlike opens).

    ONLY the customer's own host (and its subdomains) is decorated: the encrypted
    _bid token is never leaked to third-party domains. No-op when the key/host is
    missing, the email is empty, or a link already carries a _bid.
    """
    if not html or not email or not site_host:
        return html
    try:
        token = generate_bid(email)
    except Exception:
        return html
    host = _bare_host(site_host)
    if not host:
        return html

    def _repl(match: re.Match[str]) -> str:
        url = match.group(0)
        # The URL regex greedily grabs trailing sentence punctuation — peel it off
        # so we rewrite only the real URL and re-attach the punctuation after.
        trail = ""
        while url and url[-1] in ".,;:!?)]}":
            trail = url[-1] + trail
            url = url[:-1]
        parts = urlsplit(url)
        h = _bare_host(parts.netloc)
        if not (h == host or h.endswith("." + host)):
            return url + trail
        if "_bid=" in parts.query:
            return url + trail
        # Append verbatim: Fernet tokens are URL-safe base64; keeping the token
        # unencoded means the browser hands it straight to decode_bid (URLSearchParams
        # returns it as-is). Existing query params are preserved untouched.
        new_query = (parts.query + "&" if parts.query else "") + "_bid=" + token
        rebuilt = urlunsplit(
            (parts.scheme, parts.netloc, parts.path, new_query, parts.fragment)
        )
        return rebuilt + trail

    return _URL_RE.sub(_repl, html)


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
