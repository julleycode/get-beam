"""P2 tests — wire content_reader into enrichment.

Covers:
- extract_content_handles: PDL fields + OSINT accounts, never guesses
- fetch_content_for_handles: fetches only known handles, non-fatal
- Enricher._fetch_and_store_content gating: flag off / low intent / no handle
  → skip; flag on + high intent + handle → writes social_context (merged,
  preserving existing sub-keys) and sets social_context_updated_at
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.services import content_reader as cr
from apps.api.services.enricher import Enricher

pytestmark = pytest.mark.unit


# ──────────────────────── handle extraction ────────────────────────────────


class TestExtractHandles:
    def test_from_pdl_urls(self):
        pdl = {
            "youtube_url": "https://www.youtube.com/@mkbhd",
            "reddit_url": "https://www.reddit.com/user/spez",
        }
        h = cr.extract_content_handles(pdl, None)
        assert h["youtube"] == "@mkbhd"
        assert h["reddit"] == "spez"

    def test_from_pdl_bare_handles(self):
        pdl = {"youtube_handle": "@cool", "reddit_handle": "someone"}
        h = cr.extract_content_handles(pdl, None)
        assert h["youtube"] == "@cool"
        assert h["reddit"] == "someone"

    def test_from_osint_accounts(self):
        ctx = {
            "osint_scan": {
                "accounts": [
                    {"site_name": "YouTube", "url": "https://youtube.com/@ytuser",
                     "extra": {"username": "ytuser"}},
                    {"site_name": "Reddit", "url": "https://reddit.com/user/rdguy",
                     "extra": {"username": "rdguy"}},
                    {"site_name": "GitHub", "url": "https://github.com/gh"},
                ]
            }
        }
        h = cr.extract_content_handles(None, ctx)
        assert h["youtube"] == "ytuser"
        assert h["reddit"] == "rdguy"

    def test_reddit_subreddit_url_prefix(self):
        h = cr._handle_from_url("https://www.reddit.com/r/python", cr._RD_SITE_TOKENS)
        assert h == "r/python"

    def test_no_handles_returns_empty(self):
        assert cr.extract_content_handles({"job_title": "eng"}, {"deep_research": "x"}) == {}

    def test_pdl_wins_over_osint_no_double(self):
        pdl = {"youtube_url": "https://youtube.com/@primary"}
        ctx = {"osint_scan": {"accounts": [
            {"site_name": "YouTube", "extra": {"username": "secondary"}}]}}
        h = cr.extract_content_handles(pdl, ctx)
        assert h["youtube"] == "@primary"  # PDL first, not overwritten


# ──────────────────────── fetch_content_for_handles ─────────────────────────


class TestFetchForHandles:
    async def test_fetches_both(self, monkeypatch):
        monkeypatch.setattr(cr, "fetch_youtube", AsyncMock(return_value={"source": "youtube", "recent_videos": [1]}))
        monkeypatch.setattr(cr, "fetch_reddit", AsyncMock(return_value={"source": "reddit", "recent_posts": [1]}))
        out = await cr.fetch_content_for_handles({"youtube": "@x", "reddit": "y"})
        assert out["youtube"]["source"] == "youtube"
        assert out["reddit"]["source"] == "reddit"

    async def test_partial_when_one_empty(self, monkeypatch):
        monkeypatch.setattr(cr, "fetch_youtube", AsyncMock(return_value={}))
        monkeypatch.setattr(cr, "fetch_reddit", AsyncMock(return_value={"source": "reddit"}))
        out = await cr.fetch_content_for_handles({"youtube": "@x", "reddit": "y"})
        assert "youtube" not in out
        assert out["reddit"]["source"] == "reddit"

    async def test_no_handles_empty(self):
        assert await cr.fetch_content_for_handles({}) == {}


# ──────────────────────── Enricher gating ───────────────────────────────────


def _profile(social_context=None):
    return SimpleNamespace(
        visitor_id="visitor-abcdef123",
        social_context=social_context,
        social_context_updated_at=None,
    )


def _visitor(intent=80):
    return SimpleNamespace(visitor_id="visitor-abcdef123", intent_score=intent)


def _enricher():
    return Enricher(db=AsyncMock())


class TestEnricherContentGate:
    async def test_flag_off_skips(self, monkeypatch):
        monkeypatch.setattr("apps.api.services.enricher.settings.enable_content_reader", False)
        prof = _profile()
        called = AsyncMock()
        monkeypatch.setattr(cr, "fetch_content_for_handles", called)
        await _enricher()._fetch_and_store_content(_visitor(), prof, {"youtube_handle": "@x"})
        called.assert_not_called()
        assert prof.social_context is None

    async def test_low_intent_skips(self, monkeypatch):
        monkeypatch.setattr("apps.api.services.enricher.settings.enable_content_reader", True)
        called = AsyncMock()
        monkeypatch.setattr(cr, "fetch_content_for_handles", called)
        await _enricher()._fetch_and_store_content(_visitor(intent=30), _profile(), {"youtube_handle": "@x"})
        called.assert_not_called()

    async def test_no_handle_skips(self, monkeypatch):
        monkeypatch.setattr("apps.api.services.enricher.settings.enable_content_reader", True)
        fetch = AsyncMock()
        monkeypatch.setattr(cr, "fetch_content_for_handles", fetch)
        prof = _profile()
        await _enricher()._fetch_and_store_content(_visitor(), prof, {"job_title": "eng"})
        fetch.assert_not_called()
        assert prof.social_context is None

    async def test_writes_and_merges(self, monkeypatch):
        monkeypatch.setattr("apps.api.services.enricher.settings.enable_content_reader", True)
        monkeypatch.setattr(
            cr, "fetch_content_for_handles",
            AsyncMock(return_value={"reddit": {"source": "reddit", "recent_posts": [{"title": "hi"}]}}),
        )
        # Existing sub-key must be preserved (read-modify-write).
        prof = _profile(social_context={"osint_scan": {"accounts": []}, "deep_research": "keep"})
        await _enricher()._fetch_and_store_content(
            _visitor(), prof, {"reddit_handle": "someuser"}
        )
        assert prof.social_context["reddit"]["source"] == "reddit"
        assert prof.social_context["deep_research"] == "keep"  # preserved
        assert prof.social_context_updated_at is not None

    async def test_fetch_error_is_nonfatal(self, monkeypatch):
        monkeypatch.setattr("apps.api.services.enricher.settings.enable_content_reader", True)
        monkeypatch.setattr(cr, "fetch_content_for_handles", AsyncMock(side_effect=RuntimeError("boom")))
        prof = _profile()
        # Must not raise.
        await _enricher()._fetch_and_store_content(_visitor(), prof, {"reddit_handle": "u"})
        assert prof.social_context is None  # nothing written, no crash
