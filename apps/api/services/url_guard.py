"""SSRF guard for user-supplied outbound URLs (CRM generic webhook).

A site owner can set an arbitrary webhook URL that our server then POSTs to.
Without a guard that is an SSRF vector — a customer could aim it at cloud
metadata (169.254.169.254), localhost, or an internal host and use Beam as a
proxy into our own network. We reject any URL whose host resolves to a
private / loopback / link-local / reserved address.

Note: this resolves DNS at check time. It does not fully close a DNS-rebinding
window (the address could change between check and connect), but it blocks the
obvious cases. Callers should re-check before each outbound request, not just at
save time.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpx
import structlog

logger = structlog.get_logger()


def _is_public_http_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except (socket.gaierror, UnicodeError):
        return False
    if not infos:
        return False
    for info in infos:
        ip_str = info[4][0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            return False
    return True


async def is_safe_public_url(url: str) -> bool:
    """Async wrapper — DNS resolution runs in a thread so it never blocks the loop."""
    return await asyncio.to_thread(_is_public_http_url, url)


async def safe_get(
    client: httpx.AsyncClient, url: str, *, max_redirects: int = 3
) -> httpx.Response:
    """GET that follows redirects MANUALLY, re-validating each hop against the
    SSRF guard so a public URL cannot 30x into a private/internal address.

    The caller's client should be created with follow_redirects=False. Raises
    httpx.RequestError if a redirect points at a non-public URL.
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
