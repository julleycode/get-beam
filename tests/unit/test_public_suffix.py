"""Unit gates for the vendored Public Suffix List parser (WS-D, group i).

This is the REGISTRABLE-DOMAIN layer. It proves ``registrable_domain`` in
isolation, including the ICANN-section-only scoping (Q10) via the amazonaws proof
case — which lives HERE and only here (R12). The resolver layer
(``test_company_resolver.py``) asserts the FILTERED outcome for the same host,
because ``_DOMAIN_PATTERNS`` rejects ``amazonaws``; the two layers are different
and must not contradict.

Every test that varies underlying state clears the loader cache (E6a); the file
is read-only here so a module-level call is enough, but cache_clear keeps this
robust against cross-test ordering.
"""

import pytest

from apps.api.services.public_suffix import _load_rules, registrable_domain

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_psl_cache():
    # E6a: _load_rules is @lru_cache(maxsize=1); clear before each test.
    _load_rules.cache_clear()
    yield
    _load_rules.cache_clear()


class TestRegistrableDomain:
    @pytest.mark.parametrize(
        "hostname,expected",
        [
            ("mail.google.com", "google.com"),
            ("vpn-us.apple.com", "apple.com"),
            ("a.b.co.uk", "b.co.uk"),
            ("foo.bar.gov.br", "bar.gov.br"),
            # FAIL-3 corrections: suffix + exactly one label (D2 spec).
            ("x.co.za", "x.co.za"),
            ("x.co.uk", "x.co.uk"),  # the WIDENS class at the PSL layer
            # A bare public suffix with nothing in front → None.
            ("co.uk", None),
            # Unknown TLD → implicit "*" rule → suffix is the last label.
            ("host.invalidtld", "host.invalidtld"),
            # Empty / single-label input → None.
            ("", None),
            ("localhost", None),
            # ICANN-section-only proof (Q10): the PRIVATE-section rule
            # compute.amazonaws.com is NOT loaded, so the registrable domain
            # collapses to amazonaws.com (which the resolver layer then filters).
            ("ec2-1-2-3-4.compute-1.amazonaws.com", "amazonaws.com"),
        ],
    )
    def test_registrable_domain_matrix(self, hostname, expected):
        assert registrable_domain(hostname) == expected

    def test_a_wildcard_rule(self):
        # `*.ck` + `!www.ck` are in the PSL. Per the D2 spec (public suffix +
        # exactly one more label) the registrable domain of `a.b.ck` is `a.b.ck`
        # (public suffix `b.ck` via the wildcard, plus one label `a`). NOTE: the
        # plan's D5 cell states `b.ck`, which contradicts the D2 spec; per FAIL-3
        # precedence the D2 spec wins and the discrepancy is surfaced. The real
        # eTLD+1 of `a.b.ck` is `a.b.ck`.
        assert registrable_domain("a.b.ck") == "a.b.ck"

    def test_an_exception_rule(self):
        # `!www.ck` makes `www.ck` NOT a public suffix; public suffix is `ck`, so
        # the registrable domain of `www.ck` is `www.ck`.
        assert registrable_domain("www.ck") == "www.ck"

    def test_ordinary_two_label_host(self):
        assert registrable_domain("example.com") == "example.com"

    def test_trailing_dot_and_case_are_normalized(self):
        assert registrable_domain("Mail.GOOGLE.com.") == "google.com"
