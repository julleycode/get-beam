"""AC-V7 / E17 — the sweep's Redis-degraded fail direction is FLAG-CONDITIONAL.

Item 11f originally said "when Redis is degraded, let the sweep run — a duplicate
full recompute is idempotent by construction". That is true of full-vs-full and
FALSE of full-vs-incremental: a ``since=None`` SET racing an additive incremental
merge can inflate ``total_pageviews`` / ``total_sessions``, which is the exact
G1 failure the whole phase exists to prevent.

So the direction flips on the flag:

* ``aggregation_incremental_enabled=True``  -> SKIP the site (stale beats wrong).
* ``aggregation_incremental_enabled=False`` -> proceed (genuinely idempotent).

Per C7/E10 this test never touches a real Redis — the degradation is injected by
monkeypatching the sweep's Redis call to raise, so a stray local container on
6379 cannot poison it.
"""

import pytest

from apps.api.jobs import scheduler
from apps.api.services import aggregation_debounce

pytestmark = pytest.mark.unit


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, *_a, **_k):
        return _FakeResult(self._rows)


@pytest.fixture
def degraded_redis(monkeypatch):
    """Make every Redis call raise, exactly as a dead Redis would."""

    def _boom(*_a, **_k):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(
        "apps.api.services.redis_client.get_redis", _boom
    )
    return _boom


@pytest.fixture
def aggregate_calls(monkeypatch):
    calls: list = []

    async def _fake_aggregate(db, site_id, since=None):
        calls.append((site_id, since))
        return 3

    monkeypatch.setattr(
        "apps.api.services.visitor_aggregator.aggregate_visitors_for_site",
        _fake_aggregate,
    )
    monkeypatch.setattr(
        scheduler, "async_session", lambda: _FakeSession([("site-a",)])
    )
    return calls


@pytest.mark.asyncio
async def test_degraded_helpers_return_none_not_raise(degraded_redis):
    """The helper degrades explicitly so each caller can pick its own direction."""
    assert await aggregation_debounce.try_acquire("agg:debounce:x", 60) is None
    assert await aggregation_debounce.exists("agg:sweep_pending:x") is None


@pytest.mark.asyncio
async def test_flag_on_skips_the_site(
    degraded_redis, aggregate_calls, monkeypatch, caplog
):
    monkeypatch.setattr(
        scheduler.settings, "aggregation_incremental_enabled", True, raising=False
    )

    outcome, count = await scheduler._sweep_one_site("site-a", allow_defer=True)

    assert outcome == "skipped"
    assert count == 0
    assert aggregate_calls == [], "a full recompute raced a possible incremental run"


@pytest.mark.asyncio
async def test_flag_on_logs_the_documented_event(
    degraded_redis, aggregate_calls, monkeypatch
):
    logged: list = []
    monkeypatch.setattr(
        scheduler.logger, "warning", lambda evt, **kw: logged.append((evt, kw))
    )
    monkeypatch.setattr(
        scheduler.settings, "aggregation_incremental_enabled", True, raising=False
    )

    await scheduler._sweep_one_site("site-a", allow_defer=True)

    assert ("aggregation_sweep_skipped_redis_degraded", {"site_id": "site-a"}) in logged


@pytest.mark.asyncio
async def test_flag_off_proceeds_because_full_vs_full_is_idempotent(
    degraded_redis, aggregate_calls, monkeypatch
):
    monkeypatch.setattr(
        scheduler.settings, "aggregation_incremental_enabled", False, raising=False
    )

    outcome, count = await scheduler._sweep_one_site("site-a", allow_defer=True)

    assert outcome == "ran"
    assert count == 3
    assert aggregate_calls == [("site-a", None)]


@pytest.mark.asyncio
async def test_whole_pass_survives_a_degraded_redis(
    degraded_redis, aggregate_calls, monkeypatch
):
    """A skip must never abort the pass — the next site still gets its turn."""
    monkeypatch.setattr(
        scheduler.settings, "aggregation_incremental_enabled", True, raising=False
    )
    monkeypatch.setattr(
        scheduler, "async_session", lambda: _FakeSession([("a",), ("b",), ("c",)])
    )

    await scheduler._aggregation_sweep_job()  # must not raise

    assert aggregate_calls == []
