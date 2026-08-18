"""Unit tests for trusted-proxy-aware client IP resolution (AC-3, AC-8).

Pure logic — no DB, no network. Proves the resolver ignores untrusted
X-Forwarded-For, reads the correct entry behind N trusted hops, and NEVER raises
into the ingest request path regardless of how malformed the input is.
"""

import ipaddress

import pytest

from apps.api.services.ip_resolution import client_ip_key_func, resolve_client_ip

pytestmark = pytest.mark.unit

_REAL_PEER = "198.51.100.10"


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    """Minimal Request stand-in — resolve_client_ip only reads .client/.headers."""

    def __init__(self, headers=None, peer=_REAL_PEER):
        self.headers = headers or {}
        self.client = _FakeClient(peer) if peer is not None else None


def test_zero_hops_ignores_xff_header():
    """AC-3: with no trusted proxies, a forged XFF is ignored entirely."""
    req = _FakeRequest({"x-forwarded-for": "1.2.3.4, 5.6.7.8"})
    assert resolve_client_ip(req, trusted_proxy_hops=0) == _REAL_PEER


def test_one_hop_reads_rightmost_xff_entry():
    """AC-8: with 1 trusted proxy, the rightmost entry is the trusted value."""
    req = _FakeRequest({"x-forwarded-for": "203.0.113.9, 192.0.2.44"})
    assert resolve_client_ip(req, trusted_proxy_hops=1) == "192.0.2.44"


def test_two_hops_reads_second_from_right():
    """AC-8: with 2 trusted hops, index -2 is the last unforgeable entry."""
    req = _FakeRequest({"x-forwarded-for": "203.0.113.9, 192.0.2.44, 10.0.0.1"})
    assert resolve_client_ip(req, trusted_proxy_hops=2) == "192.0.2.44"


def test_misconfigured_hops_falls_back_safely():
    """AC-3/AC-8: hops deeper than the real chain must NOT index out of range."""
    req = _FakeRequest({"x-forwarded-for": "1.2.3.4"})
    assert resolve_client_ip(req, trusted_proxy_hops=5) == _REAL_PEER


def test_malformed_xff_header_falls_back_safely():
    """A garbage header value must fall back, never raise."""
    for junk in (",,,", "   ", ",", "\x00\x01"):
        req = _FakeRequest({"x-forwarded-for": junk})
        result = resolve_client_ip(req, trusted_proxy_hops=1)
        assert result in (_REAL_PEER, junk.strip())


def test_missing_xff_with_hops_configured_falls_back():
    """Header absent while hops is configured: fall back to the socket peer."""
    req = _FakeRequest({})
    assert resolve_client_ip(req, trusted_proxy_hops=1) == _REAL_PEER


def test_no_client_returns_empty_string():
    """A request with no socket peer must return "" rather than raising."""
    req = _FakeRequest({}, peer=None)
    assert resolve_client_ip(req, trusted_proxy_hops=0) == ""


def test_non_integer_hops_falls_back_safely():
    """A non-numeric trusted_proxy_hops must fail safe, not raise."""
    req = _FakeRequest({"x-forwarded-for": "1.2.3.4"})
    assert resolve_client_ip(req, trusted_proxy_hops="not-a-number") == _REAL_PEER


def test_negative_hops_treated_as_trust_nothing():
    req = _FakeRequest({"x-forwarded-for": "1.2.3.4"})
    assert resolve_client_ip(req, trusted_proxy_hops=-3) == _REAL_PEER


def test_key_func_never_returns_empty():
    """slowapi must always get a non-empty bucket key."""
    assert client_ip_key_func(_FakeRequest({}, peer=None)) == "unknown"


def test_key_func_defaults_to_settings_and_ignores_xff():
    """Default settings are trusted_proxy_hops=0 → forged XFF cannot rebucket."""
    a = client_ip_key_func(_FakeRequest({"x-forwarded-for": "9.9.9.9"}))
    b = client_ip_key_func(_FakeRequest({"x-forwarded-for": "8.8.8.8"}))
    assert a == b == _REAL_PEER


def test_cf_connecting_ip_used_when_flag_on(monkeypatch):
    """CF-Connecting-IP wins when the flag is on AND the peer is a CF edge."""
    from apps.api.config import settings

    monkeypatch.setattr(settings, "ingest_trust_cf_connecting_ip", True)
    req = _FakeRequest(
        {"cf-connecting-ip": "203.0.113.77", "x-forwarded-for": "1.2.3.4, 5.6.7.8"},
        peer="104.16.1.1",  # inside bundled 104.16.0.0/13
    )
    assert resolve_client_ip(req, trusted_proxy_hops=0) == "203.0.113.77"


