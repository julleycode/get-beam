"""DE-6 / DE-7 / DE-16a / DE-16b — pooled, multi-connection topology.

Engine parity with production: ``pool_size=3, max_overflow=2``
(``models/database.py:70-71`` + ``config.py:90-91``), supplied by the lane's
``disposable_engine`` fixture. Single-pool, single-session tests cannot observe
cross-connection lock state at all — that is the blind spot this file closes.

ROOT-CAUSE RULE (do not weaken): **row-count assertions are lock-blind.**
``uq_coop_ledger_expire_per_lot`` + ``ON CONFLICT ... DO NOTHING`` makes every
EXPIRE insert idempotent, so a sweep that RAN WITHOUT THE LOCK reports the same
``rowcount = 0`` as a sweep that was REFUSED because the lock was held. Every
assertion here observes the LOCK or the SKIP BRANCH directly.

Mutation probe for DE-6 (mandatory): stub ``_try_acquire_lock`` to return True
without taking a lock — both legs must go RED.
"""

import datetime as dt

import pytest
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.services.coop_expiry_sweep import _LOCK_KEY, run_coop_expiry_sweep
from tests.e2e_disposable.conftest import expire_row_count, seed_lapsed_lot

pytestmark = pytest.mark.disposable

_TRY_LOCK = text("SELECT pg_try_advisory_lock(hashtext(:k))")
_UNLOCK = text("SELECT pg_advisory_unlock(hashtext(:k))")


