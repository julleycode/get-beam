import asyncio

import structlog
from sqlalchemy import select

from apps.api.models.database import async_session
from apps.api.models.site import Site
from apps.api.services.celery_app import celery_app
from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

logger = structlog.get_logger()


@celery_app.task(name="apps.api.tasks.aggregation_tasks.aggregate_all_sites")
def aggregate_all_sites() -> dict:
    return asyncio.run(_aggregate_all())


async def _aggregate_all() -> dict:
    async with async_session() as db:
        result = await db.execute(select(Site.site_id))
        site_ids = [row[0] for row in result.all()]

    total = 0
    for site_id in site_ids:
        async with async_session() as db:
            count = await aggregate_visitors_for_site(db, site_id)
            total += count

    logger.info("aggregation_complete", sites=len(site_ids), visitors=total)
    return {"sites": len(site_ids), "visitors_aggregated": total}
