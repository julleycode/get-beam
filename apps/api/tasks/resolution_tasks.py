"""Celery tasks for identity resolution + Tier 1 enrichment pipeline."""

import asyncio

import structlog
from sqlalchemy import select

from apps.api.models.database import async_session
from apps.api.models.site import Site
from apps.api.models.visitor import Visitor, resolution_intent_filter
from apps.api.services.agent_visitor_filters import human_only_visitor_filter
from apps.api.services.auto_drafter import AutoDrafter
from apps.api.services.billing import check_usage_allowed, increment_usage
from apps.api.services.celery_app import celery_app
from apps.api.services.enricher import Enricher
from apps.api.services.identity_resolver import IdentityResolver
from apps.api.services.resolution_eligibility import (
    first_win_boost_site_ids,
    site_resolves_all_us,
)
from apps.api.services.segmentation_trigger import check_and_trigger_segmentation
from apps.api.services.social_intelligence import SocialIntelligence

logger = structlog.get_logger()


@celery_app.task(name="apps.api.tasks.resolution_tasks.process_all_pending_visitors")
def process_all_pending_visitors() -> dict:
    return asyncio.run(_process_all())


async def _process_all() -> dict:
    async with async_session() as db:
        result = await db.execute(select(Site.site_id))
        site_ids = [row[0] for row in result.all()]

    total_resolved = 0
    total_enriched = 0

    for site_id in site_ids:
        async with async_session() as db:
            r, e = await _process_site(db, site_id)
            total_resolved += r
            total_enriched += e

        # Check segmentation trigger after processing each site
        if total_enriched > 0:
            async with async_session() as db:
                await check_and_trigger_segmentation(db, site_id)

    return {"resolved": total_resolved, "enriched": total_enriched}


async def _process_site(db, site_id: str) -> tuple[int, int]:
    # Look up the site owner to enforce plan usage limits
    site_result = await db.execute(select(Site).where(Site.site_id == site_id))
    site = site_result.scalar_one_or_none()
    site_user_id = site.user_id if site else None

    # First-win boost: a site with fewer than settings.first_win_boost_count
    # identified visitors ever waives the intent floor entirely.
    boost_ids = await first_win_boost_site_ids(db, [site_id]) if site else []

    result = await db.execute(
        select(Visitor).where(
            Visitor.site_id == site_id,
            Visitor.identity_status == "anonymous",
            resolution_intent_filter(
                [site.site_id] if site and site_resolves_all_us(site.url) else [],
                no_floor_site_ids=boost_ids,
            ),
            Visitor.do_not_resolve.is_(False),
            # AC2 (GUARD #2): this Celery-beat task also fires Enricher.enrich_tier1
            # + AutoDrafter on resolved rows, so exclude synthetic agent-derived
            # rows explicitly — incidental intent_score=0 protection is not enough.
            human_only_visitor_filter(),
        ).order_by(Visitor.intent_score.desc()).limit(50)
    )
    visitors = list(result.scalars().all())

    resolver = IdentityResolver(db)
    enricher = Enricher(db)
    social_intel = SocialIntelligence(db)
    resolved = 0
    enriched = 0

    # Load the site owner User object once for auto-draft generation
    site_user = None
    if site_user_id is not None:
        from apps.api.models.user import User
        user_result = await db.execute(select(User).where(User.id == site_user_id))
        site_user = user_result.scalar_one_or_none()

    auto_drafter = AutoDrafter(db) if site_user else None

    for visitor in visitors:
        # ── Billing gate: skip resolution if monthly limit reached ──
        if site_user_id is not None:
            allowed = await check_usage_allowed(db, str(site_user_id))
            if not allowed:
                logger.info(
                    "resolution_skipped_billing_limit",
                    site_id=site_id,
                    visitor_id=visitor.visitor_id,
                    user_id=str(site_user_id),
                )
                continue

        identified = await resolver.resolve(visitor)
        if identified:
            resolved += 1
            # Increment billing usage counter after successful resolution
            if site_user_id is not None:
                await increment_usage(db, str(site_user_id))
            # Cascade enrichment: PDL → Proxycurl → Twitter (auto)
            profile = await enricher.enrich_tier1(visitor, identified)
            if profile:
                enriched += 1

                # ── Social Intelligence: fetch context for high-intent visitors ──
                if visitor.intent_score >= 60:
                    try:
                        social_context = await social_intel.fetch_social_context(
                            profile,
                            visitor_intent=visitor.intent_score,
                        )
                        if social_context.get("recent_posts"):
                            await social_intel.store_social_context(profile, social_context)

                            # ── Auto-draft: generate engagement draft for site owner ──
                            if auto_drafter and site_user:
                                try:
                                    enrichment_data = {
                                        "full_name": identified.full_name,
                                        "job_title": profile.job_title,
                                    }
                                    await auto_drafter.generate_for_visitor(
                                        visitor=visitor,
                                        enrichment_data=enrichment_data,
                                        social_context=social_context,
                                        user=site_user,
                                    )
                                except Exception as draft_err:
                                    logger.warning(
                                        "auto_draft_failed",
                                        visitor_id=visitor.visitor_id,
                                        error=str(draft_err),
                                    )
                    except Exception as social_err:
                        logger.warning(
                            "social_context_failed",
                            visitor_id=visitor.visitor_id,
                            error=str(social_err),
                        )

    logger.info(
        "site_resolution_complete",
        site_id=site_id,
        processed=len(visitors),
        resolved=resolved,
        enriched=enriched,
    )
    return resolved, enriched


@celery_app.task(name="apps.api.tasks.resolution_tasks.process_single_site")
def process_single_site(site_id: str) -> dict:
    r, e = asyncio.run(_run_single(site_id))
    return {"resolved": r, "enriched": e}


async def _run_single(site_id: str) -> tuple[int, int]:
    async with async_session() as db:
        result = await _process_site(db, site_id)

    # Check segmentation trigger
    async with async_session() as db:
        await check_and_trigger_segmentation(db, site_id)

    return result


@celery_app.task(name="apps.api.tasks.resolution_tasks.enrich_visitor_tier2")
def enrich_visitor_tier2(visitor_id: str, site_id: str, user_id: str) -> dict:
    """Celery task for on-demand Tier 2 enrichment."""
    return asyncio.run(
        _enrich_tier2(visitor_id, site_id, user_id)
    )


async def _enrich_tier2(visitor_id: str, site_id: str, user_id: str) -> dict:
    async with async_session() as db:
        result = await db.execute(
            select(Visitor).where(
                Visitor.site_id == site_id,
                Visitor.visitor_id == visitor_id,
            )
        )
        visitor = result.scalar_one_or_none()
        if not visitor:
            return {"status": "error", "message": "Visitor not found"}

        enricher = Enricher(db)
        profile = await enricher.enrich_tier2(visitor, user_id)

        if profile:
            return {
                "status": "enriched",
                "completeness": profile.enrichment_completeness,
            }
        return {"status": "no_change"}
