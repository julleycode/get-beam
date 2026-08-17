"""F6/F9 — bootstrap stamps after a full run; the repair sweep never stamps."""

from datetime import datetime

import pytest

from apps.api.jobs import scheduler

pytestmark = pytest.mark.unit

STAMP = datetime(2026, 8, 18, 12, 0, 0)


class _NowResult:
    def scalar(self):
        return STAMP


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, *_a, **_k):
        return _NowResult()


@pytest.fixture
def lock_ok(monkeypatch):
    async def _acquire(key, ttl, token="1"):
        return True

    async def _release(key, token=None, **kwargs):
        return None

    async def _extend(key, token, ttl):
        return True

    monkeypatch.setattr(
        "apps.api.services.aggregation_debounce.try_acquire", _acquire
    )
    monkeypatch.setattr("apps.api.services.aggregation_debounce.release", _release)
    monkeypatch.setattr("apps.api.services.aggregation_debounce.extend", _extend)


@pytest.fixture
def stamped(monkeypatch, lock_ok):
    stamps: list = []
    aggregates: list = []

    async def _fake_aggregate(db, site_id, since=None):
        aggregates.append((site_id, since))
        return 2

    async def _fake_advance(db, site_id, stamp):
        stamps.append((site_id, stamp))

    async def _fake_wm(db, site_id):
        return None

    monkeypatch.setattr(
        "apps.api.services.visitor_aggregator.aggregate_visitors_for_site",
        _fake_aggregate,
    )
    monkeypatch.setattr(
        "apps.api.services.visitor_aggregator.advance_watermark",
        _fake_advance,
    )
    monkeypatch.setattr(
        "apps.api.services.visitor_aggregator.get_aggregation_watermark",
        _fake_wm,
    )
    monkeypatch.setattr(scheduler, "async_session", lambda: _FakeSession())
    return stamps, aggregates


@pytest.mark.asyncio
async def test_bootstrap_full_run_stamps(stamped):
    stamps, aggregates = stamped
    outcome, count = await scheduler._bootstrap_one_site("site-a")
    assert outcome == "ran"
    assert count == 2
    assert aggregates == [("site-a", None)]
    assert stamps == [("site-a", STAMP)]


@pytest.mark.asyncio
async def test_sweep_full_run_does_not_stamp(stamped):
    stamps, aggregates = stamped
    outcome, count = await scheduler._sweep_one_site("site-a", allow_defer=True)
    assert outcome == "ran"
    assert count == 2
    assert aggregates == [("site-a", None)]
    assert stamps == []
