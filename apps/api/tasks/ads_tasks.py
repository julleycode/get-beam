"""Celery task: push a segment to an ad platform out-of-band.

Only used when settings.ads_async_push is on AND a Celery worker is running.
The push service falls back to a synchronous push otherwise, so this never
silently swallows a push on a worker-less deploy. Mirrors tasks/crm_tasks.py.
"""

import asyncio

import structlog

from apps.api.models.database import async_session
from apps.api.services.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(name="apps.api.tasks.ads_tasks.push_segment_to_ads")
def push_segment_to_ads_task(site_id: str, provider: str, segment_id: str) -> dict:
    # asyncio.run (fresh loop per task) — reusing the worker loop breaks asyncpg.
    return asyncio.run(_run(site_id, provider, segment_id))


async def _run(site_id: str, provider: str, segment_id: str) -> dict:
    # Imported here (not at module scope) so the task module and ads_push can
    # reference each other without a circular import at startup.
    from apps.api.services.ads_push import push_segment_to_ads

    async with async_session() as db:
        outcome = await push_segment_to_ads(db, site_id, provider, segment_id)
    logger.info(
        "ads_async_push_done",
        site_id=site_id,
        provider=provider,
        segment_id=segment_id,
        found=outcome.found,
        pushed=outcome.pushed,
        failed=outcome.failed,
    )
    return {
        "found": outcome.found,
        "pushed": outcome.pushed,
        "failed": outcome.failed,
        "skipped": outcome.skipped,
    }
