"""AC11 — per-site hourly ad-push cap.

The Nth push inside the window is rejected; the counter is independent of the
CRM limiter; Redis failure fails OPEN. Pure unit test with a fake Redis.
"""

import pytest

from apps.api.config import settings
from apps.api.services import ads_rate_limiter

pytestmark = pytest.mark.unit


class _FakeRedis:
    def __init__(self, exploding: bool = False):
        self.counts: dict[str, int] = {}
        self.expires: dict[str, int] = {}
        self.exploding = exploding

    async def incr(self, key: str) -> int:
        if self.exploding:
            raise ConnectionError("redis down")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def decr(self, key: str) -> int:
        self.counts[key] -= 1
        return self.counts[key]

    async def expire(self, key: str, ttl: int) -> None:
        self.expires[key] = ttl


@pytest.fixture
def fake_redis(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(ads_rate_limiter, "get_redis", lambda: redis)
    return redis


async def test_ads_rate_limit_rejects_nth_push_in_window(monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "max_ads_pushes_per_hour_per_site", 3)

    assert await ads_rate_limiter.check_and_reserve_push("site_a") is True
    assert await ads_rate_limiter.check_and_reserve_push("site_a") is True
    assert await ads_rate_limiter.check_and_reserve_push("site_a") is True
    # 4th push in the same clock hour is over the cap.
    assert await ads_rate_limiter.check_and_reserve_push("site_a") is False
    # And the rejected attempt did not inflate the counter.
    (key,) = list(fake_redis.counts)
    assert fake_redis.counts[key] == 3
    assert fake_redis.expires[key] == 3600


async def test_ads_rate_limit_counter_is_per_site(monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "max_ads_pushes_per_hour_per_site", 1)
    assert await ads_rate_limiter.check_and_reserve_push("site_a") is True
    assert await ads_rate_limiter.check_and_reserve_push("site_a") is False
    # A different site has its own budget.
    assert await ads_rate_limiter.check_and_reserve_push("site_b") is True


async def test_ads_rate_limit_key_is_independent_of_the_crm_limiter(monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "max_ads_pushes_per_hour_per_site", 5)
    await ads_rate_limiter.check_and_reserve_push("site_a")
    (key,) = list(fake_redis.counts)
    assert key.startswith("ads_push_rate:site_a:")
    assert "crm_push_rate" not in key


async def test_ads_rate_limit_fails_open_when_redis_is_down(monkeypatch):
    monkeypatch.setattr(ads_rate_limiter, "get_redis", lambda: _FakeRedis(exploding=True))
    assert await ads_rate_limiter.check_and_reserve_push("site_a") is True
