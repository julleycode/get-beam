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

Cloudflare's ``CF-Connecting-IP`` header is checked first (gated by
``settings.ingest_trust_cf_connecting_ip``, default on) since a permanently
CF-proxied origin sees only CF edge IPs at the direct peer — the trusted-hop
XFF walk below can't recover the real client in that topology. The header is
honoured only when the direct peer is inside the bundled Cloudflare CIDR
snapshot; a caller that hits the origin directly cannot mint limiter keys by
forging it.
"""

import ipaddress

import structlog
from fastapi import Request

logger = structlog.get_logger()

# Snapshot of Cloudflare published ranges. Source: https://www.cloudflare.com/ips/
# (https://www.cloudflare.com/ips-v4 and https://www.cloudflare.com/ips-v6).
# Static — do not fetch the internet at request time. Refresh when CF publishes
# a range change.
_CLOUDFLARE_CIDRS = (
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
)
CLOUDFLARE_NETWORKS: frozenset[ipaddress.IPv4Network | ipaddress.IPv6Network] = (
    frozenset(ipaddress.ip_network(cidr) for cidr in _CLOUDFLARE_CIDRS)
)


def peer_is_cloudflare(peer: str) -> bool:
    """True when ``peer`` is inside the bundled Cloudflare CIDR snapshot."""
    if not peer:
        return False
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    # Dual-stack sockets often present IPv4-mapped IPv6 (::ffff:x.x.x.x).
    # Unwrap so those peers still match the IPv4 CF ranges.
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addr = mapped
    return any(addr in network for network in CLOUDFLARE_NETWORKS)


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

    try:
        from apps.api.config import settings as _cf_settings

        if _cf_settings.ingest_trust_cf_connecting_ip:
            cf_ip = request.headers.get("cf-connecting-ip")
            if cf_ip:
                cf_ip = cf_ip.strip()
                try:
                    ipaddress.ip_address(cf_ip)
                except ValueError:
                    pass  # malformed — fall through to hop-count logic
                else:
                    # Honour CF-Connecting-IP only when the TCP peer is a CF edge.
                    # Direct-origin spoof (8.8.8.8 / 1.2.3.4) must not mint keys.
                    if peer_is_cloudflare(direct):
                        return cf_ip
    except Exception:
        pass  # never let CF-header handling break ingest

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
