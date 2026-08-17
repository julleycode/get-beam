"""F7 — ingest Redis-degraded fail direction is FLAG-CONDITIONAL.

Sweep already skips when Redis is down and ``aggregation_incremental_enabled``
is on. Ingest used to fail OPEN (``acquired is None`` fell through), which
races a full SET against an incremental merge. Flag ON → skip agg (log).
Flag OFF → still fail open so the 204 contract is unchanged.
"""

import pytest

from apps.api.routers import events as events_router

pytestmark = pytest.mark.unit


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


@pytest.fixture
def degraded_redis(monkeypatch):
    def _boom(*_a, **_k):
        raise ConnectionError("redis is down")

    monkeypatch.setattr("apps.api.services.redis_client.get_redis", _boom)
    return _boom


@pytest.fixture
def aggregate_calls(monkeypatch):
    calls: list = []

    async def _fake_aggregate(db, site_id, since=None):
        calls.append((site_id, since))
        return 3

    async def _fake_watermark(db, site_id):
        return None

    async def _fake_advance(db, site_id, stamp):
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
        "apps.api.services.visitor_aggregator.advance_watermark",
        _fake_advance,
    )
    monkeypatch.setattr(events_router, "async_session", lambda: _FakeSession())
    return calls


@pytest.mark.asyncio
async def test_flag_on_skips_ingest_agg(
    degraded_redis, aggregate_calls, monkeypatch
):
    monkeypatch.setattr(
        "apps.api.config.settings.aggregation_incremental_enabled",
        True,
        raising=False,
    )

    await events_router._background_aggregate("site-a")

    assert aggregate_calls == [], "ingest must not agg when Redis is down and flag is ON"


@pytest.mark.asyncio
async def test_flag_on_logs_the_documented_event(
    degraded_redis, aggregate_calls, monkeypatch
):
    logged: list = []
    monkeypatch.setattr(
        events_router.logger, "warning", lambda evt, **kw: logged.append((evt, kw))
    )
    monkeypatch.setattr(
        "apps.api.config.settings.aggregation_incremental_enabled",
        True,
        raising=False,
    )

    await events_router._background_aggregate("site-a")

    assert (
        "aggregation_ingest_skipped_redis_degraded",
        {"site_id": "site-a"},
    ) in logged


@pytest.mark.asyncio
async def test_flag_off_proceeds_because_full_vs_full_is_idempotent(
    degraded_redis, aggregate_calls, monkeypatch
):
    monkeypatch.setattr(
        "apps.api.config.settings.aggregation_incremental_enabled",
        False,
        raising=False,
    )

    await events_router._background_aggregate("site-a")

    assert aggregate_calls == [("site-a", None)]
