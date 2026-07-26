"""Unit tests for the daily activity digest email builder (no DB)."""

import pytest

from apps.api.services.daily_digest import (
    ActionItem,
    DailyStats,
    VisitorDetail,
    build_daily_email,
)


def _visitor(**overrides) -> VisitorDetail:
    base = dict(
        full_name="Dana Reed",
        email="dana@acme.com",
        phone=None,
        location="Austin, TX, US",
        job_title="VP Growth",
        company_name="Acme",
        industry="SaaS",
        seniority="vp",
        linkedin_url="https://linkedin.com/in/danareed",
        twitter_handle="@danareed",
        intent_score=72.0,
        pages_visited=4,
        is_new_today=True,
    )
    base.update(overrides)
    return VisitorDetail(**base)


class TestBuildDailyEmail:
    STATS = DailyStats(new_visitors=29, identified=3, enriched=2, pageviews=88)

    def test_subject_and_headline_numbers(self):
        subject, html = build_daily_email("Bravestep", self.STATS)
        assert subject == "Beam today: 3 identified, 29 new visitors on Bravestep"
        assert "<strong>29</strong> new visitors" in html
        assert "88 pageviews" in html
        assert "<strong>3</strong> identified" in html
        assert "<strong>2</strong> enriched" in html

    def test_singular_visitor_wording(self):
        stats = DailyStats(new_visitors=1, identified=0, enriched=0, pageviews=1)
        subject, _ = build_daily_email("Solo", stats)
        assert subject == "Beam today: 0 identified, 1 new visitor on Solo"

    def test_site_name_is_escaped(self):
        _, html = build_daily_email('<script>alert("x")</script>', self.STATS)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_owner_only_notice_always_present(self):
        _, html = build_daily_email("Bravestep", self.STATS)
        assert "don&rsquo;t forward it" in html


class TestActionsSection:
    STATS = DailyStats(new_visitors=4, identified=1, enriched=1, pageviews=9)

    def test_actions_render_with_links(self):
        actions = [
            ActionItem("2 visitors ready to identify", "Review", "/dashboard/visitors"),
            ActionItem("1 campaign ready to send", "Send", "/dashboard/campaigns"),
        ]
        _, html = build_daily_email("Bravestep", self.STATS, actions)
        assert "2 visitors ready to identify" in html
        assert "/dashboard/visitors" in html
        assert "/dashboard/campaigns" in html
        assert ">Send</a>" in html

    def test_no_actions_shows_caught_up(self):
        _, html = build_daily_email("Bravestep", self.STATS, [])
        assert "all caught up" in html

    def test_action_text_is_escaped(self):
        actions = [ActionItem("<b>2</b> visitors", "Review", "/dashboard/visitors")]
        _, html = build_daily_email("Bravestep", self.STATS, actions)
        assert "<b>2</b> visitors" not in html
        assert "&lt;b&gt;" in html


class TestVisitorDetailSection:
    STATS = DailyStats(new_visitors=5, identified=1, enriched=1, pageviews=12)

    def test_full_contact_detail_is_included(self):
        """Unlike the forwardable weekly digest, this one DOES carry contact
        details — that is the whole point of the owner-only daily report."""
        _, html = build_daily_email("Bravestep", self.STATS, [], [_visitor()])
        assert "Dana Reed" in html
        assert "dana@acme.com" in html
        assert "mailto:dana@acme.com" in html
        assert "VP Growth, Acme" in html
        assert "linkedin.com/in/danareed" in html
        assert "https://x.com/danareed" in html
        assert "intent 72" in html
        assert "4 pages" in html
        assert "Austin, TX, US" in html

    def test_new_badge_only_for_todays_identifications(self):
        _, fresh = build_daily_email("S", self.STATS, [], [_visitor()])
        _, older = build_daily_email(
            "S", self.STATS, [], [_visitor(is_new_today=False)]
        )
        assert ">new</span>" in fresh
        assert ">new</span>" not in older

    def test_email_only_row_uses_the_local_part_not_unnamed(self):
        """Identity-graph hits are usually email-only; labelling every one of
        them "Unnamed visitor" made a real digest unreadable."""
        _, html = build_daily_email(
            "S", self.STATS, [], [_visitor(full_name=None, email="theo@bitsentry.ai")]
        )
        assert "<strong>theo</strong>" in html
        assert "Unnamed visitor" not in html

    def test_company_is_the_last_resort_name_and_is_not_repeated(self):
        v = _visitor(
            full_name=None, email=None, company_name="Bitsentry", job_title="CTO"
        )
        _, html = build_daily_email("S", self.STATS, [], [v])
        assert "<strong>Bitsentry</strong>" in html
        assert "CTO, Bitsentry" not in html  # company consumed by the headline
        assert ">CTO<" in html

    def test_email_local_part_is_escaped(self):
        _, html = build_daily_email(
            "S", self.STATS, [], [_visitor(full_name=None, email="<b>x</b>@e.com")]
        )
        assert "<strong><b>x</b></strong>" not in html
        assert "&lt;b&gt;x&lt;/b&gt;" in html

    def test_missing_fields_degrade_gracefully(self):
        sparse = _visitor(
            full_name=None,
            email=None,
            phone=None,
            location=None,
            job_title=None,
            company_name=None,
            industry=None,
            seniority=None,
            linkedin_url=None,
            twitter_handle=None,
        )
        _, html = build_daily_email("S", self.STATS, [], [sparse])
        assert "Unnamed visitor" in html
        assert "—" in html  # empty contact cell

    def test_see_all_link_when_truncated(self):
        _, html = build_daily_email(
            "S", self.STATS, [], [_visitor()], total_visitor_rows=40
        )
        assert "See all 40" in html

    def test_no_see_all_link_when_complete(self):
        _, html = build_daily_email(
            "S", self.STATS, [], [_visitor()], total_visitor_rows=1
        )
        assert "See all" not in html
        assert "Open in Beam" in html

    @pytest.mark.parametrize(
        "field,payload",
        [
            ("full_name", '<img src=x onerror="alert(1)">'),
            ("company_name", "<script>bad()</script>"),
            ("email", "<b>a@b.com</b>"),
        ],
    )
    def test_visitor_fields_are_escaped(self, field, payload):
        _, html = build_daily_email(
            "S", self.STATS, [], [_visitor(**{field: payload})]
        )
        assert payload not in html
