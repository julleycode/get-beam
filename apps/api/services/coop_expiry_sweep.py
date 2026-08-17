"""Identity co-op FIFO lot-expiry sweep entrypoint.

identity-coop Phase 2a (visitors-identity). Repo convention: the sweep BODY lives
here in ``services/``; the ``_coop_expiry_sweep_job()`` wrapper and its
``scheduler.add_job(...)`` registration live in ``apps/api/jobs/scheduler.py``.
The Celery ``apps/api/tasks/`` package is deliberately out of scope.

This module owns exactly three things: acquiring the instance-dedup advisory
lock, releasing it, and calling ``expire_lapsed_lots`` once. The per-lot loop and
the per-lot commit belong to ``expire_lapsed_lots`` — see its docstring.

The lock is EFFICIENCY-ONLY. The correctness boundary for duplicate EXPIRE rows
is the ``uq_coop_ledger_expire_per_lot`` partial unique index, which rejects a
losing racer at the DB tier. A missed acquire therefore costs a redundant
concurrent sweep, never audit corruption.
"""

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.identity_coop import expire_lapsed_lots

logger = structlog.get_logger()

# Probed directly by the G-20 lock-release gate. Renaming this without updating
# that test makes the gate pass unconditionally (pg_advisory_unlock on a key
# nobody holds returns the PASSING value), so the test asserts on it explicitly.
_LOCK_KEY = "coop_expiry_sweep"

# F-B guard. ``_EXPIRE_INSERT_SQL``'s ``ON CONFLICT (lot_id) WHERE entry_type =
# 'EXPIRE'`` can only infer an arbiter if this PARTIAL UNIQUE INDEX exists
# (migration b7e4d21a9c58). Absent it EVERY insert raises, the per-lot
# ``except Exception`` (C-1) swallows it, and the sweep reports success having
# expired nothing — a silent failure on a billing surface.
_EXPIRE_INDEX_NAME = "uq_coop_ledger_expire_per_lot"
_EXPIRE_INDEX_TABLE = "identity_credit_ledger"

# POSITIVE-only cache. A miss is NEVER cached — that is what makes the guard
# self-healing when an operator applies b7e4d21a9c58 to a running fleet.
# TEST HYGIENE: a hit is cached for the whole PROCESS, so one healthy-path test
# disarms every later negative-path test (and its mutation probe) in the same
# pytest process. Guard-dependent tests MUST reset this via an autouse fixture.
_index_verified: bool = False


class CoopExpiryIndexMissing(RuntimeError):
    """The EXPIRE arbiter index is absent (D2 — fail-closed, deliberately).

    Matches this repo's money/PII precedent (``validate_production`` fails
    startup on missing prod keys; ``refresh_ip_org.py`` refuses a non-local
    DSN). Log-and-continue would produce the SAME observable outcome as the bug
    being fixed. Deliberately NOT fail-open like ``_try_acquire_lock``: a
    duplicate sweep is benign, a missing arbiter index is total failure. Do not
    "harmonise" the two.
    """


async def assert_expire_index(db: AsyncSession) -> None:
    """Raise ``CoopExpiryIndexMissing`` unless the EXPIRE arbiter index exists.

    ``tablename`` is pinned as well as ``indexname`` so a same-named index on
    another table cannot satisfy the guard. Deliberately NOT wrapped in
    try/except: a catalog error (dead connection, permissions) propagates — the
    same fail-closed direction as a miss (D3).
    """
    global _index_verified
    if _index_verified:
        return
    row = await db.execute(
        text(
            "SELECT 1 FROM pg_indexes "
            "WHERE schemaname = current_schema() "
            "AND tablename = :t AND indexname = :n"
        ),
        {"t": _EXPIRE_INDEX_TABLE, "n": _EXPIRE_INDEX_NAME},
    )
    if row.scalar() is not None:
        _index_verified = True
        return
    logger.error(
        "coop_expiry_index_missing",
        index=_EXPIRE_INDEX_NAME,
        table=_EXPIRE_INDEX_TABLE,
        migration="b7e4d21a9c58",
    )
    raise CoopExpiryIndexMissing(
        f"{_EXPIRE_INDEX_NAME} missing from {_EXPIRE_INDEX_TABLE} (migration "
        "b7e4d21a9c58 not applied): ON CONFLICT cannot infer an arbiter, so "
        "every EXPIRE insert would fail silently. Refusing to run."
    )


async def _try_acquire_lock(db: AsyncSession) -> bool | None:
    """True = acquired, False = held elsewhere, None = unsupported/errored."""
    try:
        result = await db.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
        return bool(result.scalar())
    except Exception as exc:  # noqa: BLE001
        logger.warning("coop_expiry_lock_unavailable", error=str(exc))
        return None


async def _release_lock(db: AsyncSession) -> None:
    try:
        await db.execute(
            text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
    except Exception:  # noqa: BLE001
        pass


async def run_coop_expiry_sweep(db: AsyncSession) -> int:
    """Expire every lapsed co-op credit lot. Returns rows written.

    Acquire and release are a non-separable pair: ``pg_try_advisory_lock`` is
    SESSION-scoped, not transaction-scoped, so ``expire_lapsed_lots``'s per-lot
    commit does NOT release it. Without the explicit unlock the connection returns
    to the pool still holding the lock — later ticks drawing that connection
    re-enter a session that already holds it (counter leak) while ticks drawing
    any other connection skip forever. Both failure shapes are silent.

    The not-acquired check is ``is False``, NOT falsy, and that distinction is
    deliberate: ``_try_acquire_lock`` returns ``None`` when the lock query itself
    is unsupported or errored, and every lock precedent in this repo PROCEEDS on
    ``None`` (fail-OPEN). A falsy check would be fail-CLOSED — one ``None`` and
    the sweep silently never expires anything again, observable by no gate. A
    duplicate sweep run is the strictly better failure, and the E2 partial unique
    index rejects its duplicate rows at the DB tier anyway.

    Known residual (accepted, adjacent to K-2): the per-lot commit can return the
    session's connection to the pool, so the unlock may execute on a different
    connection and no-op. Every advisory-lock sweep in this repo shares that shape;
    it is recorded in the capacity-hardening advisory-lock audit note.

    The F-B index guard lives HERE, not at boot (D1): the job is registered only
    when ``identity_coop_enabled`` is ON, and ``start_scheduler()`` is sync so it
    cannot run an async catalog probe. At this entrypoint the check fires exactly
    when someone tries to expire credits, covers every caller, and — being
    strictly BEFORE ``_try_acquire_lock`` — can never leak the advisory lock.
    Do not move it up to ``main.py``.
    """
    await assert_expire_index(db)
    got = await _try_acquire_lock(db)
    if got is False:
        logger.info("coop_expiry_sweep_skipped_locked")
        return 0

    try:
        return await expire_lapsed_lots(db)
    finally:
        # Roll back first so the unlock always runs on a usable transaction: a
        # lot that raised and left the session aborted would make the unlock
        # SELECT fail, and _release_lock's bare except swallows that — the lock
        # would leak silently despite this correct-looking try/finally.
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        if got:
            await _release_lock(db)
