"""Trigger-agnostic identity-resolution runner.

`run_resolution_for_site` is the single "what runs" implementation: the
APScheduler sweep, the POST /visitors/{site_id}/resolve endpoint, and any
future Celery/cron worker all call this same function. Triggers decide
*when*; this module decides *what*. To change scheduling later, swap the
caller — never fork this logic into a trigger.

Upgrade path (in order, when the time comes):
  1. Today: APScheduler inside the FastAPI process (zero extra infra).
  2. When a sweep takes more than a few minutes per run, or API latency
     degrades while it runs: move `run_resolution_sweep` to a Railway cron
     service (run-and-exit) — much cheaper than an always-on worker.
  3. Only after that: a dedicated Celery worker.
"""

import structlog
from sqlalchemy import select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.agent_handoff_link import AgentHandoffLink
from apps.api.models.database import async_session
from apps.api.models.site import Site
from apps.api.models.visitor import Visitor
from apps.api.services.billing import check_usage_allowed, increment_usage
from apps.api.services.enricher import Enricher
from apps.api.services.identity_resolver import IdentityResolver
from apps.api.services.resolution_eligibility import (
    ai_attributable_visitor_filter,
    first_win_boost_site_ids,
    resolution_candidate_filter,
    resolution_not_deferred_filter,
    site_resolves_all_us,
)
from apps.api.services.segmentation_trigger import check_and_trigger_segmentation

logger = structlog.get_logger()

# Key for the Postgres advisory lock that keeps the sweep single-flight
# across replicas. hashtext() maps it to the int key advisory locks need.
_SWEEP_LOCK_KEY = "beam_resolution_sweep"

# Per-site batch size per run. The hourly-ish sweep drains backlogs over
# successive runs; daily/monthly budgets inside the loop bound real spend.
SWEEP_MAX_RESOLVE_PER_SITE = 20


async def run_resolution_for_site(
    db: AsyncSession, site: Site, max_resolve: int = 20
) -> dict[str, int]:
    """Resolve + enrich eligible visitors for one site.

    Eligibility: identity_status == "anonymous" AND either AI attribution
    (ai_source or a same-site handoff link) or the resolution intent gate —
    intent_score >= RESOLUTION_MIN_INTENT (20), with two widenings: on owner
    sites whose url matches ``settings.resolve_all_us_domains`` US visitors
    qualify at any intent_score, and while a site is inside the first-win
    boost window (fewer than ``settings.first_win_boost_count`` identified
    visitors ever) the floor is waived entirely.

    AI-attributable humans first, then highest intent. Each visitor passes
    the monthly billing gate (free=10/mo) before resolution; the resolver
    itself enforces the per-site daily budget and the 30-day no-retry rule.
    Each visitor is processed in isolation so one failure can't abort the
    batch.

    Returns counters: processed (attempted), resolved, enriched,
    skipped_plan_limit (eligible but blocked by the monthly plan limit).
    """
    from apps.api.services.agent_visitor_filters import human_only_visitor_filter

    boost_ids = await first_win_boost_site_ids(db, [site.site_id])

    # Outlier / internal-traffic damping. Measured live 27-07-26: heavy visitors
    # are identified at 11.1% vs 2.0% for normal ones purely because they
    # accumulate huge intent_score and this query sorts by it — on one site 3 of
    # 8 identified visitors were heavy, i.e. 37.5% of that site's daily budget
    # spent on (probably) the owner's own traffic.
    #
    # SUGGESTION-ONLY AUTOMATION (calibrated live 27-07-26). Only a visitor the
    # CUSTOMER has confirmed is their own (internal_override == "internal") is
    # deprioritised. The automatic is_internal_suspect flag deliberately does NOT
    # appear here: at the measured production distribution it would have flagged
    # 34 visitors at 20x/3d, 5 of them ALREADY identified with a real email out
    # of only 28 identified visitors system-wide — i.e. auto-deprioritising would
    # push ~18% of real leads to the back of the resolution queue on a guess.
    #
    # is_distinct_from, so NULL (never reviewed) sorts with the un-confirmed
    # majority rather than falling out on three-valued logic.
    #
    # DEPRIORITISE, NEVER EXCLUDE: False sorts before True, so confirmed-internal
    # visitors go to the back of the queue but still resolve if budget remains.
    # Opt-in per site — when enabled, confirmed-internal status remains the
    # first ordering key ahead of AI attribution and intent.
    handoff_visitor_ids = (
        select(AgentHandoffLink.visitor_id.label("visitor_id"))
        .where(AgentHandoffLink.site_id == site.site_id)
        .distinct()
        .subquery("handoff_visitor_ids")
    )
    handoff_linked = handoff_visitor_ids.c.visitor_id.is_not(None)
    ai_attributable_human = ai_attributable_visitor_filter(
        handoff_linked=handoff_linked
    )
    candidate_eligible = resolution_candidate_filter(
        [site.site_id] if site_resolves_all_us(site.url) else [],
        no_floor_site_ids=boost_ids,
        handoff_linked=handoff_linked,
    )
    order_by = (
        (
            Visitor.internal_override.is_distinct_from("internal").desc(),
            ai_attributable_human.desc(),
            Visitor.intent_score.desc(),
        )
        # getattr, not attribute access: fails SAFE to "damping off" for any
        # site object that predates the column (unflushed ORM instance, test
        # stub). Damping must never switch itself on by accident.
        if getattr(site, "internal_damping_enabled", False)
        else (ai_attributable_human.desc(), Visitor.intent_score.desc())
    )

    result = await db.execute(
        select(Visitor)
        .outerjoin(
            handoff_visitor_ids,
            handoff_visitor_ids.c.visitor_id == Visitor.visitor_id,
        )
        .where(
            Visitor.site_id == site.site_id,
            # Identity-honesty Phase 1 (B1): candidate-tier visitors stay in the
            # sweep so a LATER deterministic signal (a form capture, a _bid email
            # click) can still upgrade them. Their pass is scoped to those
            # deterministic checks only — see deterministic_only below — so the
            # sweep can never auto-promote a candidate off another graph guess.
            Visitor.identity_status.in_(("anonymous", "candidate")),
            candidate_eligible,
            Visitor.do_not_resolve.is_(False),
            # Skip visitors held back by a provider outage until their
            # watermark passes. Without this they stay top-ranked by intent and
            # re-consume this batch's 20 slots on every single run.
            resolution_not_deferred_filter(),
            # AC2 (GUARD #2): never re-resolve the synthetic agent-derived rows
            # (they run through resolve() only via the company-resolution sweep).
            human_only_visitor_filter(),
        )
        .order_by(*order_by)
        .limit(max_resolve)
    )
    visitors = list(result.scalars().all())
    counters = {"processed": 0, "resolved": 0, "enriched": 0, "skipped_plan_limit": 0}
    if not visitors:
        return counters

    resolver = IdentityResolver(db)
    enricher = Enricher(db)

    for index, visitor in enumerate(visitors):
        # Monthly plan limit (free=10, pro=50). Checked per visitor because
        # each successful resolution increments the counter.
        if not await check_usage_allowed(db, site.user_id):
            counters["skipped_plan_limit"] = len(visitors) - index
            logger.info(
                "resolution_stopped_plan_limit",
                site_id=site.site_id,
                resolved_before_stop=counters["resolved"],
                skipped=counters["skipped_plan_limit"],
            )
            break
        counters["processed"] += 1
        try:
            identified = await resolver.resolve(
                visitor,
                deterministic_only=(visitor.identity_status == "candidate"),
            )
            if identified:
                counters["resolved"] += 1
                await increment_usage(db, site.user_id)
                profile = await enricher.enrich_tier1(visitor, identified)
                if profile:
                    counters["enriched"] += 1
        except Exception as e:
            logger.warning("resolve_visitor_error", visitor_id=visitor.visitor_id, error=str(e))

    logger.info(
        "resolution_job_complete",
        site_id=site.site_id,
        eligible=len(visitors),
        **counters,
    )

    # Documented rule: auto-segment at 10+ new enriched visitors.
    if counters["enriched"]:
        try:
            await check_and_trigger_segmentation(db, site.site_id)
        except Exception as e:
            logger.warning("auto_segmentation_failed", site_id=site.site_id, error=str(e))

    return counters


