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
    """
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
