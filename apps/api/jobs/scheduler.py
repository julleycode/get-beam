"""Background scheduler for periodic jobs (feed sync, identity resolution).

Jobs run inside the FastAPI process via APScheduler. Heavy logic lives in
trigger-agnostic services (e.g. resolution_runner) so jobs stay thin and
can move to a Railway cron service or Celery worker without rewrites.
"""

from datetime import datetime, timedelta, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from apps.api.config import settings
from apps.api.models.database import async_session
from apps.api.services.resolution_runner import run_resolution_sweep
from apps.api.services.retention import purge_events_older_than
from apps.api.services.sync import sync_all_accounts
from apps.api.services import blog_service
from apps.api.services import changelog_generator

logger = structlog.get_logger()

scheduler = AsyncIOScheduler()


async def _sync_job() -> None:
    """Periodic job: sync all connected social accounts.

    Each account's sync is wrapped in try/except by sync_all_accounts,
    so one failure won't crash the entire job.
    """
    logger.info("sync_job_started")
    try:
        async with async_session() as db:
            counts = await sync_all_accounts(db)
            total = sum(counts.values())
            logger.info("sync_job_complete", new_posts=total, breakdown=counts)
    except Exception:
        logger.exception("sync_job_crashed")


async def _resolution_sweep_job() -> None:
    """Periodic job: resolve + enrich eligible visitors across all sites.

    run_resolution_sweep handles its own sessions, per-site error isolation,
    and a Postgres advisory lock (single-flight across replicas).
    """
    logger.info("resolution_sweep_started")
    try:
        await run_resolution_sweep()
    except Exception:
        logger.exception("resolution_sweep_crashed")


async def _retention_purge_job() -> None:
    """Periodic job: delete raw events past the retention window.

    purge_events_older_than handles its own sessions and a Postgres advisory
    lock (single-flight across replicas). Only raw events are removed.
    """
    try:
        result = await purge_events_older_than()
        if result.get("deleted"):
            logger.info("retention_purge_job_complete", **result)
    except Exception:
        logger.exception("retention_purge_crashed")


async def _publish_scheduled_blog_job() -> None:
    """Periodic job: publish blog posts whose scheduled time has passed."""
    try:
        async with async_session() as db:
            count = await blog_service.publish_due_posts(db)
            if count:
                logger.info("scheduled_blog_published", count=count)
    except Exception:
        logger.exception("scheduled_blog_publish_crashed")


async def _changelog_sync_job() -> None:
    """Periodic job: turn newly merged PRs into published changelog entries."""
    try:
        async with async_session() as db:
            result = await changelog_generator.sync_from_github(db)
            if result.imported:
                logger.info("changelog_auto_synced", imported=result.imported)
    except changelog_generator.ChangelogSyncError as exc:
        logger.warning("changelog_sync_unavailable", error=str(exc))
    except Exception:
        logger.exception("changelog_sync_crashed")


def start_scheduler() -> None:
    """Start the background scheduler. Call once at app startup."""
    scheduler.add_job(
        _sync_job,
        "interval",
        minutes=settings.sync_interval_minutes,
        id="sync_all_feeds",
        replace_existing=True,
    )
    scheduler.add_job(
        _resolution_sweep_job,
        "interval",
        minutes=settings.resolution_sweep_interval_minutes,
        id="resolution_sweep",
        replace_existing=True,
        # APScheduler's first interval fire is at +interval. The API process
        # restarts on every deploy, resetting that 30-min timer before it ever
        # elapses — so the sweep effectively never ran and backlogs piled up.
        # Fire ~shortly after boot so each deploy drains the backlog, then keep
        # the interval. The sweep is advisory-locked + budget-gated, so running
        # on every boot is safe. (Railway cron is the durable fix — see
        # apps/api/jobs/run_sweep_once.py.)
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=20),
    )
    scheduler.add_job(
        _publish_scheduled_blog_job,
        "interval",
        minutes=1,
        id="publish_scheduled_blog",
        replace_existing=True,
    )
    scheduler.add_job(
        _retention_purge_job,
        "interval",
        hours=settings.retention_purge_interval_hours,
        id="retention_purge",
        replace_existing=True,
    )
    if settings.changelog_sync_enabled:
        scheduler.add_job(
            _changelog_sync_job,
            "interval",
            hours=settings.changelog_sync_interval_hours,
            id="changelog_sync",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
        )
    scheduler.start()
    logger.info(
        "scheduler_started",
        sync_interval_minutes=settings.sync_interval_minutes,
        resolution_sweep_interval_minutes=settings.resolution_sweep_interval_minutes,
    )


def stop_scheduler() -> None:
    """Shut down the scheduler gracefully."""
    scheduler.shutdown(wait=False)
    logger.info("scheduler_stopped")
