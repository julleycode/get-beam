"""Data retention purge — delete raw events past the retention window.

Trigger-agnostic core (memory: job-architecture-preferences). APScheduler calls
it daily today; it can move to a Railway cron service or Celery worker without
changes. Single-flight across replicas via a Postgres advisory lock (same
pattern as the resolution sweep).

Scope: ONLY raw events are purged. Aggregated `visitors` and enriched profiles
are kept (the privacy policy retains profiles while the account is active). This
enforces the policy's 90-day event-retention promise and supports GDPR data
minimization.

Events live in PostgreSQL (`events` table) — ClickHouse is dormant at MVP scale
(see models/event.py). When ClickHouse becomes the event store, add a TTL on its
events table instead of deleting here.
"""

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.database import async_session

logger = structlog.get_logger()

# Advisory-lock key keeping the purge single-flight across replicas.
_PURGE_LOCK_KEY = "beam_retention_purge"

# Per-batch delete size — bounds how long any single statement holds row locks.
_PURGE_BATCH_SIZE = 10_000

# created_at is stored as naive UTC (events.py strips tz), so the cutoff is
# computed in UTC wall time to match.
_CUTOFF_SQL = "(now() AT TIME ZONE 'UTC') - make_interval(days => :days)"


async def _events_table_exists(db: AsyncSession) -> bool:
    result = await db.execute(
        text(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_name = 'events')"
        )
    )
    return bool(result.scalar())


async def _count_old_events(db: AsyncSession, days: int) -> int:
    result = await db.execute(
        text(f"SELECT count(*) FROM events WHERE created_at < {_CUTOFF_SQL}"),
        {"days": days},
    )
    return result.scalar() or 0


async def _try_acquire_lock(db: AsyncSession) -> bool | None:
    """True = acquired, False = held elsewhere, None = unsupported (SQLite)."""
    try:
        result = await db.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"),
            {"key": _PURGE_LOCK_KEY},
        )
        return bool(result.scalar())
    except Exception as exc:
        logger.warning("retention_lock_unavailable", error=str(exc))
        return None


async def _release_lock(db: AsyncSession) -> None:
    try:
        await db.execute(
            text("SELECT pg_advisory_unlock(hashtext(:key))"),
            {"key": _PURGE_LOCK_KEY},
        )
    except Exception:
        pass


async def purge_events_older_than(
    days: int | None = None,
    dry_run: bool = False,
    batch_size: int = _PURGE_BATCH_SIZE,
) -> dict:
    """Delete events older than `days` (default: settings.event_retention_days).

    dry_run=True counts but deletes nothing. Returns a status dict:
    - {"status": "ok", "deleted": N}
    - {"status": "dry_run", "would_delete": N}
    - {"status": "locked", "deleted": 0}      (another replica holds the lock)
    - {"status": "no_table", "deleted": 0}    (fresh DB without events)
    """
    days = settings.event_retention_days if days is None else days

    async with async_session() as lock_db:
        acquired = await _try_acquire_lock(lock_db)
        if acquired is False:
            logger.info("retention_purge_lock_busy")
            return {"status": "locked", "deleted": 0}
        try:
            async with async_session() as db:
                if not await _events_table_exists(db):
                    return {"status": "no_table", "deleted": 0}

                if dry_run:
                    n = await _count_old_events(db, days)
                    logger.info("retention_purge_dry_run", days=days, would_delete=n)
                    return {"status": "dry_run", "would_delete": n}

                total = 0
                while True:
                    result = await db.execute(
                        text(
                            f"""
                            DELETE FROM events
                            WHERE id IN (
                                SELECT id FROM events
                                WHERE created_at < {_CUTOFF_SQL}
                                LIMIT :lim
                            )
                            """
                        ),
                        {"days": days, "lim": batch_size},
                    )
                    await db.commit()
                    deleted = result.rowcount or 0
                    total += deleted
                    if deleted < batch_size:
                        break

                logger.info("retention_purge_complete", days=days, deleted=total)
                return {"status": "ok", "deleted": total}
        finally:
            if acquired:
                await _release_lock(lock_db)
