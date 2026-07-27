"""Redact PII and credentials out of captured request/response bodies.

Pure, stateless, DB-free — no imports outside the stdlib. The admin request-log
middleware pipes every captured body through ``redact()`` before it reaches
Postgres, which is what keeps the repo guardrail "never log PII or prompt bodies"
intact while still leaving the JSON *shape* debuggable.

Two independent rules, applied together:

    key-based    a key whose name looks credential-shaped (password, token,
                 api_key, authorization, cookie, ...) has its whole value
                 replaced, no matter what the value looks like. This is the
                 stronger rule: it does not depend on recognizing the value.
    value-based  an email-shaped string anywhere becomes domain-only
                 (``a***@acme.com``), matching the domain-only logging pattern
                 the first-party capture path already uses.

Key matching is substring-based on the lowercased key, so ``X-Api-Key``,
``apiKey``, and ``user_api_key_2`` all match one ``api_key`` entry. That is
deliberately over-broad: a false redaction costs one unreadable debug field, a
missed one persists a live credential.

Depth and width are bounded (``_MAX_DEPTH`` / ``_MAX_ITEMS``) so a hostile or
pathological payload cannot make redaction itself the expensive part of a
request.
"""

import re
from typing import Any

REDACTED = "***"
TRUNCATED_SUFFIX = "…[truncated]"

# Substrings that mark a key as credential-shaped. Compared against the
# lowercased key, so one entry covers every casing/separator variant.
_SENSITIVE_KEY_PARTS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "cookie",
    "session",
    "credential",
    "private_key",
    "client_secret",
    "signature",
    "ssn",
    "card_number",
    "cvv",
)

# Deliberately loose: this runs over already-captured log data, so over-matching
# a near-email costs nothing while under-matching persists a real address.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Bounds. A payload deeper/wider than this is structurally not something an
# operator reads in a debug viewer anyway.
_MAX_DEPTH = 12
_MAX_ITEMS = 500
_MAX_STRING_LEN = 2_000


def mask_email(address: str) -> str:
    """``someone@acme.com`` -> ``s***@acme.com``. Domain kept, local part masked.

    The first character survives so two different senders on the same domain stay
    distinguishable in a log — enough to correlate, not enough to contact.
    """
    local, _, domain = address.partition("@")
    if not domain:
        return REDACTED
    head = local[:1] if local else ""
    return f"{head}***@{domain}"


def _normalize_key(key: str) -> str:
    """Lowercase and strip separators so one entry covers every casing/spelling.

    ``X-Api-Key``, ``apiKey``, ``api_key`` and ``API KEY`` all normalize to
    ``apikey``. Without this the hyphenated HTTP-header spelling — the single most
    common way a credential actually arrives — slips past a list written in
    snake_case.
    """
    return re.sub(r"[^a-z0-9]", "", key.lower())


# Same normalization applied to the list itself, so the two sides always agree.
_NORMALIZED_SENSITIVE_PARTS: tuple[str, ...] = tuple(
    _normalize_key(part) for part in _SENSITIVE_KEY_PARTS
)


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalize_key(key)
    return any(part in normalized for part in _NORMALIZED_SENSITIVE_PARTS)


def _redact_string(value: str) -> str:
    masked = _EMAIL_RE.sub(lambda m: mask_email(m.group(0)), value)
    if len(masked) > _MAX_STRING_LEN:
        return masked[:_MAX_STRING_LEN] + TRUNCATED_SUFFIX
    return masked


def redact(value: Any, _depth: int = 0) -> Any:
    """Recursively redact a decoded JSON value. Never raises, never mutates input.

    Returns a NEW structure; the caller's object is untouched. Unknown scalar
    types (int/float/bool/None) pass through as-is — they carry no PII on their
    own and keeping them makes the log readable.
    """
    if _depth > _MAX_DEPTH:
        return REDACTED

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for i, (key, item) in enumerate(value.items()):
            if i >= _MAX_ITEMS:
                out["__truncated__"] = f"{len(value) - _MAX_ITEMS} more keys"
                break
            key_str = str(key)
            if _is_sensitive_key(key_str):
                out[key_str] = REDACTED
            else:
                out[key_str] = redact(item, _depth + 1)
        return out

    if isinstance(value, (list, tuple)):
        items = list(value)[:_MAX_ITEMS]
        out_list = [redact(item, _depth + 1) for item in items]
        if len(value) > _MAX_ITEMS:
            out_list.append(f"__truncated__: {len(value) - _MAX_ITEMS} more items")
        return out_list

    if isinstance(value, str):
        return _redact_string(value)

    return value


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Redact a flat header map. Credential headers are dropped to ``***``.

    Kept separate from ``redact()`` because headers are always a flat str->str
    map and never need recursion — and because ``authorization`` / ``cookie``
    must be masked even though their *values* look nothing like an email.
    """
    return {
        key: REDACTED if _is_sensitive_key(key) else _redact_string(str(val))
        for key, val in headers.items()
    }
