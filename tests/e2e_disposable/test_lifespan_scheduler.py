"""DE-3 / DE-4 / DE-5 / DE-5b / DE-13 / DE-14 / DE-15 — real ASGI lifespan.

``httpx.ASGITransport`` does NOT run the ASGI lifespan, so ``start_scheduler()``
and ``_coop_expiry_sweep_job`` are executed by NO test at any tier in this repo.
``LifespanManager`` runs it for real, which is the only way the boot gate at
``scheduler.py:743``, the ``add_job`` registration, and the wrapper's global
``async_session`` path are proven at all.

The flag is monkeypatched on the SETTINGS OBJECT, never via env before import:
``start_scheduler()`` reads ``settings.identity_coop_enabled`` at CALL time and
the wrapper re-reads it at RUN time, so an env var buys nothing and would make
DE-3 (boot-ON) and DE-4 (boot-OFF) mutually exclusive in one process.

Mutation probe for DE-3/DE-5 (mandatory): comment out the ``add_job(...)`` call
at ``scheduler.py:744-752`` — both must go RED.
"""

import asyncio
import datetime as dt
import uuid

import pytest
from asgi_lifespan import LifespanManager
from sqlalchemy import text

from tests.e2e_disposable.conftest import expire_row_count, seed_lapsed_lot

pytestmark = pytest.mark.disposable

_JOB_ID = "coop_expiry_sweep"


async def _boot(flag: bool, monkeypatch):
    """Boot the real app through its ASGI lifespan with the coop flag set."""
    from apps.api.config import settings
    from apps.api.main import app

    monkeypatch.setattr(settings, "identity_coop_enabled", flag)
    return LifespanManager(app, startup_timeout=120, shutdown_timeout=60)


def _coop_jobs():
    from apps.api.jobs.scheduler import scheduler

    return [j for j in scheduler.get_jobs() if j.id == _JOB_ID]


# ── DE-3 / DE-4 — boot gate ───────────────────────────────────────────────────


async def test_de3_coop_job_registered_with_correct_trigger(
    disposable_schema, monkeypatch
):
    from apps.api.config import settings

    async with await _boot(True, monkeypatch):
        jobs = _coop_jobs()
        assert len(jobs) == 1, "coop expiry job must register when the flag is ON"
        job = jobs[0]
        assert job.trigger.interval == dt.timedelta(
            minutes=settings.coop_expiry_sweep_interval_minutes
        )
        assert job.trigger.jitter == 90
        assert job.misfire_grace_time == 300


async def test_de4_boot_off_registers_no_coop_job(disposable_schema, monkeypatch):
    """Proves the `if settings.identity_coop_enabled:` gate at scheduler.py:743."""
    async with await _boot(False, monkeypatch):
        assert _coop_jobs() == [], "a flag-OFF process must register NO coop job"


# ── DE-5 / DE-5b — the scheduler itself writes through the GLOBAL session ─────


async def _seed_one_lapsed(engine, site_id: str):
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    async with engine.begin() as conn:
        return await seed_lapsed_lot(
            conn, site_id, expires_at=past, spendable_at=past - dt.timedelta(days=1)
        )


async def _run_job_now(timeout: float = 30.0) -> None:
    """Force the REGISTERED job to fire now and wait for it to COMPLETE.

    Deliberately goes through `job.modify(next_run_time=...)` rather than calling
    the service directly: the point of DE-5 is that the SCHEDULER's own path —
    including `scheduler.py`'s module-level `async_session`, which
    `tests/conftest.py:199-212` never patches — actually writes.

    Completion is observed via `EVENT_JOB_EXECUTED`, NOT by watching
    `next_run_time` advance. `BaseScheduler._process_jobs` submits the job
    (`schedulers/base.py:1195`) and only THEN advances `next_run_time`
    (`:1228-1229`), so "next_run_time moved" means SUBMITTED, not FINISHED. The
    coroutine is still in flight when the caller leaves the `LifespanManager`
    block, and `AsyncIOExecutor.shutdown()` — which "has no way to honor
    wait=True" (`executors/asyncio.py`) — then CANCELS it. Measured: the sweep
    takes 58-250 ms against the old 250 ms poll tick, so the write lost that race
    in 6 of 40 full-file runs and DE-5 went red with a bare `assert 0 == 1`.
    `EVENT_JOB_EXECUTED` fires from the future's done-callback, i.e. strictly
    after the per-lot commit, so it cannot be observed early.

    The listener is attached BEFORE `modify()`: the job can fire on the very next
    loop tick, and a listener attached afterwards would miss the event and hang.
    """
    from apscheduler.events import (
        EVENT_JOB_ERROR,
        EVENT_JOB_EXECUTED,
        EVENT_JOB_MISSED,
    )

    from apps.api.jobs.scheduler import scheduler

    job = scheduler.get_job(_JOB_ID)
    assert job is not None

    loop = asyncio.get_running_loop()
    finished = asyncio.Event()

    def _on_job_event(event) -> None:
        if event.job_id == _JOB_ID:
            loop.call_soon_threadsafe(finished.set)

    scheduler.add_listener(
        _on_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED
    )
    try:
        job.modify(next_run_time=dt.datetime.now(job.next_run_time.tzinfo))
        scheduler.wakeup()
        await asyncio.wait_for(finished.wait(), timeout)
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise AssertionError(
            "scheduled coop job did not run within the timeout"
        ) from exc
    finally:
        scheduler.remove_listener(_on_job_event)


