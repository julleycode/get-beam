"""Trusted-proxy-aware client IP resolution.

Replaces the previously spoofable ``_extract_ip`` in ``routers/events.py``, which
took the FIRST ``X-Forwarded-For`` entry verbatim with no trust check — a value
any caller can set, letting an attacker mint a fresh rate-limit / abuse-detection
bucket per request.

Trust model: only the app operator knows how many reverse proxies sit in front of
the app, so that count is configuration (``settings.trusted_proxy_hops``), never
inferred from the request. With N trusted hops, the rightmost N entries of XFF
were appended by infrastructure we control; entry ``[-N]`` is therefore the last
value a caller could NOT forge. With N = 0 (the default) the header is ignored
entirely.

Choosing N is a trust-boundary decision, not a tuning knob: N too high lets a
caller forge their own limiter key (bypass), N too low collapses every visitor
into the proxy's single bucket (mass 429). The full tradeoff and the rollout
rules live on ``trusted_proxy_hops`` in ``apps/api/config.py`` — read that
comment before changing the value.

This function must NEVER raise into the ingest request path: every failure mode —
absent header, malformed value, chain shorter than the configured hop count,
unexpected exception — falls back to ``request.client.host``.
"""

import structlog
from fastapi import Request

logger = structlog.get_logger()


def resolve_client_ip(request: Request, trusted_proxy_hops: int | None = None) -> str:
    """Return the caller's client IP, honouring only trusted proxy hops.

    ``trusted_proxy_hops`` defaults to ``settings.trusted_proxy_hops`` when None
    (an explicit argument keeps this unit-testable without patching settings).
    """
    direct = ""
    try:
        if request.client is not None:
            direct = request.client.host or ""
    except Exception:  # pragma: no cover — defensive; Request.client is a property
        direct = ""

    if trusted_proxy_hops is None:
        try:
            from apps.api.config import settings

            trusted_proxy_hops = settings.trusted_proxy_hops
        except Exception:
            return direct

    try:
        hops = int(trusted_proxy_hops)
    except (TypeError, ValueError):
        return direct

    # Trust nothing: the forwarded header is untrusted input, ignore it.
    if hops <= 0:
        return direct

    try:
        forwarded = request.headers.get("x-forwarded-for")
        if not forwarded:
            return direct

        entries = [part.strip() for part in forwarded.split(",")]
        entries = [part for part in entries if part]

        # Chain shorter than the configured depth = misconfiguration (or a caller
        # that stripped entries). Fail safe rather than index out of range or
        # trust an attacker-supplied entry.
        if len(entries) < hops:
            return direct

        return entries[-hops] or direct
    except Exception:
        # Defense in depth: never 500 the ingest endpoint over IP resolution.
        return direct


def client_ip_key_func(request: Request) -> str:
    """slowapi ``key_func`` — per-IP limiter bucket keyed on the resolved IP.

    Replaces ``slowapi.util.get_remote_address``. At the default
    ``trusted_proxy_hops = 0`` this is byte-identical to the old behaviour
    (``request.client.host``); behind N trusted proxies it keys on the real
    client instead of collapsing every visitor into the proxy's single bucket.
    """
    return resolve_client_ip(request) or "unknown"
