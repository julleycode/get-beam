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
from apps.api.services.retention import (
    purge_events_older_than,
    purge_agent_fetch_events_older_than,
)
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
    """Periodic job: delete raw events + agent_fetch_events past retention.

    Each purge handles its own sessions and its own Postgres advisory lock
    (single-flight across replicas). The two purges are independent — a failure
    in one never blocks the other.
    """
    try:
        result = await purge_events_older_than()
        if result.get("deleted"):
            logger.info("retention_purge_job_complete", **result)
    except Exception:
        logger.exception("retention_purge_crashed")
    try:
        agent_result = await purge_agent_fetch_events_older_than()
        if agent_result.get("deleted"):
            logger.info("agent_fetch_retention_purge_job_complete", **agent_result)
    except Exception:
        logger.exception("agent_fetch_retention_purge_crashed")


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


async def _connection_nudge_job() -> None:
    """Periodic job: email owners whose social token is expiring/expired.

    check_expiring_connections manages its own session, throttles per account,
    and isolates per-account send failures.
    """
    try:
        from apps.api.services.connection_nudge import check_expiring_connections

        await check_expiring_connections()
    except Exception:
        logger.exception("connection_nudge_crashed")


async def _referral_activation_job() -> None:
    """Periodic job: reward pending referrals whose referee has real events.

    activate_pending_referrals manages its own session, holds an advisory
    lock, and isolates per-row failures.
    """
    try:
        from apps.api.services.referral_activation import activate_pending_referrals

        await activate_pending_referrals()
    except Exception:
        logger.exception("referral_activation_crashed")


async def _outcome_digest_job() -> None:
    """Weekly job: email site owners their Beam outcomes summary.

    send_weekly_outcome_digests manages its own session, holds an advisory
    lock, throttles per site, and isolates per-site send failures.
    """
    try:
        from apps.api.services.outcome_digest import send_weekly_outcome_digests

        await send_weekly_outcome_digests()
    except Exception:
        logger.exception("outcome_digest_crashed")


async def _agent_verification_sweep_job() -> None:
    """Periodic job: upgrade eligible ua-only agent visits to ip-verified.

    run_verification_sweep opens its own row iteration with per-row fail-open
    isolation; this wrapper opens the session and swallows any top-level crash.
    Never touches the ingest hot path (SPEC AC5 / Resolved Open Question 2).
    """
    try:
        from apps.api.services import agent_verification
        from apps.api.services.agent_company_resolution import (
            run_company_resolution_sweep,
        )

        async with async_session() as db:
            await agent_verification.run_verification_sweep(db)
            # EvalLayer Phase 05: 2nd step — resolve eligible agent visits into
            # company/lead records via the existing waterfall (own fail-open
            # per-row isolation). Runs after verification so newly ip-verified
            # rows are eligible in the same sweep.
            await run_company_resolution_sweep(db)
    except Exception:
        logger.exception("agent_verification_sweep_crashed")


async def _handoff_correlation_sweep_job() -> None:
    """Periodic job: link recent on-demand agent fetches to human AI-referral clicks.

    run_handoff_correlation_sweep opens its own per-row fail-open iteration; this
    wrapper opens the session and swallows any top-level crash. Never touches the
    ingest hot path (SPEC Constraint 4). Handoff Detection H2 — its own job, NOT
    chained into _agent_verification_sweep_job.
    """
    try:
        from apps.api.services.agent_handoff_correlation import (
            run_handoff_correlation_sweep,
        )

        async with async_session() as db:
            await run_handoff_correlation_sweep(db)
    except Exception:
        logger.exception("handoff_correlation_sweep_crashed")


async def _intent_signal_sweep_job() -> None:
    """Periodic job: live commercial-page intent alerts + spike detection (H3).

    run_intent_signal_sweep opens its own per-(site,page) fail-open iteration;
    this wrapper opens the session and swallows any top-level crash. Never touches
    the ingest hot path. Handoff Detection H3 — its own job, additive, registered
    after H2's _handoff_correlation_sweep_job.
    """
    try:
        from apps.api.services.agent_intent_signals import run_intent_signal_sweep

        async with async_session() as db:
            await run_intent_signal_sweep(db)
    except Exception:
        logger.exception("intent_signal_sweep_crashed")


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
    scheduler.add_job(
        _agent_verification_sweep_job,
        "interval",
        minutes=settings.agent_verification_sweep_interval_minutes,
        id="agent_verification_sweep",
        replace_existing=True,
    )
    scheduler.add_job(
        _handoff_correlation_sweep_job,
        "interval",
        minutes=settings.handoff_correlation_sweep_interval_minutes,
        id="handoff_correlation_sweep",
        replace_existing=True,
    )
    scheduler.add_job(
        _intent_signal_sweep_job,
        "interval",
        minutes=settings.intent_signal_sweep_interval_minutes,
        id="intent_signal_sweep",
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
    if settings.connection_nudge_enabled:
        scheduler.add_job(
            _connection_nudge_job,
            "interval",
            hours=1,
            id="connection_nudge",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=45),
        )
    if settings.referrals_enabled:
        scheduler.add_job(
            _referral_activation_job,
            "interval",
            hours=1,
            id="referral_activation",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=60),
        )
    if settings.outcomes_digest_enabled:
        from apscheduler.triggers.cron import CronTrigger

        scheduler.add_job(
            _outcome_digest_job,
            CronTrigger(day_of_week="mon", hour=15, timezone="UTC"),
            id="outcome_digest",
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