def test_cf_connecting_ip_ignored_when_flag_off(monkeypatch):
    """Flag off: CF header is ignored, old hop-count behaviour applies."""
    from apps.api.config import settings

    monkeypatch.setattr(settings, "ingest_trust_cf_connecting_ip", False)
    req = _FakeRequest({"cf-connecting-ip": "203.0.113.77"})
    assert resolve_client_ip(req, trusted_proxy_hops=0) == _REAL_PEER


def test_cf_connecting_ip_falls_back_on_malformed_value(monkeypatch):
    """A garbage CF-Connecting-IP value must fall back, never raise."""
    from apps.api.config import settings

    monkeypatch.setattr(settings, "ingest_trust_cf_connecting_ip", True)
    req = _FakeRequest({"cf-connecting-ip": "not-an-ip, stuff"})
    assert resolve_client_ip(req, trusted_proxy_hops=0) == _REAL_PEER


@pytest.mark.parametrize("peer", ["8.8.8.8", "1.2.3.4"])
def test_cf_connecting_ip_ignored_when_peer_not_cloudflare(monkeypatch, peer):
    """Direct-origin spoof: CF-Connecting-IP must not mint the limiter key."""
    from apps.api.config import settings

    monkeypatch.setattr(settings, "ingest_trust_cf_connecting_ip", True)
    req = _FakeRequest({"cf-connecting-ip": "203.0.113.77"}, peer=peer)
    assert resolve_client_ip(req, trusted_proxy_hops=0) == peer


def test_cf_connecting_ip_trusted_when_peer_in_cf_range(monkeypatch):
    """Header is trusted only when the TCP peer is in the bundled CF snapshot."""
    from apps.api.config import settings
    from apps.api.services.ip_resolution import CLOUDFLARE_NETWORKS, peer_is_cloudflare

    cf_peer = "172.64.0.1"  # 172.64.0.0/13
    assert peer_is_cloudflare(cf_peer)
    assert any(ipaddress.ip_address(cf_peer) in net for net in CLOUDFLARE_NETWORKS)

    monkeypatch.setattr(settings, "ingest_trust_cf_connecting_ip", True)
    req = _FakeRequest({"cf-connecting-ip": "203.0.113.88"}, peer=cf_peer)
    assert resolve_client_ip(req, trusted_proxy_hops=0) == "203.0.113.88"


def test_peer_is_cloudflare_unwraps_ipv4_mapped_ipv6():
    """Dual-stack ::ffff:x.x.x.x peers must match IPv4 CF ranges."""
    from apps.api.services.ip_resolution import peer_is_cloudflare

    assert peer_is_cloudflare("104.16.1.1")
    assert peer_is_cloudflare("::ffff:104.16.1.1")
    assert not peer_is_cloudflare("::ffff:8.8.8.8")


def test_cf_connecting_ip_trusted_when_peer_is_ipv4_mapped_cf(monkeypatch):
    """IPv4-mapped CF peer still honours CF-Connecting-IP."""
    from apps.api.config import settings
    from apps.api.services.ip_resolution import peer_is_cloudflare

    mapped = "::ffff:104.16.1.1"
    assert peer_is_cloudflare(mapped)
    monkeypatch.setattr(settings, "ingest_trust_cf_connecting_ip", True)
    req = _FakeRequest({"cf-connecting-ip": "203.0.113.88"}, peer=mapped)
    assert resolve_client_ip(req, trusted_proxy_hops=0) == "203.0.113.88"


def test_peer_is_cloudflare_ipv6_covers_published_slash29():
    """2a06:98c0::/29 includes 2a06:98c1:: which the old /32 missed."""
    from apps.api.services.ip_resolution import CLOUDFLARE_NETWORKS, peer_is_cloudflare

    assert any(str(net) == "2a06:98c0::/29" for net in CLOUDFLARE_NETWORKS)
    assert peer_is_cloudflare("2a06:98c0::1")
    assert peer_is_cloudflare("2a06:98c1::1")
    assert peer_is_cloudflare("2a06:98c7::1")
    assert not peer_is_cloudflare("2a06:98c8::1")
