"""PLUS tests — TwitterAPI.io fallback in Enricher._enrich_twitter.

Official X API v2 stays PRIMARY. TwitterAPI.io is the FALLBACK when the official
call errors / returns a non-200 (other than a definitive 404) / no bearer token.

Covers:
- official 200 → used, no fallback call
- official 404 → definitive miss, no fallback call
- official 401/5xx → falls back to TwitterAPI.io
- no bearer token + fallback key → fallback used directly
- fallback maps data.description / data.followers via _apply_twitter shape
- fallback gated: no fallback key → {}
- mock mode
"""
from unittest.mock import AsyncMock

import httpx
import pytest

from apps.api.services.enricher import Enricher

pytestmark = pytest.mark.unit


def _resp(status, payload=None):
    return httpx.Response(status, json=(payload or {}), request=httpx.Request("GET", "http://x"))


class _SeqClient:
    """AsyncClient whose successive .get() calls return a queued sequence of
    responses (or raise if the queued item is an Exception)."""
    _queue: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, *a, **k):
        item = _SeqClient._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def enricher():
    e = Enricher(db=AsyncMock())
    # Cache + ledger are best-effort; stub them so no Redis/DB is needed.
    e._cache_get = AsyncMock(return_value=(False, None))
    e._cache_set = AsyncMock()
    e._log_enrich = AsyncMock()
    return e


@pytest.fixture
def seq(monkeypatch):
    _SeqClient._queue = []
    monkeypatch.setattr(httpx, "AsyncClient", _SeqClient)
    return _SeqClient


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setattr("apps.api.services.enricher.settings.mock_external_apis", False)
    monkeypatch.setattr("apps.api.services.enricher.settings.twitterapi_io_api_key", "twapi-key")


OFFICIAL_OK = {"data": {"description": "official bio", "public_metrics": {"followers_count": 500}}}
FALLBACK_OK = {"status": "success", "data": {"description": "fallback bio", "followers": 999}}


class TestPrimaryOfficial:
    async def test_official_200_used_no_fallback(self, enricher, seq, cfg):
        _SeqClient._queue = [_resp(200, OFFICIAL_OK)]  # only ONE response queued
        out = await enricher._enrich_twitter("jack", api_key="bearer")
        assert out["twitter_bio"] == "official bio"
        assert out["twitter_follower_count"] == 500
        assert _SeqClient._queue == []  # fallback NOT called

    async def test_official_404_definitive_no_fallback(self, enricher, seq, cfg):
        _SeqClient._queue = [_resp(404)]
        out = await enricher._enrich_twitter("ghost", api_key="bearer")
        assert out == {}
        assert _SeqClient._queue == []  # no fallback for a real 404
        enricher._cache_set.assert_awaited()  # negative-cached


class TestFallbackTriggers:
    async def test_official_401_falls_back(self, enricher, seq, cfg):
        # Official returns 401 (bad token) → fallback used.
        _SeqClient._queue = [_resp(401), _resp(200, FALLBACK_OK)]
        out = await enricher._enrich_twitter("jack", api_key="bad-bearer")
        assert out["twitter_bio"] == "fallback bio"
        assert out["twitter_follower_count"] == 999
        assert _SeqClient._queue == []

    async def test_official_5xx_falls_back(self, enricher, seq, cfg):
        _SeqClient._queue = [_resp(503), _resp(200, FALLBACK_OK)]
        out = await enricher._enrich_twitter("jack", api_key="bearer")
        assert out["twitter_bio"] == "fallback bio"

    async def test_official_exception_falls_back(self, enricher, seq, cfg):
        _SeqClient._queue = [httpx.ConnectError("boom"), _resp(200, FALLBACK_OK)]
        out = await enricher._enrich_twitter("jack", api_key="bearer")
        assert out["twitter_follower_count"] == 999

    async def test_no_bearer_uses_fallback_directly(self, enricher, seq, cfg):
        # No official call at all; fallback is the only request.
        _SeqClient._queue = [_resp(200, FALLBACK_OK)]
        out = await enricher._enrich_twitter("jack", api_key=None)
        assert out["twitter_bio"] == "fallback bio"
        assert _SeqClient._queue == []


class TestFallbackGating:
    async def test_no_fallback_key_returns_empty(self, enricher, seq, monkeypatch):
        monkeypatch.setattr("apps.api.services.enricher.settings.mock_external_apis", False)
        monkeypatch.setattr("apps.api.services.enricher.settings.twitterapi_io_api_key", "")
        _SeqClient._queue = [_resp(401)]  # official fails, no fallback key
        out = await enricher._enrich_twitter("jack", api_key="bearer")
        assert out == {}

    async def test_fallback_user_not_found_status_error(self, enricher, seq, cfg):
        _SeqClient._queue = [_resp(200, {"status": "error", "msg": "not found", "data": None})]
        out = await enricher._enrich_twitter("ghost", api_key=None)
        assert out == {}


class TestMockMode:
    async def test_mock_returns_fake(self, enricher, monkeypatch):
        monkeypatch.setattr("apps.api.services.enricher.settings.mock_external_apis", True)
        out = await enricher._enrich_twitter("@someone", api_key="bearer")
        assert out["twitter_bio"]
        assert out["twitter_follower_count"] == 1234
