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


async def _aggregate_all(full_recompute: bool = False) -> dict:
    """Sequential per-site aggregation.

    NOT a live cadence: this Celery task has no consumer (no worker, no beat
    process anywhere in Dockerfile / railway.json / infra/docker-compose.yml), so
    it runs only if invoked explicitly. The live repair cadence is the APScheduler
    `aggregation_sweep` job in `apps/api/jobs/scheduler.py`.

    `full_recompute=True` forces the unbounded repair path regardless of the
    incremental flag — the explicit repair entrypoint (checklist item 8).
    """
    from apps.api.config import settings
    from apps.api.services.visitor_aggregator import get_aggregation_watermark

    async with async_session() as db:
        result = await db.execute(select(Site.site_id))
        site_ids = [row[0] for row in result.all()]

    incremental = settings.aggregation_incremental_enabled and not full_recompute

    total = 0
    for site_id in site_ids:
        async with async_session() as db:
            since = await get_aggregation_watermark(db, site_id) if incremental else None
            count = await aggregate_visitors_for_site(db, site_id, since=since)
            total += count

    logger.info("aggregation_complete", sites=len(site_ids), visitors=total)
    return {"sites": len(site_ids), "visitors_aggregated": total}
