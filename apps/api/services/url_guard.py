"""SSRF guard for user-supplied outbound URLs (CRM generic webhook).

A site owner can set an arbitrary webhook URL that our server then POSTs to.
Without a guard that is an SSRF vector — a customer could aim it at cloud
metadata (169.254.169.254), localhost, or an internal host and use Beam as a
proxy into our own network. We reject any URL whose host resolves to a
private / loopback / link-local / reserved address.

DNS rebinding: a plain "resolve, validate, then let httpx connect" is a TOCTOU
— httpx re-resolves the hostname at connect time, so a short-TTL record can
answer public at check time and private at connect time. ``pinned_client``
closes that window: it resolves + validates INSIDE the transport and connects
to that exact validated IP, while TLS SNI and certificate validation still use
the original hostname. Use ``pinned_client`` (not a bare ``httpx.AsyncClient``)
for any request to a user-supplied URL.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpx
import structlog

logger = structlog.get_logger()

# Only standard web ports. Blocks aiming a "public" hostname at an internal
# service on an odd port (Redis 6379, Postgres 5432, …); the IP checks below
# already block internal *addresses* regardless of port, this is defense in depth.
_ALLOWED_PORTS = {80, 443}


def _addr_is_safe(ip_str: str) -> bool:
    """True only if ``ip_str`` is a routable public address. Rejects private,
    loopback, link-local (incl. cloud metadata 169.254.x), reserved, multicast
    and unspecified. IPv4-mapped IPv6 (``::ffff:169.254.169.254``) is unwrapped
    and its embedded IPv4 validated too, so it cannot smuggle an internal v4."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    candidates = [addr]
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        candidates.append(mapped)
    for a in candidates:
        if (
            a.is_private
            or a.is_loopback
            or a.is_link_local
            or a.is_reserved
            or a.is_multicast
            or a.is_unspecified
        ):
            return False
    return True


def _resolve_safe_ip(host: str, port: int) -> str | None:
    """Resolve ``host`` and return a single validated IP to connect to, or None
    if resolution fails or ANY resolved address is non-public. Rejecting when
    any address is unsafe (not just picking a safe one) matches the original
    conservative guard and avoids a mixed public/private record set."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return None
    if not infos:
        return None
    ip_strs = [info[4][0] for info in infos]
    if not all(_addr_is_safe(ip) for ip in ip_strs):
        return None
    return ip_strs[0]


def _is_public_http_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in _ALLOWED_PORTS:
        return False
    return _resolve_safe_ip(parsed.hostname, port) is not None


async def is_safe_public_url(url: str) -> bool:
    """Async wrapper — DNS resolution runs in a thread so it never blocks the loop.

    A fast pre-check for a clear error message; the authoritative guard against
    rebinding is ``pinned_client``, which re-resolves + pins at connect time."""
    return await asyncio.to_thread(_is_public_http_url, url)


class _PinnedTransport(httpx.AsyncHTTPTransport):
    """Resolve + validate the target host and connect ONLY to that validated IP.

    Rewrites the request URL's host to the pinned IP so httpcore cannot
    re-resolve to a different (rebound) address, while restoring the original
    hostname as the ``Host`` header and the TLS ``sni_hostname`` so certificate
    validation is unchanged. If the extension is ignored on some httpcore build,
    the TLS handshake fails closed (cert vs IP mismatch) rather than open."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.scheme not in ("http", "https"):
            raise httpx.RequestError("blocked non-http(s) scheme")
        host = request.url.host
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        if port not in _ALLOWED_PORTS:
            raise httpx.RequestError(f"blocked non-standard port {port}")
        ip = await asyncio.to_thread(_resolve_safe_ip, host, port)
        if ip is None:
            raise httpx.RequestError("host resolves to a non-public address")
        request.headers["Host"] = host if port in (80, 443) else f"{host}:{port}"
        request.extensions = dict(request.extensions or {})
        request.extensions["sni_hostname"] = host
        request.url = request.url.copy_with(host=ip)
        return await super().handle_async_request(request)


def pinned_client(**kwargs) -> httpx.AsyncClient:
    """AsyncClient that pins DNS resolution to a validated public IP per request.

    Redirects are NOT followed automatically (use ``safe_get`` to follow them
    with per-hop re-validation). Pass ``timeout=`` etc. through ``kwargs``."""
    kwargs.setdefault("follow_redirects", False)
    return httpx.AsyncClient(transport=_PinnedTransport(), **kwargs)


async def safe_get(
    client: httpx.AsyncClient, url: str, *, max_redirects: int = 3
) -> httpx.Response:
    """GET that follows redirects MANUALLY, re-validating each hop against the
    SSRF guard so a public URL cannot 30x into a private/internal address.

    Pass a ``pinned_client`` so each hop also connects to its validated IP
    (closing the rebinding window). Raises httpx.RequestError on a non-public
    redirect target.
    """
    resp = await client.get(url)
    redirects = 0
    while resp.is_redirect and redirects < max_redirects:
        location = resp.headers.get("location")
        if not location:
            break
        next_url = str(httpx.URL(resp.url).join(location))
        if not await is_safe_public_url(next_url):
            raise httpx.RequestError("redirect to non-public URL blocked")
        resp = await client.get(next_url)
        redirects += 1
    return resp
