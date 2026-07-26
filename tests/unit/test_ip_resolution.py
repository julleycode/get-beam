"""Unit tests for trusted-proxy-aware client IP resolution (AC-3, AC-8).

Pure logic — no DB, no network. Proves the resolver ignores untrusted
X-Forwarded-For, reads the correct entry behind N trusted hops, and NEVER raises
into the ingest request path regardless of how malformed the input is.
"""

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
