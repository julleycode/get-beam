"""Celery tasks for identity resolution + Tier 1 enrichment pipeline."""

import asyncio

import structlog
from sqlalchemy import select

from apps.api.models.database import async_session
from apps.api.models.site import Site
from apps.api.models.visitor import Visitor
from apps.api.services.celery_app import celery_app
from apps.api.services.enricher import Enricher
from apps.api.services.identity_resolver import IdentityResolver
from apps.api.services.segmentation_trigger import check_and_trigger_segmentation

logger = structlog.get_logger()


@celery_app.task(name="apps.api.tasks.resolution_tasks.process_all_pending_visitors")
def process_all_pending_visitors() -> dict:
    return asyncio.get_event_loop().run_until_complete(_process_all())


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
    result = await db.execute(
        select(Visitor).where(
            Visitor.site_id == site_id,
            Visitor.identity_status == "anonymous",
            Visitor.intent_score >= 40,
        ).order_by(Visitor.intent_score.desc()).limit(50)
    )
    visitors = list(result.scalars().all())

    resolver = IdentityResolver(db)
    enricher = Enricher(db)
    resolved = 0
    enriched = 0

    for visitor in visitors:
        identified = await resolver.resolve(visitor)
        if identified:
            resolved += 1
            # Cascade enrichment: PDL → Proxycurl → Twitter (auto)
            profile = await enricher.enrich_tier1(visitor, identified)
            if profile:
                enriched += 1

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
    r, e = asyncio.get_event_loop().run_until_complete(_run_single(site_id))
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
    return asyncio.get_event_loop().run_until_complete(
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