async def _try_acquire_sweep_lock(db: AsyncSession) -> bool | None:
    """Try the Postgres advisory lock guarding the sweep.

    Returns True when acquired, False when another replica holds it, and
    None when the database doesn't support advisory locks (SQLite in
    dev/test) — in that case the sweep proceeds unguarded, matching the
    fail-open behavior of the segmentation Redis lock.
    """
    try:
        result = await db.execute(
            sql_text("SELECT pg_try_advisory_lock(hashtext(:key))"),
            {"key": _SWEEP_LOCK_KEY},
        )
        return bool(result.scalar())
    except Exception as exc:
        logger.warning("resolution_sweep_lock_unavailable", error=str(exc))
        return None


async def _release_sweep_lock(db: AsyncSession) -> None:
    try:
        await db.execute(
            sql_text("SELECT pg_advisory_unlock(hashtext(:key))"),
            {"key": _SWEEP_LOCK_KEY},
        )
    except Exception:
        pass


async def run_resolution_sweep() -> None:
    """Resolve eligible visitors across ALL sites. Single-flight via a
    Postgres advisory lock so multiple Railway replicas (each running its
    own APScheduler) can't double-run and double-burn provider credits.

    The lock is session-scoped: the lock session stays open for the whole
    sweep and the lock auto-releases if the process dies mid-run. Per-site
    work runs on its own session, isolated so one site's failure doesn't
    stop the rest.
    """
    async with async_session() as lock_db:
        acquired = await _try_acquire_sweep_lock(lock_db)
        if acquired is False:
            logger.info("resolution_sweep_lock_busy")
            return

        try:
            # Only sites that opted into auto-identify. Sites with the toggle off
            # (the default) are resolved one visitor at a time via the per-row
            # Identify button instead.
            #
            # `tracking_enabled` is a second, independent gate: a paused site
            # (manual toggle OR the inactivity auto-pause) must not burn
            # resolver/enrichment/Gemini credits draining its existing backlog.
            # Ingest already 204s for these sites, so the backlog is frozen —
            # this is what makes a pause actually stop spend.
            sites_result = await lock_db.execute(
                select(Site).where(
                    Site.auto_identify_enabled.is_(True),
                    Site.tracking_enabled.is_(True),
                )
            )
            sites = list(sites_result.scalars().all())
            totals = {"processed": 0, "resolved": 0, "enriched": 0, "skipped_plan_limit": 0}
            failed_sites = 0

            for site in sites:
                try:
                    async with async_session() as db:
                        counters = await run_resolution_for_site(
                            db, site, max_resolve=SWEEP_MAX_RESOLVE_PER_SITE
                        )
                    for key in totals:
                        totals[key] += counters.get(key, 0)
                except Exception:
                    failed_sites += 1
                    logger.exception("resolution_sweep_site_failed", site_id=site.site_id)

            logger.info(
                "resolution_sweep_complete",
                sites=len(sites),
                failed_sites=failed_sites,
                **totals,
            )
        finally:
            if acquired:
                await _release_sweep_lock(lock_db)
