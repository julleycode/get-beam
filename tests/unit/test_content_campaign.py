"""P3 tests — feed social_context into campaign personalization.

Covers:
- build_recent_content: youtube / reddit / tweets / deep_research → short string
- empty / None social_context → "" (prompt unchanged)
- length cap
- segmenter.build_visitor_profiles adds recent_content only when present
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.services import content_reader as cr

pytestmark = pytest.mark.unit


class TestBuildRecentContent:
    def test_empty_inputs(self):
        assert cr.build_recent_content(None) == ""
        assert cr.build_recent_content({}) == ""
        assert cr.build_recent_content("not a dict") == ""

    def test_youtube(self):
        ctx = {"youtube": {"recent_videos": [
            {"title": "How I built X"}, {"title": "My setup tour"}, {"title": "Q&A"}, {"title": "extra"}]}}
        out = cr.build_recent_content(ctx)
        assert "Recent YouTube videos" in out
        assert "How I built X" in out
        assert "extra" not in out  # capped at 3

    def test_reddit(self):
        ctx = {"reddit": {"recent_posts": [
            {"title": "Ask me anything"}, {"snippet": "just a body no title here"}]}}
        out = cr.build_recent_content(ctx)
        assert "Recent Reddit posts" in out
        assert "Ask me anything" in out

    def test_tweets(self):
        ctx = {"recent_posts": [{"content": "shipping a new feature today"}]}
        out = cr.build_recent_content(ctx)
        assert "Recent posts" in out
        assert "shipping a new feature" in out

    def test_deep_research(self):
        ctx = {"deep_research": "This person is a devtools founder active on X."}
        out = cr.build_recent_content(ctx)
        assert "Research summary" in out
        assert "devtools founder" in out

    def test_combined_and_capped(self):
        ctx = {
            "youtube": {"recent_videos": [{"title": "vid " + "x" * 400}]},
            "deep_research": "y" * 400,
        }
        out = cr.build_recent_content(ctx)
        assert len(out) <= cr.RECENT_CONTENT_MAX_CHARS

    def test_only_noise_returns_empty(self):
        # Sub-keys present but no usable content → "".
        ctx = {"youtube": {"recent_videos": []}, "reddit": {"recent_posts": []}}
        assert cr.build_recent_content(ctx) == ""


class TestSegmenterWiring:
    async def test_adds_recent_content_when_present(self, monkeypatch):
        from apps.api.agents import segmenter

        visitor = MagicMock()
        visitor.visitor_id = "v1"
        visitor.intent_score = 70
        visitor.total_pageviews = 3
        visitor.total_sessions = 1
        visitor.pages_visited = ["/"]
        visitor.device_type = "desktop"
        visitor.country_code = "US"

        enriched = MagicMock()
        enriched.visitor_id = "v1"
        enriched.job_title = "Founder"
        enriched.company_name = "Acme"
        enriched.industry = "SaaS"
        enriched.seniority_level = "C-level"
        enriched.linkedin_url = None
        enriched.twitter_handle = None
        enriched.linkedin_headline = None
        enriched.twitter_bio = None
        enriched.social_context = {"reddit": {"recent_posts": [{"title": "cool post"}]}}

        # Mock the two DB queries build_visitor_profiles issues.
        id_result = MagicMock()
        id_result.scalars.return_value.all.return_value = []
        enrich_result = MagicMock()
        enrich_result.scalars.return_value.all.return_value = [enriched]

        # Third query: the additive job-change signal batch fetch. Returns no
        # rows here — this suite is about recent_content, and job_changed_at is
        # None for a visitor with no confirmed job change.
        job_change_result = MagicMock()
        job_change_result.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[id_result, enrich_result, job_change_result])

        profiles = await segmenter.build_visitor_profiles(db, "site1", [visitor])
        assert profiles[0]["recent_content"]
        assert "cool post" in profiles[0]["recent_content"]

    async def test_no_recent_content_key_when_empty(self, monkeypatch):
        from apps.api.agents import segmenter

        visitor = MagicMock()
        visitor.visitor_id = "v1"
        visitor.intent_score = 70
        visitor.total_pageviews = 3
        visitor.total_sessions = 1
        visitor.pages_visited = ["/"]
        visitor.device_type = "desktop"
        visitor.country_code = "US"

        enriched = MagicMock()
        enriched.visitor_id = "v1"
        enriched.job_title = "Founder"
        enriched.company_name = "Acme"
        enriched.industry = "SaaS"
        enriched.seniority_level = "C-level"
        enriched.linkedin_url = None
        enriched.twitter_handle = None
        enriched.linkedin_headline = None
        enriched.twitter_bio = None
        enriched.social_context = None  # no context

        id_result = MagicMock()
        id_result.scalars.return_value.all.return_value = []
        enrich_result = MagicMock()
        enrich_result.scalars.return_value.all.return_value = [enriched]

        # Third query: the additive job-change signal batch fetch. Returns no
        # rows here — this suite is about recent_content, and job_changed_at is
        # None for a visitor with no confirmed job change.
        job_change_result = MagicMock()
        job_change_result.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[id_result, enrich_result, job_change_result])

        profiles = await segmenter.build_visitor_profiles(db, "site1", [visitor])
        assert "recent_content" not in profiles[0]
