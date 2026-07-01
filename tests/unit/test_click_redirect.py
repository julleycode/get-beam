"""Own-data P7c: email click-tracking redirect — pure-helper unit tests.

The redirect must be PII-safe (email rides as an opaque token, never plaintext)
and open-redirect-safe (only ever redirects to the site's own host).
"""
from urllib.parse import parse_qs, urlsplit

from apps.api.routers.click import build_click_url, safe_dest, svid_cookie_name
from apps.api.services.link_decorator import decode_bid


class TestSafeDest:
    def test_own_host(self):
        assert safe_dest("https://acme.com/x", "https://acme.com") == "https://acme.com/x"

    def test_subdomain_allowed(self):
        assert safe_dest("https://shop.acme.com/x", "https://acme.com") == "https://shop.acme.com/x"

    def test_www_allowed(self):
        assert safe_dest("https://www.acme.com/x", "https://acme.com") == "https://www.acme.com/x"

    def test_foreign_host_falls_back_to_homepage(self):
        assert safe_dest("https://evil.com/phish", "https://acme.com") == "https://acme.com"

    def test_non_http_scheme_falls_back(self):
        assert safe_dest("javascript:alert(1)", "https://acme.com") == "https://acme.com"
        assert safe_dest("", "https://acme.com") == "https://acme.com"

    def test_lookalike_and_suffix_hosts_blocked(self):
        assert safe_dest("https://notacme.com/x", "https://acme.com") == "https://acme.com"
        assert safe_dest("https://acme.com.evil.com/x", "https://acme.com") == "https://acme.com"
        assert safe_dest("https://acme-com.evil.com/x", "https://acme.com") == "https://acme.com"

    def test_userinfo_tricks(self):
        # Real host is after the @ — acme.com@evil.com resolves to evil.com (blocked);
        # evil.com@acme.com resolves to acme.com (allowed).
        assert safe_dest("https://acme.com@evil.com/x", "https://acme.com") == "https://acme.com"
        assert safe_dest("https://evil.com@acme.com/x", "https://acme.com") == "https://evil.com@acme.com/x"

    def test_backslash_and_whitespace_parser_differential_blocked(self):
        # Browsers treat \ as / in the authority; urlsplit does not. Reject outright.
        for bad in (
            "https://evil.com\\.acme.com/x",
            "https://evil.com\t.acme.com/x",
            "https://evil.com\n.acme.com/x",
            "https://acme.com /x",
        ):
            assert safe_dest(bad, "https://acme.com") == "https://acme.com"

    def test_protocol_relative_blocked(self):
        assert safe_dest("//evil.com/x", "https://acme.com") == "https://acme.com"


class TestBuildClickUrl:
    def test_builds_and_token_roundtrips(self):
        url = build_click_url("https://api.beam.fyi", "site_x", "https://acme.com/p", "cto@buyer.com")
        assert url.startswith("https://api.beam.fyi/c/site_x?t=")
        q = parse_qs(urlsplit(url).query)
        assert decode_bid(q["t"][0]) == "cto@buyer.com"
        assert q["u"][0] == "https://acme.com/p"

    def test_no_plaintext_email_in_url(self):
        url = build_click_url("https://api.beam.fyi", "s", "https://acme.com", "cto@buyer.com")
        assert "cto@buyer.com" not in url
        assert "cto%40buyer.com" not in url


def test_svid_cookie_name_matches_events_scheme():
    assert svid_cookie_name("beam_getbeam_fyi") == "_rta_svid_beam_getbeam_fyi"
    assert svid_cookie_name("a-b.c") == "_rta_svid_abc"  # non-alnum stripped, same as events.py
