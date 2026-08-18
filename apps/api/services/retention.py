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
from apps.api.models.database import apply_long_job_statement_timeout, async_session

logger = structlog.get_logger()

# Advisory-lock key keeping the purge single-flight across replicas.
_PURGE_LOCK_KEY = "beam_retention_purge"

# Separate advisory-lock key for the agent_fetch_events purge (Handoff H1) so it
# is single-flight independently of the raw-events purge.
_AGENT_FETCH_PURGE_LOCK_KEY = "beam_agent_fetch_retention_purge"

# Third independent lock: the admin request-log purge runs on a much tighter
# window (7 days vs 90) and must not be blocked by, or block, the two above.
_REQUEST_LOG_PURGE_LOCK_KEY = "beam_request_log_retention_purge"

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


async def _try_acquire_lock(db: AsyncSession, key: str = _PURGE_LOCK_KEY) -> bool | None:
    """True = acquired, False = held elsewhere, None = unsupported (SQLite)."""
    try:
        result = await db.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"),
            {"key": key},
        )
        return bool(result.scalar())
    except Exception as exc:
        logger.warning("retention_lock_unavailable", error=str(exc))
        return None


async def _release_lock(db: AsyncSession, key: str = _PURGE_LOCK_KEY) -> None:
    try:
        await db.execute(
            text("SELECT pg_advisory_unlock(hashtext(:key))"),
            {"key": key},
        )
    except Exception:
        pass


async def _agent_fetch_events_table_exists(db: AsyncSession) -> bool:
    result = await db.execute(
        text(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_name = 'agent_fetch_events')"
        )
    )
    return bool(result.scalar())


async def _count_old_agent_fetch_events(db: AsyncSession, days: int) -> int:
    result = await db.execute(
        text(f"SELECT count(*) FROM agent_fetch_events WHERE created_at < {_CUTOFF_SQL}"),
        {"days": days},
    )
    return result.scalar() or 0


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
        await apply_long_job_statement_timeout(lock_db)
        acquired = await _try_acquire_lock(lock_db)
        if acquired is False:
            logger.info("retention_purge_lock_busy")
            return {"status": "locked", "deleted": 0}
        try:
            async with async_session() as db:
                await apply_long_job_statement_timeout(db)
                if not await _events_table_exists(db):
                    return {"status": "no_table", "deleted": 0}

                if dry_run:
                    n = await _count_old_events(db, days)
                    logger.info("retention_purge_dry_run", days=days, would_delete=n)
                    return {"status": "dry_run", "would_delete": n}

                total = 0
                while True:
                    await apply_long_job_statement_timeout(db)
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


# agent_fetch_events.created_at is tz-aware (Base server_default now()), unlike
# the naive events.created_at, so the cutoff is computed in tz-aware wall time.
_AGENT_FETCH_CUTOFF_SQL = "now() - make_interval(days => :days)"


async def purge_agent_fetch_events_older_than(
    days: int | None = None,
    dry_run: bool = False,
    batch_size: int = _PURGE_BATCH_SIZE,
) -> dict:
    """Delete agent_fetch_events older than `days`.

    Default `days` = settings.agent_fetch_event_retention_days. Mirrors
    purge_events_older_than exactly (own advisory lock, table-exists guard,
    dry-run counting path, batched delete). Returns the same status-dict shape.
    """
    days = settings.agent_fetch_event_retention_days if days is None else days

    async with async_session() as lock_db:
        await apply_long_job_statement_timeout(lock_db)
        acquired = await _try_acquire_lock(lock_db, _AGENT_FETCH_PURGE_LOCK_KEY)
        if acquired is False:
            logger.info("agent_fetch_retention_purge_lock_busy")
            return {"status": "locked", "deleted": 0}
        try:
            async with async_session() as db:
                await apply_long_job_statement_timeout(db)
                if not await _agent_fetch_events_table_exists(db):
                    return {"status": "no_table", "deleted": 0}

                if dry_run:
                    n = await _count_old_agent_fetch_events(db, days)
                    logger.info(
                        "agent_fetch_retention_purge_dry_run", days=days, would_delete=n
                    )
                    return {"status": "dry_run", "would_delete": n}

                total = 0
                while True:
                    await apply_long_job_statement_timeout(db)
                    result = await db.execute(
                        text(
                            f"""
                            DELETE FROM agent_fetch_events
                            WHERE id IN (
                                SELECT id FROM agent_fetch_events
                                WHERE created_at < {_AGENT_FETCH_CUTOFF_SQL}
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

                logger.info(
                    "agent_fetch_retention_purge_complete", days=days, deleted=total
                )
                return {"status": "ok", "deleted": total}
        finally:
            if acquired:
                await _release_lock(lock_db, _AGENT_FETCH_PURGE_LOCK_KEY)


async def _request_logs_table_exists(db: AsyncSession) -> bool:
    result = await db.execute(
        text(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_name = 'request_logs')"
        )
    )
    return bool(result.scalar())


async def _count_old_request_logs(db: AsyncSession, days: int) -> int:
    result = await db.execute(
        text(f"SELECT count(*) FROM request_logs WHERE created_at < {_AGENT_FETCH_CUTOFF_SQL}"),
        {"days": days},
    )
    return result.scalar() or 0


async def purge_request_logs_older_than(
    days: int | None = None,
    dry_run: bool = False,
    batch_size: int = _PURGE_BATCH_SIZE,
) -> dict:
    """Delete admin request_logs older than `days` (default 7).

    Mirrors purge_agent_fetch_events_older_than exactly (own advisory lock,
    table-exists guard, dry-run counting path, batched delete) and returns the
    same status-dict shape.

    This purge is the compensating control that makes capturing request bodies
    acceptable at all: the window is short by design, so a debug capture never
    becomes a long-lived data store. Do not widen it without revisiting the
    redaction posture in services/log_redaction.py.

    request_logs.created_at is tz-aware (Base server_default now()), so it uses
    the tz-aware cutoff, not the naive events one.
    """
    days = settings.request_log_retention_days if days is None else days

    async with async_session() as lock_db:
        await apply_long_job_statement_timeout(lock_db)
        acquired = await _try_acquire_lock(lock_db, _REQUEST_LOG_PURGE_LOCK_KEY)
        if acquired is False:
            logger.info("request_log_retention_purge_lock_busy")
            return {"status": "locked", "deleted": 0}
        try:
            async with async_session() as db:
                await apply_long_job_statement_timeout(db)
                if not await _request_logs_table_exists(db):
                    return {"status": "no_table", "deleted": 0}

                if dry_run:
                    n = await _count_old_request_logs(db, days)
                    logger.info(
                        "request_log_retention_purge_dry_run", days=days, would_delete=n
                    )
                    return {"status": "dry_run", "would_delete": n}

                total = 0
                while True:
                    await apply_long_job_statement_timeout(db)
                    result = await db.execute(
                        text(
                            f"""
                            DELETE FROM request_logs
                            WHERE id IN (
                                SELECT id FROM request_logs
                                WHERE created_at < {_AGENT_FETCH_CUTOFF_SQL}
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

                logger.info(
                    "request_log_retention_purge_complete", days=days, deleted=total
                )
                return {"status": "ok", "deleted": total}
        finally:
            if acquired:
                await _release_lock(lock_db, _REQUEST_LOG_PURGE_LOCK_KEY)
