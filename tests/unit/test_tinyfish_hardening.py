"""TinyFish reader hardening: URL safety, search/site caps, negative cache."""
import pytest

from apps.api.services import tinyfish_reader as tr
from tests.unit.test_tinyfish_reader import _FakeRedis

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "data:text/html,x",
        "https://user:pw@linkedin.com/in/x",
        "https://linkedin.com.evil.io/in/x",
        "https://evil.io/linkedin.com",
        "https:// linkedin.com/in/x",
        "https://localhost/in/x",
        None,
        123,
    ],
)
def test_safe_url_rejects_unsafe_linkedin(value):
    assert tr.safe_url(value, linkedin=True) is None


def test_safe_url_accepts_linkedin_and_plain_https():
    assert tr.safe_url("https://www.linkedin.com/in/x", linkedin=True)
    assert tr.safe_url("https://linkedin.com/in/x", linkedin=True)
    assert tr.safe_url("https://example.com/me") == "https://example.com/me"
    assert tr.safe_url("ftp://example.com/me") is None


async def test_claim_cap_site_cap_blocks_before_global(monkeypatch):
    r = _FakeRedis()
    monkeypatch.setattr(tr, "get_redis", lambda: r)
    monkeypatch.setattr(tr.settings, "tinyfish_site_daily_cap", 1)
    monkeypatch.setattr(tr.settings, "tinyfish_daily_search_cap", 100)
    assert await tr._claim_cap("search", site_id="s1") is True
    assert await tr._claim_cap("search", site_id="s1") is False
    # the rejected call did not consume global quota
    assert r.store[tr.cap_key(kind="search")] == "1"
    assert await tr._claim_cap("search", site_id="s2") is True


async def test_claim_cap_search_global_cap(monkeypatch):
    r = _FakeRedis()
    monkeypatch.setattr(tr, "get_redis", lambda: r)
    monkeypatch.setattr(tr.settings, "tinyfish_daily_search_cap", 1)
    assert await tr._claim_cap("search") is True
    assert await tr._claim_cap("search") is False


async def test_claim_cap_fails_closed_when_redis_down(monkeypatch):
    def boom():
        raise ConnectionError("down")

    monkeypatch.setattr(tr, "get_redis", boom)
    assert await tr._claim_cap("fetch", site_id="s1") is False


async def test_negative_result_cached_for_a_day(monkeypatch):
    seen = {}

    async def fake_set(key, data, ttl=tr.CACHE_TTL_SECONDS):
        seen.update(key=key, data=data, ttl=ttl)

    monkeypatch.setattr(tr, "_cache_set", fake_set)
    assert await tr._negative("k", "v1", "no_results") is False
    assert seen == {"key": "k", "data": {"negative": True}, "ttl": tr.NEGATIVE_CACHE_TTL_SECONDS}
