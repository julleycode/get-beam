"""Orphan-ingest counter tests (AC3).

Unit lane: Redis is monkeypatched with an in-memory fake, so no server is
needed. Covers the hourly key shape + TTL, the summary window/bucketing, and the
hard fail-open rule (a raising Redis must never propagate out of either helper).
"""

from datetime import datetime, timezone

import pytest

from apps.api.services import orphan_ingest_metrics as oim

pytestmark = pytest.mark.unit


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.ttls[key] = seconds
        return True

    async def get(self, key: str):
        v = self.store.get(key)
        return None if v is None else str(v)

    async def scan_iter(self, match: str):
        prefix = match.rstrip("*")
        for k in list(self.store):
            if k.startswith(prefix):
                yield k


class BoomRedis:
    async def incr(self, key):
        raise RuntimeError("redis down")

    async def expire(self, key, seconds):
        raise RuntimeError("redis down")

    async def get(self, key):
        raise RuntimeError("redis down")

    def scan_iter(self, match):
        raise RuntimeError("redis down")


@pytest.fixture
def fake_redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(oim, "get_redis", lambda: r)
    return r


def _bucket() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H")


async def test_record_increments_global_and_per_site_keys_with_ttl(fake_redis):
    await oim.record_orphan_ingest("site_deadbeef1234")

    b = _bucket()
    assert fake_redis.store[f"beam:orphan_ingest:{b}"] == 1
    assert fake_redis.store[f"beam:orphan_ingest:{b}:site_deadbeef1234"] == 1
    # 7-day TTL on both keys — the keyspace self-prunes, no cron.
    assert fake_redis.ttls[f"beam:orphan_ingest:{b}"] == 7 * 24 * 3600
    assert fake_redis.ttls[f"beam:orphan_ingest:{b}:site_deadbeef1234"] == 7 * 24 * 3600


async def test_repeated_records_accumulate(fake_redis):
    for _ in range(3):
        await oim.record_orphan_ingest("site_aaaaaaaaaaaa")
    b = _bucket()
    assert fake_redis.store[f"beam:orphan_ingest:{b}"] == 3
    assert fake_redis.store[f"beam:orphan_ingest:{b}:site_aaaaaaaaaaaa"] == 3


async def test_summary_sums_window_and_buckets_by_site_id(fake_redis):
    await oim.record_orphan_ingest("site_aaaaaaaaaaaa")
    await oim.record_orphan_ingest("site_aaaaaaaaaaaa")
    await oim.record_orphan_ingest("site_bbbbbbbbbbbb")

    summary = await oim.orphan_ingest_summary(window_hours=24)

    assert summary["window_hours"] == 24
    assert summary["total"] == 3
    assert summary["by_site_id"] == {
        "site_aaaaaaaaaaaa": 2,
        "site_bbbbbbbbbbbb": 1,
    }


async def test_summary_empty_when_nothing_recorded(fake_redis):
    summary = await oim.orphan_ingest_summary(window_hours=1)
    assert summary == {"window_hours": 1, "total": 0, "by_site_id": {}}


async def test_record_is_fail_open_when_redis_raises(monkeypatch):
    monkeypatch.setattr(oim, "get_redis", lambda: BoomRedis())
    # Must NOT raise — a counter can never turn an ingest 403 into a 500.
    assert await oim.record_orphan_ingest("site_cccccccccccc") is None


async def test_record_is_fail_open_when_client_construction_raises(monkeypatch):
    def _boom():
        raise RuntimeError("no redis url")

    monkeypatch.setattr(oim, "get_redis", _boom)
    assert await oim.record_orphan_ingest("site_cccccccccccc") is None


async def test_summary_returns_zeros_when_redis_raises(monkeypatch):
    monkeypatch.setattr(oim, "get_redis", lambda: BoomRedis())
    summary = await oim.orphan_ingest_summary(window_hours=6)
    assert summary == {"window_hours": 6, "total": 0, "by_site_id": {}}
