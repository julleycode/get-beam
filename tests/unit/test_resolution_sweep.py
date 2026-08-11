"""Unit tests for the all-sites resolution sweep (no DB, no network).

Verifies the sweep's orchestration contract:
- per-site error isolation (one failing site doesn't stop the rest)
- advisory-lock single-flight (busy lock short-circuits the run)
- fail-open when the DB doesn't support advisory locks
- lock released only when it was actually acquired
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# Importing resolution_runner registers the User mapper (via billing) without
# its relationship targets (SocialAccount, Draft, ...). Import the app so ALL
# models register — otherwise lazy mapper config blows up in whichever test
# file happens to touch the ORM first (same rationale as conftest.test_engine).
import apps.api.main  # noqa: F401
from apps.api.services import resolution_runner


class _FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items


def _fake_session_factory(sites, captured: list | None = None):
    """async_session stand-in: any execute() returns the site list.

    When ``captured`` is passed, every statement handed to execute() is appended
    to it so a test can assert on the query the sweep actually built.
    """

    @asynccontextmanager
    async def factory():
        db = AsyncMock()

        async def _execute(stmt, *args, **kwargs):
            if captured is not None:
                captured.append(stmt)
            return _FakeResult(sites)

        db.execute = _execute
        yield db

    return factory


def _sites(n: int):
    return [SimpleNamespace(site_id=f"site-{i}", user_id=f"user-{i}") for i in range(n)]


@pytest.mark.asyncio
async def test_sweep_isolates_site_failures(monkeypatch):
    """One site raising must not stop the remaining sites."""
    sites = _sites(3)
    calls: list[str] = []

    async def fake_run(db, site, max_resolve=20):
        calls.append(site.site_id)
        if site.site_id == "site-1":
            raise RuntimeError("provider exploded")
        return {"processed": 1, "resolved": 0, "enriched": 0, "skipped_plan_limit": 0}

    monkeypatch.setattr(resolution_runner, "async_session", _fake_session_factory(sites))
    monkeypatch.setattr(resolution_runner, "run_resolution_for_site", fake_run)
    monkeypatch.setattr(resolution_runner, "_try_acquire_sweep_lock", AsyncMock(return_value=True))
    release = AsyncMock()
    monkeypatch.setattr(resolution_runner, "_release_sweep_lock", release)

    await resolution_runner.run_resolution_sweep()

    assert calls == ["site-0", "site-1", "site-2"]
    release.assert_awaited_once()


@pytest.mark.asyncio
async def test_sweep_skips_when_lock_busy(monkeypatch):
    """Another replica holds the lock: do nothing, release nothing."""
    run = AsyncMock()
    release = AsyncMock()
    monkeypatch.setattr(resolution_runner, "async_session", _fake_session_factory(_sites(2)))
    monkeypatch.setattr(resolution_runner, "run_resolution_for_site", run)
    monkeypatch.setattr(resolution_runner, "_try_acquire_sweep_lock", AsyncMock(return_value=False))
    monkeypatch.setattr(resolution_runner, "_release_sweep_lock", release)

    await resolution_runner.run_resolution_sweep()

    run.assert_not_awaited()
    release.assert_not_awaited()


@pytest.mark.asyncio
async def test_sweep_proceeds_when_lock_unsupported(monkeypatch):
    """Non-Postgres DB (SQLite dev/test): fail open and run unguarded,
    but never call unlock for a lock that was never taken."""
    sites = _sites(2)
    run = AsyncMock(return_value={"processed": 0, "resolved": 0, "enriched": 0, "skipped_plan_limit": 0})
    release = AsyncMock()
    monkeypatch.setattr(resolution_runner, "async_session", _fake_session_factory(sites))
    monkeypatch.setattr(resolution_runner, "run_resolution_for_site", run)
    monkeypatch.setattr(resolution_runner, "_try_acquire_sweep_lock", AsyncMock(return_value=None))
    monkeypatch.setattr(resolution_runner, "_release_sweep_lock", release)

    await resolution_runner.run_resolution_sweep()

    assert run.await_count == 2
    release.assert_not_awaited()


@pytest.mark.asyncio
async def test_sweep_query_excludes_paused_sites(monkeypatch):
    """A paused site (manual toggle OR inactivity auto-pause) must not have its
    backlog drained — that would keep burning resolver/enrichment/Gemini credits
    for a site whose ingest is already 204ing. `tracking_enabled` is therefore a
    second gate alongside `auto_identify_enabled` in the sweep's site query."""
    captured: list = []
    monkeypatch.setattr(
        resolution_runner, "async_session", _fake_session_factory(_sites(1), captured)
    )
    monkeypatch.setattr(
        resolution_runner,
        "run_resolution_for_site",
        AsyncMock(
            return_value={
                "processed": 0,
                "resolved": 0,
                "enriched": 0,
                "skipped_plan_limit": 0,
            }
        ),
    )
    monkeypatch.setattr(
        resolution_runner, "_try_acquire_sweep_lock", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(resolution_runner, "_release_sweep_lock", AsyncMock())

    await resolution_runner.run_resolution_sweep()

    assert captured, "expected the sweep to issue a site query"
    sql = str(captured[0]).lower()
    assert "auto_identify_enabled" in sql
    assert "tracking_enabled" in sql, (
        "the sweep must filter on tracking_enabled; without it a paused site "
        "keeps burning provider credits draining its existing backlog"
    )
