"""P4 tests — find_company_channels (subreddit + YouTube discovery).

Covers:
- domain-root helpers
- generic/free-mail domain → skip (no confidence)
- mock mode
- Reddit subreddit search: confidence gate (domain root must appear)
- YouTube via Gemini: confidence gate (domain root must appear in URL)
- cache + rate-limit
- build_recent_content includes company_content
"""
from unittest.mock import AsyncMock

import httpx
import pytest

from apps.api.services import content_reader as cr

pytestmark = pytest.mark.unit


@pytest.fixture
def fake_redis(monkeypatch):
    import fakeredis.aioredis
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cr, "get_redis", lambda: client)
    return client


@pytest.fixture
def mock_off(monkeypatch):
    monkeypatch.setattr(cr.settings, "mock_external_apis", False)
    monkeypatch.setattr(cr.settings, "content_reader_max_items", 5)
    monkeypatch.setattr(cr.settings, "gemini_api_key", "test-key")


class TestDomainHelpers:
    def test_domain_root(self):
        assert cr._domain_root("www.acme.com") == "acme"
        assert cr._domain_root("blog.acme.co.uk") == "acme"
        assert cr._domain_root("https://acme.io/path") == "acme"

    def test_domain_matches_url(self):
        assert cr._domain_matches_url("acme.com", "https://youtube.com/@acmehq") is True
        assert cr._domain_matches_url("acme.com", "https://youtube.com/@othercorp") is False


class TestGenericDomainSkip:
    async def test_generic_domain_skipped(self, mock_off, fake_redis):
        assert await cr.find_company_channels("Gmail User", "gmail.com") == {}

    async def test_missing_inputs(self, mock_off, fake_redis):
        assert await cr.find_company_channels("", "acme.com") == {}
        assert await cr.find_company_channels("Acme", "") == {}

    async def test_short_root_skipped(self, mock_off, fake_redis):
        # 2-char root gives too little signal.
        assert await cr.find_company_channels("X", "x.io") == {}


class TestMockMode:
    async def test_mock_returns_root_handles(self, monkeypatch):
        monkeypatch.setattr(cr.settings, "mock_external_apis", True)
        out = await cr.find_company_channels("Acme Corp", "acme.com")
        assert out == {"reddit": "r/acme", "youtube": "@acme"}


def _resp(status, payload=None):
    return httpx.Response(status, json=(payload or {}), request=httpx.Request("GET", "http://x"))


class _FakeClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **k):
        return self._response


class TestSubredditSearch:
    async def test_subreddit_matches_on_domain_root(self, mock_off, fake_redis, monkeypatch):
        payload = {"data": {"children": [
            {"data": {"display_name": "acme", "title": "Acme HQ",
                      "public_description": "official acme community", "url": "/r/acme"}},
        ]}}
        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _FakeClient(_resp(200, payload)))
        # Disable the youtube leg to isolate the reddit result.
        monkeypatch.setattr(cr, "_find_company_youtube", AsyncMock(return_value=None))
        out = await cr.find_company_channels("Acme Corp", "acme.com")
        assert out["reddit"] == "r/acme"

    async def test_subreddit_rejected_without_domain_root(self, mock_off, fake_redis, monkeypatch):
        # A generically-named subreddit that does NOT contain the domain root.
        payload = {"data": {"children": [
            {"data": {"display_name": "cooking", "title": "Cooking",
                      "public_description": "recipes", "url": "/r/cooking"}},
        ]}}
        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _FakeClient(_resp(200, payload)))
        monkeypatch.setattr(cr, "_find_company_youtube", AsyncMock(return_value=None))
        out = await cr.find_company_channels("Acme Corp", "acme.com")
        assert "reddit" not in out


class TestYoutubeConfidence:
    async def test_youtube_accepted_when_domain_in_url(self, mock_off, fake_redis, monkeypatch):
        monkeypatch.setattr(cr, "_find_company_subreddit", AsyncMock(return_value=None))
        monkeypatch.setattr(
            cr, "_find_company_youtube",
            AsyncMock(return_value={"youtube_url": "https://www.youtube.com/@acmehq"}),
        )
        out = await cr.find_company_channels("Acme Corp", "acme.com")
        assert out["youtube"] == "https://www.youtube.com/@acmehq"

    async def test_youtube_rejected_when_domain_absent(self, mock_off, fake_redis, monkeypatch):
        monkeypatch.setattr(cr, "_find_company_subreddit", AsyncMock(return_value=None))
        monkeypatch.setattr(
            cr, "_find_company_youtube",
            AsyncMock(return_value={"youtube_url": "https://www.youtube.com/@randomchannel"}),
        )
        out = await cr.find_company_channels("Acme Corp", "acme.com")
        assert "youtube" not in out


class TestCache:
    async def test_negative_cache(self, mock_off, fake_redis, monkeypatch):
        monkeypatch.setattr(cr, "_find_company_subreddit", AsyncMock(return_value=None))
        monkeypatch.setattr(cr, "_find_company_youtube", AsyncMock(return_value=None))
        out = await cr.find_company_channels("Acme Corp", "acme.com")
        assert out == {}
        key = f"content:company:{cr._hash('acme.com')}"
        assert await fake_redis.get(key) == cr._CACHE_MISS_MARKER

        # Second call must hit cache — the search fns should NOT be called again.
        sub = AsyncMock(return_value=None)
        monkeypatch.setattr(cr, "_find_company_subreddit", sub)
        out2 = await cr.find_company_channels("Acme Corp", "acme.com")
        assert out2 == {}
        sub.assert_not_called()


class TestBuildRecentContentCompany:
    def test_company_content_included(self):
        ctx = {"company_content": {
            "reddit": {"recent_posts": [{"title": "company update"}]},
            "youtube": {"recent_videos": [{"title": "product launch"}]},
        }}
        out = cr.build_recent_content(ctx)
        assert "Company subreddit posts" in out
        assert "company update" in out
        assert "Company recent YouTube videos" in out
        assert "product launch" in out