async def test_de5_scheduler_writes_expire_row(
    disposable_engine, clean_coop, monkeypatch
):
    lot = await _seed_one_lapsed(disposable_engine, "de5")
    async with await _boot(True, monkeypatch):
        assert _coop_jobs(), "no job registered — DE-5 cannot be proven"
        await _run_job_now()
    async with disposable_engine.connect() as conn:
        assert await expire_row_count(conn, lot) == 1


async def test_de5b_runtime_flip_off_writes_nothing(
    disposable_engine, clean_coop, monkeypatch
):
    """K-5: registered flag-ON, flipped OFF at runtime — the wrapper's re-check
    at scheduler.py:314-317 must short-circuit before any write."""
    from apps.api.config import settings

    lot = await _seed_one_lapsed(disposable_engine, "de5b")
    async with await _boot(True, monkeypatch):
        assert _coop_jobs()
        monkeypatch.setattr(settings, "identity_coop_enabled", False)
        await _run_job_now()
    async with disposable_engine.connect() as conn:
        assert await expire_row_count(conn, lot) == 0


# ── DE-13 — boundary: expires_at == now exactly ──────────────────────────────


async def test_de13_boundary_expires_at_equals_now(
    disposable_engine, disposable_db, monkeypatch
):
    """Both the sweep and `spendable_balance` compute `now` INTERNALLY and take
    no `now` parameter, so the boundary is only constructible by freezing the
    module's `datetime` (one patch covers both call sites — C-6).

    `spendable_at` is seeded in the PAST on purpose (C-14): `spendable_balance`
    also excludes a lot when `spendable_at > now`, so a still-held lot would be
    absent from the balance for the wrong reason and the gate would be green even
    under a broken expiry predicate.
    """
    from apps.api.services import identity_coop

    T = dt.datetime(2026, 8, 17, 12, 0, 0, tzinfo=dt.timezone.utc)

    class _Frozen(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return T

    async with disposable_engine.begin() as conn:
        lot = await seed_lapsed_lot(
            conn, "de13", expires_at=T, spendable_at=T - dt.timedelta(days=10)
        )

    monkeypatch.setattr(identity_coop, "datetime", _Frozen)

    written = await identity_coop.expire_lapsed_lots(disposable_db)
    balance = await identity_coop.spendable_balance(disposable_db, "de13")

    async with disposable_engine.connect() as conn:
        expires = await expire_row_count(conn, lot)

    assert written == 1, "expires_at == now must be SWEPT (`expires_at <= now`)"
    assert expires == 1
    assert balance == 0, (
        "expires_at == now must be EXCLUDED from spendable (`expires_at > now` false)"
    )


# ── DE-14 — mid-run crash ─────────────────────────────────────────────────────


async def test_de14_mid_run_crash_is_durable_and_resumes(
    disposable_engine, disposable_db, monkeypatch
):
    """Per-lot commit means an aborted sweep leaves processed lots durable and
    unprocessed lots untouched; the next tick finishes the rest with no dupes."""
    from apps.api.services import identity_coop

    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    lots = []
    async with disposable_engine.begin() as conn:
        for _ in range(5):
            lots.append(
                await seed_lapsed_lot(
                    conn, "de14", expires_at=past, spendable_at=past - dt.timedelta(1)
                )
            )

    real = identity_coop._lot_remaining
    calls = {"n": 0}

    async def _crashing(db, lot_id):
        calls["n"] += 1
        if calls["n"] > 2:
            # BaseException — escapes the loop's `except Exception` on purpose.
            raise KeyboardInterrupt("simulated mid-sweep kill")
        return await real(db, lot_id)

    monkeypatch.setattr(identity_coop, "_lot_remaining", _crashing)
    with pytest.raises(KeyboardInterrupt):
        await identity_coop.expire_lapsed_lots(disposable_db)

    async with disposable_engine.connect() as conn:
        durable = sum([await expire_row_count(conn, lot) for lot in lots])
    assert durable == 2, "already-committed lots must survive the crash"

    monkeypatch.setattr(identity_coop, "_lot_remaining", real)
    await identity_coop.expire_lapsed_lots(disposable_db)

    async with disposable_engine.connect() as conn:
        per_lot = [await expire_row_count(conn, lot) for lot in lots]
    assert per_lot == [1] * 5, "resume must finish the rest and reprocess nothing"


# ── DE-15 — aborted transaction still releases the advisory lock ─────────────


async def test_de15_aborted_transaction_still_releases_lock(
    disposable_engine, disposable_dsn, disposable_db, monkeypatch
):
    """An exception path that defeats the unlock leaves the lock held FOREVER.
    Observed from a DIFFERENT connection, never by row count (locks are
    invisible to row counts — see the plan's lock-blind root-cause note)."""
    from apps.api.services import coop_expiry_sweep
    from apps.api.services.coop_expiry_sweep import run_coop_expiry_sweep
    from tests.e2e_disposable.test_pool_topology import _probe_lock_is_free

    async def _abort_then_raise(db):
        try:
            await db.execute(text("SELECT 1/0"))
        except Exception:
            pass
        raise RuntimeError("simulated lot failure leaving an aborted session")

    monkeypatch.setattr(coop_expiry_sweep, "expire_lapsed_lots", _abort_then_raise)

    with pytest.raises(RuntimeError):
        await run_coop_expiry_sweep(disposable_db)

    # SEPARATE POOL — a same-pool probe is vacuous (advisory locks are re-entrant
    # within one backend session). See _probe_lock_is_free's docstring.
    free = await _probe_lock_is_free(disposable_dsn)
    assert free, "the finally-unlock must survive an aborted transaction"
