"""Background scheduler for periodic jobs (feed sync, identity resolution).

Jobs run inside the FastAPI process via APScheduler. Heavy logic lives in
trigger-agnostic services (e.g. resolution_runner) so jobs stay thin and
can move to a Railway cron service or Celery worker without rewrites.
"""

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from apps.api.config import settings
from apps.api.models.database import async_session
from apps.api.services.resolution_runner import run_resolution_sweep
from apps.api.services.sync import sync_all_accounts

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
