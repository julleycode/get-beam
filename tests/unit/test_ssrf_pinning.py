"""DNS-rebinding / IP-pinning tests for the SSRF guard.

The plain guard resolved DNS at check time and let httpx re-resolve at connect
time — a TOCTOU a short-TTL rebinding record exploits (public answer at check,
private answer at connect). ``pinned_client`` resolves + validates INSIDE the
transport and connects to that exact IP, so the connect can never land on a
different address than the one validated. Also covers IPv4-mapped-IPv6 metadata
and the port allowlist.
"""

import socket

import httpx
import pytest

from apps.api.services.url_guard import (
    _addr_is_safe,
    is_safe_public_url,
    pinned_client,
)


def _gai(ip: str):
    """A socket.getaddrinfo-shaped result for a single address."""
    fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(fam, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 0))]


@pytest.mark.parametrize(
    "ip",
    [
        "::ffff:169.254.169.254",  # cloud metadata via IPv4-mapped IPv6
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "::1",
    ],
)
def test_addr_is_safe_rejects_internal(ip):
    assert _addr_is_safe(ip) is False


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34"])
def test_addr_is_safe_allows_public(ip):
    assert _addr_is_safe(ip) is True


async def test_non_standard_port_rejected():
    # Port allowlist: a public host on an internal-service port is refused even
    # though the address itself is public.
    assert await is_safe_public_url("http://8.8.8.8:6379/") is False
    assert await is_safe_public_url("https://1.1.1.1:8443/") is False


async def test_pinned_client_connects_to_validated_ip(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _gai("93.184.216.34"))
    captured: dict = {}

    async def fake_super(self, request):
        captured["host"] = request.url.host
        captured["Host"] = request.headers.get("Host")
        captured["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_super)

    async with pinned_client() as c:
        r = await c.post("https://example.test/hook", json={"x": 1})

    assert r.status_code == 200
    assert captured["host"] == "93.184.216.34"  # connect targets the pinned IP
    assert captured["Host"] == "example.test"   # Host header keeps the hostname
    assert captured["sni"] == "example.test"    # TLS SNI/cert keep the hostname


async def test_pinned_client_refuses_private(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _gai("169.254.169.254"))
    hit = {"super": False}

    async def fake_super(self, request):
        hit["super"] = True
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_super)

    async with pinned_client() as c:
        with pytest.raises(httpx.RequestError):
            await c.post("https://evil.test/hook", json={})
    assert hit["super"] is False  # refused before any connection was attempted


async def test_pinning_defeats_dns_rebinding(monkeypatch):
    """The core scenario: public at check time, private at connect time."""
    calls = {"n": 0}

    def rebinding_gai(*a, **k):
        calls["n"] += 1
        return _gai("8.8.8.8") if calls["n"] == 1 else _gai("169.254.169.254")

    monkeypatch.setattr(socket, "getaddrinfo", rebinding_gai)

    async def fake_super(self, request):
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_super)

    # Check-time resolution says public...
    assert await is_safe_public_url("https://rebind.test/") is True
    # ...but the transport re-resolves at connect and gets the private answer,
    # so the connect is refused instead of reaching the internal address.
    async with pinned_client() as c:
        with pytest.raises(httpx.RequestError):
            await c.post("https://rebind.test/hook", json={})
