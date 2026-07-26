"""AC-V5 / E16 — the repair sweep cannot be starved by a hot site.

Docker-gated: needs a real Redis.

The starvation this proves absent: the per-ingest path takes
``agg:debounce:{site_id}`` with ``SET NX EX aggregation_min_interval_seconds`` on
EVERY batch, so on a continuously-ingesting site the key is re-acquired the
instant it expires and is held ~100% of the time. A sweep that made a single
``SET NX`` attempt and skipped on failure would therefore never repair exactly
the hottest sites — the ones this whole plan exists for — and
``avg_time_on_page`` / ``intent_score`` (which drives segmentation and outreach)
would stay frozen forever.

The four-part protocol asserted here:

1. the sweep sets ``agg:sweep_pending:{site_id}`` instead of silently skipping;
2. the per-ingest trigger yields while that marker is set, and does NOT re-take
   the debounce key;
3. the sweep's end-of-pass retry then acquires the key and runs a FULL recompute;
4. the marker is deleted afterwards.
"""

import asyncio

import pytest

from apps.api.jobs import scheduler
from apps.api.routers import events as events_router
from apps.api.services import aggregation_debounce as dbnc

pytestmark = pytest.mark.integration

SITE_ID = "test_site_sweep_priority"
TTL = 2  # short debounce so the end-of-pass retry is observable in-test


@pytest.fixture(autouse=True)
async def redis_reset():
    from apps.api.services import redis_client

    redis_client._client = None
    redis = redis_client.get_redis()
    keys = (dbnc.debounce_key(SITE_ID), dbnc.sweep_pending_key(SITE_ID))
    for key in keys:
        await redis.delete(key)
    yield redis
    for key in keys:
        await redis.delete(key)
    await redis.aclose()
    redis_client._client = None


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows=()):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, *_a, **_k):
        return _FakeResult(self._rows)


@pytest.fixture
def sweep_env(monkeypatch):
    """One site, short TTL, aggregation stubbed so no DB is needed."""
    calls: list = []

    async def _fake_aggregate(db, site_id, since=None):
        calls.append((site_id, since))
        return 7

    async def _fake_watermark(db, site_id):
        return None

    monkeypatch.setattr(
        "apps.api.services.visitor_aggregator.aggregate_visitors_for_site",
        _fake_aggregate,
    )
    monkeypatch.setattr(
        "apps.api.services.visitor_aggregator.get_aggregation_watermark",
        _fake_watermark,
    )
    monkeypatch.setattr(
        "apps.api.config.settings.aggregation_min_interval_seconds", TTL
    )
    monkeypatch.setattr(
        "apps.api.config.settings.aggregation_incremental_enabled", True
    )
    monkeypatch.setattr(
        scheduler, "async_session", lambda: _FakeSession([(SITE_ID,)])
    )
    monkeypatch.setattr(events_router, "async_session", lambda: _FakeSession())
    return calls


class TestSweepIsNotStarved:
    @pytest.mark.asyncio
    async def test_full_protocol_end_to_end(self, sweep_env, redis_reset):
        """A hot site holds the key; the sweep still repairs it within one TTL."""
        # A per-ingest run is in flight and holds the debounce key.
        await events_router._background_aggregate(SITE_ID)
        assert sweep_env == [(SITE_ID, None)]
        assert await redis_reset.exists(dbnc.debounce_key(SITE_ID))
        sweep_env.clear()

        # Emulate the hot site: keep re-taking the key the moment it expires,
        # exactly as a continuously-ingesting per-ingest path would — but through
        # the real trigger, so the yield-marker check is exercised.
        stop = asyncio.Event()

        async def _hot_ingest():
            while not stop.is_set():
                await asyncio.sleep(0.2)
                await events_router._background_aggregate(SITE_ID)

        hot = asyncio.create_task(_hot_ingest())
        try:
            await scheduler._aggregation_sweep_job()
        finally:
            stop.set()
            await hot

        # (3) the sweep ran a FULL recompute for the contended site
        assert (SITE_ID, None) in sweep_env, sweep_env
        # (4) the marker is gone
        assert not await redis_reset.exists(dbnc.sweep_pending_key(SITE_ID))

    @pytest.mark.asyncio
    async def test_1_sweep_sets_the_yield_marker_instead_of_skipping(
        self, sweep_env, redis_reset
    ):
        await redis_reset.set(dbnc.debounce_key(SITE_ID), "1", ex=60)

        outcome, _ = await scheduler._sweep_one_site(SITE_ID, allow_defer=True)

        assert outcome == "deferred"
        assert await redis_reset.exists(dbnc.sweep_pending_key(SITE_ID))

    @pytest.mark.asyncio
    async def test_1b_marker_ttl_outlives_one_debounce_interval(
        self, sweep_env, redis_reset
    ):
        await redis_reset.set(dbnc.debounce_key(SITE_ID), "1", ex=60)
        await scheduler._sweep_one_site(SITE_ID, allow_defer=True)

        ttl = await redis_reset.ttl(dbnc.sweep_pending_key(SITE_ID))
        assert ttl > TTL, "a single unlucky expiry race would drop the marker"

    @pytest.mark.asyncio
    async def test_2_per_ingest_yields_and_does_not_retake_the_key(
        self, sweep_env, redis_reset
    ):
        await redis_reset.set(dbnc.sweep_pending_key(SITE_ID), "1", ex=30)

        await events_router._background_aggregate(SITE_ID)

        assert sweep_env == [], "per-ingest run should have stood down"
        assert not await redis_reset.exists(dbnc.debounce_key(SITE_ID))

    @pytest.mark.asyncio
    async def test_3_end_of_pass_retry_waits_for_the_key_and_runs(
        self, sweep_env, redis_reset
    ):
        await redis_reset.set(dbnc.debounce_key(SITE_ID), "1", ex=TTL)

        outcome, count = await scheduler._sweep_one_site(
            SITE_ID, allow_defer=False, wait_seconds=TTL + 5
        )

        assert outcome == "ran"
        assert count == 7
        assert sweep_env == [(SITE_ID, None)], "retry must use the repair path"

    @pytest.mark.asyncio
    async def test_4_marker_is_cleared_even_when_the_site_fails(
        self, sweep_env, redis_reset, monkeypatch
    ):
        """A crash must never wedge every per-ingest trigger for that site."""

        async def _boom(db, site_id, since=None):
            raise RuntimeError("aggregation exploded")

        monkeypatch.setattr(
            "apps.api.services.visitor_aggregator.aggregate_visitors_for_site", _boom
        )
        await redis_reset.set(dbnc.sweep_pending_key(SITE_ID), "1", ex=30)

        outcome, _ = await scheduler._sweep_one_site(SITE_ID, allow_defer=True)

        assert outcome == "skipped"
        assert not await redis_reset.exists(dbnc.sweep_pending_key(SITE_ID))

    @pytest.mark.asyncio
    async def test_a_deferred_site_never_aborts_the_whole_pass(
        self, sweep_env, redis_reset, monkeypatch
    ):
        monkeypatch.setattr(
            scheduler,
            "async_session",
            lambda: _FakeSession([(SITE_ID,), ("other_site",)]),
        )
        await redis_reset.set(dbnc.debounce_key(SITE_ID), "1", ex=60)

        await scheduler._aggregation_sweep_job()

        assert ("other_site", None) in sweep_env
