"""Background scheduler for periodic jobs (feed sync, identity resolution).

Jobs run inside the FastAPI process via APScheduler. Heavy logic lives in
trigger-agnostic services (e.g. resolution_runner) so jobs stay thin and
can move to a Railway cron service or Celery worker without rewrites.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from apps.api.config import settings
from apps.api.models.database import async_session
from apps.api.services.resolution_runner import run_resolution_sweep
from apps.api.services.retention import (
    purge_events_older_than,
    purge_agent_fetch_events_older_than,
    purge_request_logs_older_than,
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
    try:
        log_result = await purge_request_logs_older_than()
        if log_result.get("deleted"):
            logger.info("request_log_retention_purge_job_complete", **log_result)
    except Exception:
        logger.exception("request_log_retention_purge_crashed")


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


async def _daily_digest_job() -> None:
    """Daily job: email owners of pixel-active sites their 24h working report.

    send_daily_digests manages its own session, holds an advisory lock,
    throttles per site (20h), and isolates per-site send failures.
    """
    try:
        from apps.api.services.daily_digest import send_daily_digests

        await send_daily_digests()
    except Exception:
        logger.exception("daily_digest_crashed")


async def _agent_ip_range_refresh_job() -> None:
    """Periodic job: re-fetch the published per-agent IP-range datasets.

    Verification is only as good as the freshness of what it checks against: a
    rotated range that is not picked up turns a real agent into an ``ip-mismatch``
    — the same verdict a forged UA gets. Fail-open throughout; a failed refresh
    leaves the existing datasets in place.
    """
    try:
        from apps.api.services.agent_ip_range_refresh import refresh_agent_ip_ranges

        await refresh_agent_ip_ranges()
    except Exception:
        logger.exception("agent_ip_range_refresh_crashed")


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


async def _cadence_bot_flag_sweep_job() -> None:
    """Periodic job: behavioral stealth-crawler detection (cadence bot flag).

    run_cadence_bot_flag_sweep opens its own per-(site, visitor) fail-open
    iteration; this wrapper opens the session and swallows any top-level crash.
    Never touches the ingest hot path — detection is batch-only by design (AC-4).

    The enabled-check lives here AND inside the sweep: the job is registered
    unconditionally (unlike the optional jobs below) because `events` rows exist
    regardless of the flag, so retroactive detection is the point — but with the
    flag off this returns before opening a session or issuing a single query.
    """
    from apps.api.config import settings

    if not settings.cadence_bot_flag_enabled:
        return
    try:
        from apps.api.services.cadence_bot_flag_sweep import (
            run_cadence_bot_flag_sweep,
        )

        async with async_session() as db:
            await run_cadence_bot_flag_sweep(db)
    except Exception:
        logger.exception("cadence_bot_flag_sweep_crashed")


async def _outlier_traffic_damping_sweep_job() -> None:
    """Periodic job: outlier / internal-traffic damping.

    run_outlier_traffic_damping_sweep opens its own per-(site, visitor) fail-open
    iteration; this wrapper opens the session and swallows any top-level crash.
    Never touches the ingest hot path — detection is batch-only by design.

    Unlike the cadence job above there is no global settings flag to check here:
    the opt-in is PER SITE (Site.internal_damping_enabled, default False), so the
    sweep's own first query returns an empty site list and it exits immediately
    when nobody has opted in.
    """
    try:
        from apps.api.services.outlier_traffic_damping_sweep import (
            run_outlier_traffic_damping_sweep,
        )

        async with async_session() as db:
            await run_outlier_traffic_damping_sweep(db)
    except Exception:
        logger.exception("outlier_traffic_damping_sweep_crashed")


async def _promotion_sweep_job() -> None:
    """Periodic job: promote fresh tokenized-link clicks to a verified identity.

    run_promotion_sweep opens its own session, holds a Postgres advisory lock
    (single-flight across replicas), re-checks the feature flag, and isolates
    per-visitor failures; this wrapper only swallows a top-level crash. Never
    touches the ingest hot path — promotion is batch-only by design (SPEC AC11).
    """
    try:
        from apps.api.services.promotion_sweep_runner import run_promotion_sweep

        await run_promotion_sweep()
    except Exception:
        logger.exception("promotion_sweep_crashed")


async def _graph_erasure_sweep_job() -> None:
    """Periodic job: drain the cross-tenant identity-graph erasure queue.

    run_graph_erasure_sweep opens its own session, holds a Postgres advisory
    lock (single-flight across replicas), re-checks the feature flag, and
    isolates per-row failures; this wrapper only swallows a top-level crash.
    Never runs inside a request — all graph work is deliberately out of band so
    the deletion endpoint cannot become an existence oracle.
    """
    try:
        from apps.api.services.graph_erasure import run_graph_erasure_sweep

        await run_graph_erasure_sweep()
    except Exception:
        logger.exception("graph_erasure_sweep_crashed")


async def _sweep_one_site(
    site_id: str,
    allow_defer: bool,
    wait_seconds: int = 0,
) -> tuple[str, int]:
    """Attempt one site's FULL recompute. Returns (outcome, visitors).

    Outcomes: "ran" | "deferred" | "skipped".

    E17 — the Redis-degraded fail direction is FLAG-CONDITIONAL, not blanket.
    "A duplicate full recompute is idempotent" is true of full-vs-full and FALSE
    of full-vs-incremental: a `since=None` SET racing an additive incremental
    merge can inflate total_pageviews / total_sessions, which is the exact G1
    failure this phase exists to prevent. So with the incremental flag ON we skip
    the site (stale-but-correct beats wrong — D7's own hierarchy); with it OFF we
    proceed.
    """
    from apps.api.services import aggregation_debounce as dbnc
    from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

    key = dbnc.debounce_key(site_id)
    marker = dbnc.sweep_pending_key(site_id)

    acquired = await dbnc.try_acquire(key, settings.aggregation_min_interval_seconds)

    # End-of-pass retry (E16c): the yield marker is already set, so no NEW
    # per-ingest run may take the key — it therefore frees within one TTL. Poll
    # for it rather than giving up instantly, otherwise a short pass never
    # actually retries and the deferred site waits a whole interval.
    if acquired is False and wait_seconds > 0:
        deadline = asyncio.get_running_loop().time() + wait_seconds
        while acquired is False and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(1)
            acquired = await dbnc.try_acquire(
                key, settings.aggregation_min_interval_seconds
            )

    if acquired is None:
        if settings.aggregation_incremental_enabled:
            logger.warning("aggregation_sweep_skipped_redis_degraded", site_id=site_id)
            return ("skipped", 0)
        # Flag OFF → full-vs-full only → genuinely idempotent → fail open.
        logger.info("aggregation_sweep_redis_degraded_proceeding", site_id=site_id)
    elif acquired is False:
        if allow_defer:
            # E16(a) — set the YIELD MARKER instead of silently dropping the
            # site. Per-ingest triggers stand down while it is set, so the
            # debounce key frees within one TTL and the end-of-pass retry wins.
            await dbnc.try_acquire(
                marker,
                settings.aggregation_min_interval_seconds
                * dbnc.SWEEP_PENDING_TTL_MULTIPLIER,
            )
            logger.info("aggregation_sweep_deferred", site_id=site_id)
            return ("deferred", 0)
        logger.warning("aggregation_sweep_site_contended", site_id=site_id)
        await dbnc.release(marker)
        return ("skipped", 0)

    try:
        async with async_session() as db:
            # E19 — the sweep is the REPAIR path. `since=None` is passed
            # explicitly and unconditionally; the incremental branch is never
            # taken, whatever aggregation_incremental_enabled says. This job is
            # the sole writer of avg_time_on_page and intent_score under D7.
            count = await aggregate_visitors_for_site(db, site_id, since=None)
        return ("ran", count)
    except Exception:
        logger.exception("aggregation_sweep_site_failed", site_id=site_id)
        return ("skipped", 0)
    finally:
        # E16(d) — clear the marker whether the site succeeded or failed, so a
        # crash can never wedge every per-ingest trigger for that site.
        await dbnc.release(marker)


async def _aggregation_sweep_job() -> None:
    """Periodic FULL-recompute repair sweep (capacity-hardening Phase 3, item 11).

    This job is the mechanism behind the Public Contracts freshness bound: with
    `aggregation_incremental_enabled` ON it is the ONLY writer of
    `avg_time_on_page` and `intent_score` (D7), so worst-case staleness equals
    `aggregation_sweep_interval_minutes`. With the flag OFF it is
    redundant-but-harmless (an idempotent full recompute).

    Pool-awareness is MANDATORY, not advisory (item 11d): the API container's
    pool is pool_size=3 + max_overflow=2 = 5 connections, shared with request
    traffic and ten other scheduler jobs. Sites are processed STRICTLY
    SEQUENTIALLY, one open session at a time — no parallel fan-out over sites,
    and no long-lived outer session held across the loop.
    """
    try:
        from apps.api.models.site import Site

        async with async_session() as db:
            result = await db.execute(select(Site.site_id))
            site_ids = [row[0] for row in result.all()]

        ran = 0
        visitors = 0
        deferred: list[str] = []

        for site_id in site_ids:
            outcome, count = await _sweep_one_site(site_id, allow_defer=True)
            if outcome == "ran":
                ran += 1
                visitors += count
            elif outcome == "deferred":
                deferred.append(site_id)

        # E16(c) — retry deferred sites once at the end of the pass. The debounce
        # TTL is aggregation_min_interval_seconds and no NEW per-ingest run may
        # take the key while the yield marker is set, so the key frees within one
        # TTL. Without this retry even transient contention costs a full interval.
        retried = 0
        for site_id in deferred:
            outcome, count = await _sweep_one_site(
                site_id,
                allow_defer=False,
                wait_seconds=settings.aggregation_min_interval_seconds + 5,
            )
            if outcome == "ran":
                ran += 1
                retried += 1
                visitors += count

        logger.info(
            "aggregation_sweep_complete",
            sites=len(site_ids),
            aggregated=ran,
            deferred=len(deferred),
            retried=retried,
            visitors=visitors,
        )
    except Exception:
        logger.exception("aggregation_sweep_crashed")


def start_scheduler() -> None:
    """Start the background scheduler. Call once at app startup.

    Capacity-hardening Phase 4c: EVERY `interval` job below carries an explicit
    `jitter` and `misfire_grace_time`.

    - `jitter` — these are interval triggers, so they align to BOOT time, not to
      the wall clock. Every container in a deploy boots within seconds of the
      others, so without jitter the same job fires simultaneously across all
      containers against one shared 5-connection pool. Jitter is nominally ~10%
      of the default interval, capped, so the fleet spreads out.
    - `misfire_grace_time` — APScheduler's default is 1 second, so any job that
      is late (busy event loop, container under load) is SILENTLY SKIPPED rather
      than run. Every value below is explicit for that reason.

    The single `CronTrigger` job (`outcome_digest`) is deliberately excluded:
    `jitter` semantics differ for cron, and a weekly digest has no thundering-herd
    problem. Asserted by tests/unit/test_scheduler_job_config.py (AC13), which
    derives the counts from the AST — never from line numbers.
    """
    scheduler.add_job(
        _sync_job,
        "interval",
        minutes=settings.sync_interval_minutes,
        id="sync_all_feeds",
        replace_existing=True,
        jitter=300,
        misfire_grace_time=300,
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
        jitter=180,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _publish_scheduled_blog_job,
        "interval",
        minutes=1,
        id="publish_scheduled_blog",
        replace_existing=True,
        # 1-minute interval: keep jitter small enough that publishing stays
        # near-on-time, but non-zero so it stops coinciding with the longer jobs.
        jitter=6,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        _retention_purge_job,
        "interval",
        hours=settings.retention_purge_interval_hours,
        id="retention_purge",
        replace_existing=True,
        # Holds TWO connections for the whole purge (an outer advisory-lock
        # session plus an inner delete session — retention.py:116/122, :177/183).
        # That 2-connection reservation is documented in the config.py 4b pool
        # math; the wide jitter keeps it off the boot burst.
        jitter=600,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _agent_ip_range_refresh_job,
        "interval",
        hours=settings.agent_ip_range_refresh_interval_hours,
        id="agent_ip_range_refresh",
        replace_existing=True,
        # Seed an early run: the shipped datasets are empty placeholders, so
        # until the first refresh lands no visit can be verified at all. The
        # in-memory job store recomputes the first fire from boot on every
        # restart, which would otherwise leave a whole interval with no data.
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=60),
        jitter=600,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _agent_verification_sweep_job,
        "interval",
        minutes=settings.agent_verification_sweep_interval_minutes,
        id="agent_verification_sweep",
        replace_existing=True,
        jitter=90,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _handoff_correlation_sweep_job,
        "interval",
        minutes=settings.handoff_correlation_sweep_interval_minutes,
        id="handoff_correlation_sweep",
        replace_existing=True,
        # The job store is in-memory, so every restart recomputes the first fire
        # as boot + interval. A process recycled more often than the interval
        # would therefore never run this sweep at all. Seed an early first run
        # (same pattern as the resolution sweep above); the sweep is cheap and
        # bounded, so an extra run right after boot costs nothing.
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
        jitter=60,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _intent_signal_sweep_job,
        "interval",
        minutes=settings.intent_signal_sweep_interval_minutes,
        id="intent_signal_sweep",
        replace_existing=True,
        jitter=60,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _cadence_bot_flag_sweep_job,
        "interval",
        minutes=settings.cadence_bot_flag_sweep_interval_minutes,
        id="cadence_bot_flag_sweep",
        replace_existing=True,
        jitter=90,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _outlier_traffic_damping_sweep_job,
        "interval",
        minutes=settings.outlier_traffic_damping_sweep_interval_minutes,
        id="outlier_traffic_damping_sweep",
        replace_existing=True,
        jitter=90,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _aggregation_sweep_job,
        "interval",
        minutes=settings.aggregation_sweep_interval_minutes,
        id="aggregation_sweep",
        replace_existing=True,
        # E18 — explicit boot offset, same reason as resolution_sweep above:
        # APScheduler's first interval fire is at +interval, and the API process
        # restarts on every deploy. A 60-minute job on a service that redeploys
        # more often than hourly would NEVER fire, voiding the Public Contracts
        # staleness bound for avg_time_on_page / intent_score. The offset is
        # larger than the existing 20/30/45/60s offsets so the (heaviest) sweep
        # does not pile onto the boot burst; Phase 4c's jitter then spreads it
        # across containers.
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=90),
        # Phase 4c — the heaviest job in the file (full-history recompute per
        # site). Jitter matters most here: without it every container runs the
        # unbounded sweep at the same instant against the shared pool.
        jitter=300,
        misfire_grace_time=600,
    )
    if settings.promotion_sweep_enabled:
        scheduler.add_job(
            _promotion_sweep_job,
            "interval",
            minutes=settings.promotion_sweep_interval_minutes,
            id="promotion_sweep",
            replace_existing=True,
            # Short interval (1-2 min) inside a 5-minute SLA: jitter stays small
            # so promotion stays on time, but non-zero so replicas spread out.
            jitter=15,
            misfire_grace_time=60,
        )
    if settings.graph_erasure_sweep_enabled:
        scheduler.add_job(
            _graph_erasure_sweep_job,
            "interval",
            minutes=settings.graph_erasure_sweep_interval_minutes,
            id="graph_erasure_sweep",
            replace_existing=True,
            # Phase 4c convention: explicit jitter + misfire_grace_time. Small
            # jitter (5-minute interval), and a grace window wide enough that a
            # deploy restart never silently skips a pass on a legal clock.
            jitter=30,
            misfire_grace_time=300,
        )
    if settings.changelog_sync_enabled:
        scheduler.add_job(
            _changelog_sync_job,
            "interval",
            hours=settings.changelog_sync_interval_hours,
            id="changelog_sync",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
            jitter=600,
            misfire_grace_time=3600,
        )
    if settings.connection_nudge_enabled:
        scheduler.add_job(
            _connection_nudge_job,
            "interval",
            hours=1,
            id="connection_nudge",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=45),
            jitter=300,
            misfire_grace_time=600,
        )
    if settings.referrals_enabled:
        scheduler.add_job(
            _referral_activation_job,
            "interval",
            hours=1,
            id="referral_activation",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=60),
            jitter=300,
            misfire_grace_time=600,
        )
    if settings.outcomes_digest_enabled:
        from apscheduler.triggers.cron import CronTrigger

        scheduler.add_job(
            _outcome_digest_job,
            CronTrigger(day_of_week="mon", hour=15, timezone="UTC"),
            id="outcome_digest",
            replace_existing=True,
        )
    if settings.daily_digest_enabled:
        from apscheduler.triggers.cron import CronTrigger

        scheduler.add_job(
            _daily_digest_job,
            CronTrigger(hour=settings.daily_digest_hour_utc, timezone="UTC"),
            id="daily_digest",
            replace_existing=True,
            # No jitter (E20 excludes cron jobs — a fixed send hour is the point;
            # the per-site advisory lock already prevents replica double-sends).
            # A generous grace window so a deploy at the top of the hour doesn't
            # silently skip the whole day's digest.
            misfire_grace_time=3600,
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
