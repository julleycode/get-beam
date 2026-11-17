"""F8 mutex — lock survives a run longer than the cooldown TTL (no real Redis).

In-memory stand-in for SET NX EX / token compare-and-del so this gate can run
in the unit lane when localhost:6379 is down. The integration debounce file
repeats the same scenario against real Redis.
"""

import asyncio
import inspect
import time

import pytest

from apps.api.routers import events as events_router
from apps.api.services import aggregation_debounce as dbnc

pytestmark = pytest.mark.unit

SITE_ID = "test_site_mutex_unit"


class _MemoryRedis:
    """Minimal async Redis: set nx/ex, exists, delete, eval for F8 Lua."""

    def __init__(self):
        self.store: dict[str, tuple[str, float]] = {}

    def _get(self, key: str) -> str | None:
        item = self.store.get(key)
        if item is None:
            return None
        value, expires_at = item
        if expires_at <= time.monotonic():
            self.store.pop(key, None)
            return None
        return value

    async def set(self, key, value, nx=False, ex=1):
        if nx and self._get(key) is not None:
            return False
        self.store[key] = (value, time.monotonic() + max(int(ex), 1))
        return True

    async def exists(self, key):
        return 1 if self._get(key) is not None else 0

    async def delete(self, key):
        existed = key in self.store
        self.store.pop(key, None)
        return int(existed)

    async def eval(self, script, numkeys, *args):
        key = args[0]
        if "expire" in script:
            token, ttl = args[1], int(args[2])
            current = self._get(key)
            if current != token:
                return 0
            self.store[key] = (current, time.monotonic() + max(ttl, 1))
            return 1
        token, cooldown = args[1], int(args[2])
        current = self._get(key)
        if current != token:
            return 0
        if cooldown > 0:
            self.store[key] = ("1", time.monotonic() + cooldown)
            return 1
        self.store.pop(key, None)
        return 1


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
def memory_redis(monkeypatch):
    fake = _MemoryRedis()
    monkeypatch.setattr(
        "apps.api.services.redis_client.get_redis", lambda: fake
    )
    return fake


@pytest.fixture
def slow_runs(monkeypatch):
    calls: list = []

    async def _slow_aggregate(db, site_id, since=None):
        calls.append((site_id, since))
        await asyncio.sleep(2.1)
        return 0

    async def _fake_watermark(db, site_id):
        return None

    monkeypatch.setattr(
        "apps.api.services.visitor_aggregator.aggregate_visitors_for_site",
        _slow_aggregate,
    )
    monkeypatch.setattr(
        "apps.api.services.visitor_aggregator.get_aggregation_watermark",
        _fake_watermark,
    )
    monkeypatch.setattr(events_router, "async_session", lambda: _FakeSession())
    return calls


@pytest.mark.asyncio
async def test_mutex_held_longer_than_ttl_no_double_count(
    memory_redis, slow_runs, monkeypatch
):
    monkeypatch.setattr(
        "apps.api.config.settings.aggregation_min_interval_seconds", 1
    )

    async def _second():
        await asyncio.sleep(1.2)
        await events_router._background_aggregate(SITE_ID)

    await asyncio.gather(
        events_router._background_aggregate(SITE_ID),
        _second(),
    )
    assert len(slow_runs) == 1, slow_runs
    assert not await memory_redis.exists(dbnc.debounce_key(SITE_ID))


@pytest.mark.asyncio
async def test_mutex_release_in_finally_even_on_aggregate_error(
    memory_redis, monkeypatch
):
    monkeypatch.setattr(
        "apps.api.config.settings.aggregation_min_interval_seconds", 60
    )

    async def _boom(db, site_id, since=None):
        raise RuntimeError("agg failed")

    monkeypatch.setattr(
        "apps.api.services.visitor_aggregator.aggregate_visitors_for_site",
        _boom,
    )
    monkeypatch.setattr(events_router, "async_session", lambda: _FakeSession())

    await events_router._background_aggregate(SITE_ID)

    # Refresh stopped; leftover cooldown may remain ("1") but the mutex token
    # must not still own the key.
    val = memory_redis._get(dbnc.debounce_key(SITE_ID))
    assert val in (None, "1")


def test_ingest_created_at_is_server_utcnow():
    """F2 structural guard — event.ts must not write Event.created_at."""
    src = inspect.getsource(events_router)
    assert "created_at=datetime.utcnow()" in src
    assert "created_at=event.ts" not in src
