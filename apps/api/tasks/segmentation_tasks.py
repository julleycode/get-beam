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
    # asyncio.run (not get_event_loop().run_until_complete): reusing the
    # worker's loop across tasks breaks asyncpg ("attached to a different
    # loop") after the first task.
    return asyncio.run(_check_triggers())


async def _check_triggers() -> dict:
    async with async_session() as db:
        result = await db.execute(select(Site))
        sites = list(result.scalars().all())

    triggered = 0
    for site in sites:
        async with async_session() as db:
            # Count only NEW (unsegmented) enriched visitors. Counting all
            # enriched visitors made this hourly task re-run segmentation —
            # and re-pay 3-6 Claude calls — forever once a site crossed the
            # threshold, flooding segments/campaigns with duplicates.
            count_result = await db.execute(
                select(func.count()).select_from(Visitor).where(
                    Visitor.site_id == site.site_id,
                    Visitor.enrichment_status == "enriched",
                    Visitor.segmented == False,  # noqa: E712
                )
            )
            new_enriched_count = count_result.scalar() or 0

            if new_enriched_count >= SEGMENTATION_THRESHOLD:
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
    if not visitors:
        return

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

    # Mark the processed visitors segmented in the same session so the next
    # hourly tick doesn't count them as "new" and re-bill the AI calls.
    from sqlalchemy import update

    await db.execute(
        update(Visitor)
        .where(
            Visitor.site_id == site.site_id,
            Visitor.visitor_id.in_([v.visitor_id for v in visitors]),
        )
        .values(segmented=True)
    )
    await db.commit()

    logger.info("segmentation_triggered", site_id=site.site_id, segments=len(segments))

    # Opt-in: auto-sync the freshly built segments to any connected CRM.
    # Best-effort — never let a CRM hiccup break segmentation.
    from apps.api.services.crm_push import auto_push_segments

    await auto_push_segments(db, site.site_id, [str(s.id) for s in segments])


@celery_app.task(name="apps.api.tasks.segmentation_tasks.run_segmentation_manual")
def run_segmentation_manual(site_id: str) -> dict:
    # asyncio.run — see check_segmentation_triggers.
    return asyncio.run(_run_manual(site_id))


async def _run_manual(site_id: str) -> dict:
    async with async_session() as db:
        site_result = await db.execute(select(Site).where(Site.site_id == site_id))
        site = site_result.scalar_one_or_none()
        if not site:
            return {"error": "Site not found"}
        await _run_segmentation_for_site(db, site)
    return {"status": "completed"}
