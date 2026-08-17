"""AC-V10 / E19 — the repair sweep must NEVER take the incremental branch.

The sweep is the sole writer of ``avg_time_on_page`` and ``intent_score`` once
``aggregation_incremental_enabled`` is ON (D7). If it ever inherited the
watermark branch — for example by being written as a copy of the now
watermark-aware ``aggregation_tasks._aggregate_all`` — those two columns would
freeze permanently and the Public Contracts staleness bound would be void.

So: ``since=None``, explicitly and unconditionally, for BOTH values of the flag.
"""

import ast
import inspect

import pytest

from apps.api.jobs import scheduler

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
def captured(monkeypatch):
    """Run the sweep against fake Redis + DB, capturing every `since` passed."""
    calls: list = []

    async def _fake_aggregate(db, site_id, since=None):
        calls.append((site_id, since))
        return 1

    async def _acquire(key, ttl, token="1"):
        return True

    async def _release(key, token=None, **kwargs):
        return None

    async def _extend(key, token, ttl):
        return True

    monkeypatch.setattr(
        "apps.api.services.visitor_aggregator.aggregate_visitors_for_site",
        _fake_aggregate,
    )
    monkeypatch.setattr(
        "apps.api.services.aggregation_debounce.try_acquire", _acquire
    )
    monkeypatch.setattr("apps.api.services.aggregation_debounce.release", _release)
    monkeypatch.setattr("apps.api.services.aggregation_debounce.extend", _extend)
    monkeypatch.setattr(
        scheduler, "async_session", lambda: _FakeSession([("site-a",), ("site-b",)])
    )
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [True, False])
async def test_sweep_always_passes_since_none(captured, monkeypatch, flag):
    monkeypatch.setattr(
        scheduler.settings, "aggregation_incremental_enabled", flag, raising=False
    )

    await scheduler._aggregation_sweep_job()

    assert captured, "sweep did not aggregate any site"
    assert [site for site, _ in captured] == ["site-a", "site-b"]
    assert all(since is None for _, since in captured), captured


class TestSourceLevelGuards:
    """Structural guards — these hold even if the runtime test above is skipped."""

    def _source(self):
        return inspect.getsource(scheduler._aggregation_sweep_job) + inspect.getsource(
            scheduler._sweep_one_site
        )

    def test_since_none_is_passed_explicitly_as_a_keyword(self):
        tree = ast.parse(inspect.getsource(scheduler._sweep_one_site).lstrip())
        found = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "aggregate_visitors_for_site"
            ):
                for kw in node.keywords:
                    if kw.arg == "since":
                        found.append(isinstance(kw.value, ast.Constant) and kw.value.value is None)
        assert found == [True], "expected exactly one explicit since=None call"

    def test_sweep_does_not_read_the_watermark(self):
        assert "get_aggregation_watermark" not in self._source()

    def test_sweep_does_not_stamp_the_watermark(self):
        src = inspect.getsource(scheduler._sweep_one_site)
        assert "advance_watermark" not in src
        assert "_advance_watermark" not in src

    def test_sweep_is_sequential_no_parallel_fanout(self):
        """11d pool-awareness: 5 connections shared with request traffic."""
        src = self._source()
        assert "asyncio.gather" not in src
        assert "TaskGroup" not in src
