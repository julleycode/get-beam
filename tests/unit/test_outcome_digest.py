"""Unit tests for the weekly outcomes digest email builder (no DB)."""

from apps.api.services.outcome_digest import DigestStats, build_digest_email


class TestBuildDigestEmail:
    def test_subject_and_body_contain_the_numbers(self):
        stats = DigestStats(
            sent=42, clicked=7, conversions=3, attributed=2, attributed_revenue_cents=12550
        )
        subject, html = build_digest_email("Acme Store", stats)
        assert subject == "Beam this week: 3 conversions for Acme Store"
        assert "<strong>42</strong> campaign emails sent" in html
        assert "<strong>7</strong> clicks" in html
        assert "<strong>3</strong> conversions" in html
        assert "<strong>2</strong> driven by Beam campaigns" in html
        assert "$125.50 attributed" in html
        assert "/dashboard/outcomes" in html

    def test_singular_conversion_and_no_revenue_suffix(self):
        stats = DigestStats(sent=5, clicked=1, conversions=1, attributed=0, attributed_revenue_cents=0)
        subject, html = build_digest_email("Solo Site", stats)
        assert subject == "Beam this week: 1 conversion for Solo Site"
        assert "attributed)" not in html  # zero revenue → no revenue suffix

    def test_site_name_is_escaped(self):
        stats = DigestStats(sent=1, clicked=0, conversions=0, attributed=0, attributed_revenue_cents=0)
        _, html = build_digest_email('<script>alert("x")</script>', stats)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
