"""AC5 — cross-container aggregation debounce (Phase 3 / W1, decision D3).

Docker-gated: needs a real Redis. The point of moving the guard out of the
in-memory ``_aggregating`` set and into ``agg:debounce:{site_id}`` is that the
in-memory set deduplicates only within ONE process, so N containers ran N
concurrent full-history aggregations of the same site.

Two concurrent triggers for one site inside ``aggregation_min_interval_seconds``
must produce exactly ONE aggregation run.
"""

import asyncio

import pytest

from apps.api.routers import events as events_router
from apps.api.services import aggregation_debounce as dbnc

pytestmark = pytest.mark.integration

SITE_ID = "test_site_debounce"


@pytest.fixture(autouse=True)
async def clean_keys():
    """Fresh Redis client per test.

    ``redis_client._client`` is a module-level singleton bound to whichever event
    loop first created it; pytest-asyncio gives each test its own loop, so a
    cached client raises "Event loop is closed" on the second test. Reset the
    singleton around every test and clear this site's keys.
    """
    from apps.api.services import redis_client

    redis_client._client = None
    redis = redis_client.get_redis()
    keys = (dbnc.debounce_key(SITE_ID), dbnc.sweep_pending_key(SITE_ID))
    for key in keys:
        await redis.delete(key)
    yield
    for key in keys:
        await redis.delete(key)
    await redis.aclose()
    redis_client._client = None


@pytest.fixture
def runs(monkeypatch):
    """Count real aggregation runs, without touching the DB."""
    calls: list = []

    async def _fake_aggregate(db, site_id, since=None):
        calls.append((site_id, since))
        await asyncio.sleep(0.05)
        return 0

    async def _fake_watermark(db, site_id):
        return None

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def execute(self, *_a, **_k):
            class _Result:
                def scalar(self):
                    return None

            return _Result()

    monkeypatch.setattr(
        "apps.api.services.visitor_aggregator.aggregate_visitors_for_site",
        _fake_aggregate,
    )
    monkeypatch.setattr(
        "apps.api.services.visitor_aggregator.get_aggregation_watermark",
        _fake_watermark,
    )
    monkeypatch.setattr(events_router, "async_session", lambda: _FakeSession())
    return calls


class TestDebounce:
    @pytest.mark.asyncio
    async def test_two_concurrent_triggers_produce_exactly_one_run(self, runs):
        """The in-memory set is bypassed entirely here — both coroutines call
        _background_aggregate directly, simulating two containers."""
        await asyncio.gather(
            events_router._background_aggregate(SITE_ID),
            events_router._background_aggregate(SITE_ID),
        )
        assert len(runs) == 1, runs

    @pytest.mark.asyncio
    async def test_a_third_trigger_inside_the_interval_is_also_debounced(self, runs):
        await events_router._background_aggregate(SITE_ID)
        await events_router._background_aggregate(SITE_ID)
        await events_router._background_aggregate(SITE_ID)
        assert len(runs) == 1, runs

    @pytest.mark.asyncio
    async def test_a_trigger_runs_again_once_the_key_expires(self, runs, monkeypatch):
        monkeypatch.setattr(
            "apps.api.config.settings.aggregation_min_interval_seconds", 1
        )
        await events_router._background_aggregate(SITE_ID)
        assert len(runs) == 1
        await asyncio.sleep(1.3)
        await events_router._background_aggregate(SITE_ID)
        assert len(runs) == 2

    @pytest.mark.asyncio
    async def test_the_key_is_the_documented_shared_namespace(self, runs):
        from apps.api.services.redis_client import get_redis

        await events_router._background_aggregate(SITE_ID)
        assert await get_redis().exists(f"agg:debounce:{SITE_ID}")


    @pytest.mark.asyncio
    async def test_mutex_held_longer_than_ttl_no_double_count(self, runs, monkeypatch):
        """F8 — lock survives a run longer than the old 60s TTL analog.

        Inject TTL=1s and a 2.1s aggregate; a second trigger after 1.2s must
        not start another run. No real 120s wait.
        """
        monkeypatch.setattr(
            "apps.api.config.settings.aggregation_min_interval_seconds", 1
        )
        slow: list = []

        async def _slow_aggregate(db, site_id, since=None):
            slow.append((site_id, since))
            await asyncio.sleep(2.1)
            return 0

        monkeypatch.setattr(
            "apps.api.services.visitor_aggregator.aggregate_visitors_for_site",
            _slow_aggregate,
        )

        async def _second():
            await asyncio.sleep(1.2)
            await events_router._background_aggregate(SITE_ID)

        await asyncio.gather(
            events_router._background_aggregate(SITE_ID),
            _second(),
        )
        assert len(slow) == 1, slow


class TestSweepYieldMarker:
    """E16(b) — a per-ingest trigger stands down while the sweep is waiting."""

    @pytest.mark.asyncio
    async def test_trigger_yields_and_does_not_take_the_key(self, runs):
        from apps.api.services.redis_client import get_redis

        await get_redis().set(dbnc.sweep_pending_key(SITE_ID), "1", ex=30)

        await events_router._background_aggregate(SITE_ID)

        assert runs == [], "per-ingest run should have yielded to the sweep"
        assert not await get_redis().exists(dbnc.debounce_key(SITE_ID)), (
            "taking the debounce key here is exactly what starves the sweep"
        )
