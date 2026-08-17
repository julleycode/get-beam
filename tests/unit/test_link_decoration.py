"""Own-data P7: email-click _bid link decoration.

Every campaign link to the customer's OWN site is stamped with the recipient's
encrypted email (_bid); a click resolves that visitor deterministically on
arrival (residential-safe, MPP-proof). The token is NEVER put on third-party
links, and the plaintext email never appears in the URL.
"""
import re

from apps.api.services.link_decorator import decode_bid, decorate_links


def _bids(html: str) -> list[str]:
    return re.findall(r"[?&]_bid=([^&\s\"'<>)]+)", html)


class TestDecorateLinks:
    def test_own_site_link_gets_bid_that_roundtrips(self):
        html = 'Check <a href="https://acme.com/pricing">pricing</a>.'
        out = decorate_links(html, "cto@buyer.com", "acme.com")
        tokens = _bids(out)
        assert len(tokens) == 1
        assert decode_bid(tokens[0]) == "cto@buyer.com"

    def test_plaintext_email_never_in_output(self):
        out = decorate_links("https://acme.com/x", "cto@buyer.com", "acme.com")
        assert "cto@buyer.com" not in out
        assert "cto%40buyer.com" not in out  # not URL-encoded either

    def test_www_and_subdomain_match(self):
        out = decorate_links(
            "a https://www.acme.com/a b https://app.acme.com/b", "u@x.com", "acme.com"
        )
        assert len(_bids(out)) == 2

    def test_third_party_link_not_decorated(self):
        # The encrypted token must never leak to a domain Beam doesn't control.
        html = "book https://calendly.com/acme and buy https://acme.com/buy"
        out = decorate_links(html, "u@x.com", "acme.com")
        assert "calendly.com/acme" in out
        assert "_bid" not in out.split("acme.com/buy")[0]  # only the acme link tagged
        assert len(_bids(out)) == 1

    def test_booking_url_on_third_party_host_not_decorated(self):
        """A site's configured booking_url on a third-party host stays clean.

        This is a PRIVACY guarantee, not a link-parsing limitation: the _bid
        token encrypts the recipient's email, so handing it to Calendly/Cal.com
        would leak it. The consequence — booking clicks carry no _tp/_bid, so
        attribution runs through the customer's own thank-you page instead — is
        documented in decorate_links and the backlog note.
        """
        booking_url = "https://cal.com/acme/demo"
        html = f'Book: <a href="{booking_url}">demo</a> or <a href="https://acme.com/pricing">pricing</a>'
        out = decorate_links(html, "u@x.com", "acme.com")
        # The booking link survives byte-for-byte — no _bid, no _tp appended.
        assert booking_url + '"' in out
        # Non-vacuity control: the same-host link in the SAME call IS decorated,
        # so a no-op decorate_links (e.g. unset encryption_key) fails here.
        assert len(_bids(out)) == 1
        assert "acme.com/pricing?_bid=" in out

    def test_existing_query_and_bid_preserved(self):
        html = "https://acme.com/p?ref=email and https://acme.com/q?_bid=already"
        out = decorate_links(html, "u@x.com", "acme.com")
        assert "ref=email" in out and "_bid=" in out.split("ref=email")[1]  # appended, not clobbered
        assert out.count("_bid=already") == 1  # link that already had _bid is untouched

    def test_trailing_punctuation_preserved(self):
        out = decorate_links("Visit https://acme.com/x.", "u@x.com", "acme.com")
        assert out.rstrip().endswith(".")
        assert len(_bids(out)) == 1

    def test_noop_without_email_or_host(self):
        html = "https://acme.com/x"
        assert decorate_links(html, "", "acme.com") == html
        assert decorate_links(html, "u@x.com", None) == html
        assert decorate_links(html, "u@x.com", "") == html

    def test_same_token_reused_across_links(self):
        html = "https://acme.com/a https://acme.com/b https://acme.com/c"
        toks = _bids(decorate_links(html, "u@x.com", "acme.com"))
        assert len(toks) == 3 and len(set(toks)) == 1  # one encrypt, reused