async def _probe_lock_is_free(dsn: str) -> bool:
    """Probe the advisory lock from a connection in a SEPARATE POOL.

    LOAD-BEARING (found by mutation probe, 17-08-26): probing via
    ``disposable_engine.connect()`` is VACUOUS. That checks a connection out of
    the SAME pool the sweep used, and Postgres advisory locks are RE-ENTRANT
    within one backend session — so if the probe draws the very connection that
    still holds the lock, ``pg_try_advisory_lock`` returns TRUE and the gate
    reports "free" even when the unlock never ran. Stubbing ``_release_lock`` to
    a no-op left the same-pool version GREEN.

    A separate engine is a separate PG backend, so re-entrancy cannot mask a leak.
    This is the only correct reading of the plan's "from a DIFFERENT connection".
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    probe_engine = create_async_engine(dsn, pool_size=1, max_overflow=0)
    try:
        async with probe_engine.connect() as conn:
            free = bool((await conn.execute(_TRY_LOCK, {"k": _LOCK_KEY})).scalar())
            if free:  # do not leave the probe holding it
                await conn.execute(_UNLOCK, {"k": _LOCK_KEY})
        return free
    finally:
        await probe_engine.dispose()


async def _seed_lapsed(engine, site_id: str, n: int = 3) -> list:
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    lots = []
    async with engine.begin() as conn:
        for _ in range(n):
            lots.append(
                await seed_lapsed_lot(
                    conn,
                    site_id,
                    expires_at=past,
                    spendable_at=past - dt.timedelta(days=1),
                )
            )
    return lots


# ── DE-6 — the lock is genuinely ACQUIRED ────────────────────────────────────


async def test_de6_lock_acquisition_observed_from_a_third_connection(
    disposable_engine, clean_coop, monkeypatch
):
    """Deterministic by construction (C-13) — no race, no timing dependency.

    conn1 holds the lock directly; the sweep runs on conn2 and must take the
    ``got is False`` branch; conn3 independently confirms the key is genuinely
    held. ``_LOCK_KEY`` is IMPORTED, never re-spelled — the module docstring
    warns that re-spelling makes the gate pass unconditionally.
    """
    from apps.api.services import identity_coop

    await _seed_lapsed(disposable_engine, "de6")

    calls = {"n": 0}
    real = identity_coop._lot_remaining

    async def _counting(db, lot_id):
        calls["n"] += 1
        return await real(db, lot_id)

    monkeypatch.setattr(identity_coop, "_lot_remaining", _counting)

    factory = async_sessionmaker(disposable_engine, class_=AsyncSession)
    async with disposable_engine.connect() as conn1:
        held = bool((await conn1.execute(_TRY_LOCK, {"k": _LOCK_KEY})).scalar())
        assert held, "conn1 must win the lock before the sweep is even started"
        try:
            with structlog.testing.capture_logs() as logs:
                async with factory() as sweep_session:
                    await run_coop_expiry_sweep(sweep_session)

            # (a) a THIRD connection independently observes the key as held
            async with disposable_engine.connect() as conn3:
                probe = bool(
                    (await conn3.execute(_TRY_LOCK, {"k": _LOCK_KEY})).scalar()
                )
                if probe:  # released it accidentally — put it back immediately
                    await conn3.execute(_UNLOCK, {"k": _LOCK_KEY})
            assert probe is False, (
                "pg_try_advisory_lock from a third connection returned TRUE while "
                "the lock was supposedly held — acquisition is not real"
            )

            # (b) the loser took the `got is False` branch
            events = [entry.get("event") for entry in logs]
            assert "coop_expiry_sweep_skipped_locked" in events
            assert calls["n"] == 0, (
                "the refused sweep must never reach the per-lot loop "
                "(there ARE lapsed lots seeded, so a non-refused sweep would)"
            )
        finally:
            await conn1.execute(_UNLOCK, {"k": _LOCK_KEY})


# ── DE-7 — release observed from a DIFFERENT connection ──────────────────────


async def test_de7_lock_is_free_after_a_real_sweep(
    disposable_engine, disposable_dsn, clean_coop
):
    """PRE-DECLARED AS LIKELY TO FIRE. `coop_expiry_sweep.py`'s own docstring
    records the accepted residual: the per-lot commit can return the session's
    connection to the pool, so the unlock may execute on a DIFFERENT connection
    and silently no-op. A prod-parity pool (3+2) is exactly the condition that
    surfaces it. A RED here is a confirmed residual to REPORT, not to fix.

    MEASURED 17-08-26: GREEN — the unlock DID land on the lock-holding connection
    at n=5 on a 3+2 pool. That does NOT disprove the residual: this lane runs ONE
    sweep with no competing pool consumer, so the session reliably re-draws its
    own connection after each per-lot commit. Under real contention another
    consumer can take that connection in between, and the unlock would then run
    elsewhere and no-op. Residual stays OPEN, now with a bound: not reproducible
    without concurrent pool pressure."""
    lots = await _seed_lapsed(disposable_engine, "de7", n=5)
    factory = async_sessionmaker(disposable_engine, class_=AsyncSession)
    async with factory() as session:
        written = await run_coop_expiry_sweep(session)
    assert written == len(lots)

    free = await _probe_lock_is_free(disposable_dsn)
    assert free, (
        "advisory lock still held after the sweep returned — the unlock ran on a "
        "recycled connection and no-opped (accepted residual, see docstring)"
    )


# ── DE-16a — the WHERE EXISTS orphan guard ───────────────────────────────────


async def test_de16a_orphan_guard_blocks_expire_when_exists_is_false(
    disposable_engine, disposable_db, monkeypatch
):
    """MID-FLIGHT `site_id` rewrite (E-1) — the only mutation that can flip this.

    Deleting the ACCRUE lot row does NOT work: an ACCRUE row is its own lot
    (`ledger.lot_id = ledger.id`), so `_lot_remaining` returns 0, the
    `continue` at identity_coop.py:589-590 fires, and `_EXPIRE_INSERT_SQL` never
    executes at all — no orphan row appears WITH OR WITHOUT the guard.
    Pre-mutation does not work either: the lapsed SELECT has no site filter, so a
    pre-changed `site_id` is simply carried in the snapshot.

    This rewrite keeps `SUM(amount) > 0` (lot_id untouched) while making the
    EXISTS predicate FALSE against the snapshot's `:site_id`.
    """
    from apps.api.services import identity_coop

    (lot,) = await _seed_lapsed(disposable_engine, "de16a", n=1)

    real = identity_coop._lot_remaining
    fired = {"n": 0, "remaining": None}

    async def _rewriting(db, lot_id):
        if fired["n"] == 0:
            fired["n"] = 1
            # Separate connection + commit, so the sweep's own snapshot is stale.
            async with disposable_engine.begin() as other:
                await other.execute(
                    text(
                        "UPDATE identity_credit_ledger SET site_id = 'e2e-moved' "
                        "WHERE id = :l"
                    ),
                    {"l": lot_id},
                )
        fired["remaining"] = await real(db, lot_id)
        return fired["remaining"]

    monkeypatch.setattr(identity_coop, "_lot_remaining", _rewriting)

    written = await identity_coop.expire_lapsed_lots(disposable_db)

    assert fired["n"] == 1, "the mid-flight rewrite must actually have run"
    # Anti-vacuity, measured AT THE CALL (not after the sweep, which the EXPIRE
    # row itself would zero): the `continue` at identity_coop.py:589-590 did NOT
    # fire, so the WHERE EXISTS guard is the only thing that can block the insert.
    assert fired["remaining"] and fired["remaining"] > 0, (
        "remaining must be > 0 at call time or the `continue` short-circuit, not "
        "the WHERE EXISTS guard, is what blocked the insert (vacuous)"
    )
    async with disposable_engine.connect() as conn:
        assert await expire_row_count(conn, lot) == 0, (
            "WHERE EXISTS is FALSE — no orphan EXPIRE row may be minted"
        )
    assert written == 0


async def test_de16b_site_row_deleted_mid_sweep_does_not_raise(
    disposable_engine, disposable_db
):
    """ROBUSTNESS ONLY — explicitly NOT an orphan-guard proof. There is no
    ForeignKey on identity_credit_ledger.site_id (models/identity_coop.py is a
    bare String(50)), so deleting a Site row leaves the ledger intact and the
    EXISTS clause stays TRUE either way: the guard's presence is invisible here."""
    lots = await _seed_lapsed(disposable_engine, "de16b", n=2)
    async with disposable_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM sites WHERE site_id = :s"), {"s": "de16b"}
        )

    from apps.api.services import identity_coop

    written = await identity_coop.expire_lapsed_lots(disposable_db)
    assert written == len(lots)
