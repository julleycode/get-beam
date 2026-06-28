"""Celery task: push a segment to a CRM out-of-band.

Only used when settings.crm_async_push is on AND a Celery worker is running.
The router falls back to a synchronous push otherwise, so this never silently
swallows a push on a worker-less deploy.
"""

import asyncio

import structlog

from apps.api.models.database import async_session
from apps.api.services.celery_app import celery_app
from apps.api.services.crm_push import push_segment

logger = structlog.get_logger()


@celery_app.task(name="apps.api.tasks.crm_tasks.push_segment_to_crm")
def push_segment_to_crm(site_id: str, provider: str, segment_id: str) -> dict:
    # asyncio.run (fresh loop per task) — reusing the worker loop breaks asyncpg.
    return asyncio.run(_run(site_id, provider, segment_id))


async def _run(site_id: str, provider: str, segment_id: str) -> dict:
    async with async_session() as db:
        outcome = await push_segment(db, site_id, provider, segment_id)
    logger.info(
        "crm_async_push_done",
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
