import asyncio

import structlog
from sqlalchemy import select, func

from apps.api.agents.campaign_planner import plan_campaign
from apps.api.agents.segmenter import build_visitor_profiles, run_segmentation
from apps.api.models.database import async_session
from apps.api.models.site import Site
from apps.api.models.visitor import Visitor
from apps.api.services.celery_app import celery_app

logger = structlog.get_logger()

SEGMENTATION_THRESHOLD = 10


@celery_app.task(name="apps.api.tasks.segmentation_tasks.check_segmentation_triggers")
def check_segmentation_triggers() -> dict:
    return asyncio.get_event_loop().run_until_complete(_check_triggers())


async def _check_triggers() -> dict:
    async with async_session() as db:
        result = await db.execute(select(Site))
        sites = list(result.scalars().all())

    triggered = 0
    for site in sites:
        async with async_session() as db:
            count_result = await db.execute(
                select(func.count()).select_from(Visitor).where(
                    Visitor.site_id == site.site_id,
                    Visitor.enrichment_status == "enriched",
                )
            )
            enriched_count = count_result.scalar() or 0

            if enriched_count >= SEGMENTATION_THRESHOLD:
                await _run_segmentation_for_site(db, site)
                triggered += 1

    return {"triggered": triggered}


async def _run_segmentation_for_site(db, site: Site) -> None:
    result = await db.execute(
        select(Visitor).where(
            Visitor.site_id == site.site_id,
            Visitor.enrichment_status == "enriched",
        ).order_by(Visitor.intent_score.desc()).limit(50)
    )
    visitors = list(result.scalars().all())

    segments = await run_segmentation(
        db=db,
        site_id=site.site_id,
        site_name=site.name,
        site_description=site.description or "",
        site_category=site.category or "",
        visitors=visitors,
    )

    for segment in segments:
        profiles = await build_visitor_profiles(db, site.site_id, visitors)
        segment_profiles = [p for p in profiles if p["visitor_id"] in [
            m.visitor_id for m in (await db.execute(
                select(__import__("apps.api.models.segment", fromlist=["SegmentMember"]).SegmentMember).where(
                    __import__("apps.api.models.segment", fromlist=["SegmentMember"]).SegmentMember.segment_id == segment.id
                )
            )).scalars().all()
        ]]
        if segment_profiles:
            await plan_campaign(db, segment, segment_profiles)

    logger.info("segmentation_triggered", site_id=site.site_id, segments=len(segments))


@celery_app.task(name="apps.api.tasks.segmentation_tasks.run_segmentation_manual")
def run_segmentation_manual(site_id: str) -> dict:
    return asyncio.get_event_loop().run_until_complete(_run_manual(site_id))


async def _run_manual(site_id: str) -> dict:
    async with async_session() as db:
        site_result = await db.execute(select(Site).where(Site.site_id == site_id))
        site = site_result.scalar_one_or_none()
        if not site:
            return {"error": "Site not found"}
        await _run_segmentation_for_site(db, site)
    return {"status": "completed"}
