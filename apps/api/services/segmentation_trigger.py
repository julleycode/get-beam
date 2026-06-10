"""Auto-segmentation trigger — runs AI segmentation when enough NEW enriched
visitors accumulate.

Called from the live resolution path after Tier-1 enrichment (and from the
Celery resolution task when a worker is deployed). When THRESHOLD+ unsegmented
enriched visitors exist for a site, this runs segmentation + campaign planning
inline; `_run_segmentation_for_site` marks the processed visitors segmented
after success, so the next trigger only counts genuinely new ones. A short
Redis lock prevents two concurrent resolution jobs from double-firing (and
double-billing the Claude calls).

This used to use threshold 50 and mark visitors segmented WITHOUT running
segmentation — consuming the "new" flag with no effect. The documented rule
(CLAUDE.md) is: segmentation triggers at 10+ new enriched visitors.
"""

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.site import Site
from apps.api.models.visitor import Visitor
from apps.api.services.redis_client import get_redis

logger = structlog.get_logger()

SEGMENTATION_THRESHOLD = 10
_LOCK_TTL_SECONDS = 600


async def _acquire_lock(site_id: str) -> bool:
    try:
        return bool(
            await get_redis().set(
                f"seg_lock:{site_id}", "1", nx=True, ex=_LOCK_TTL_SECONDS
            )
        )
    except Exception as exc:
        # Redis down: proceed without the lock — worst case is one duplicate
        # segmentation run; skipping would silently disable the documented
        # auto-segmentation behavior.
        logger.warning(
            "segmentation_lock_unavailable", site_id=site_id, error=str(exc)
        )
        return True


async def _release_lock(site_id: str) -> None:
    try:
        await get_redis().delete(f"seg_lock:{site_id}")
    except Exception:
        pass


async def check_and_trigger_segmentation(db: AsyncSession, site_id: str) -> bool:
    """Run segmentation when THRESHOLD+ new enriched visitors exist.

    Returns True when a segmentation run was performed.
    """
    count_result = await db.execute(
        select(func.count())
        .select_from(Visitor)
        .where(
            Visitor.site_id == site_id,
            Visitor.enrichment_status == "enriched",
            Visitor.segmented == False,  # noqa: E712
        )
    )
    count = count_result.scalar() or 0
    if count < SEGMENTATION_THRESHOLD:
        return False

    if not await _acquire_lock(site_id):
        logger.info("segmentation_already_running", site_id=site_id)
        return False

    try:
        site_result = await db.execute(select(Site).where(Site.site_id == site_id))
        site = site_result.scalar_one_or_none()
        if site is None:
            logger.warning("segmentation_trigger_site_missing", site_id=site_id)
            return False

        logger.info(
            "segmentation_auto_triggered", site_id=site_id, new_enriched=count
        )
        # Lazy import: pulls in the Celery app + AI agents, which callers on
        # the hot resolution path never need until the threshold is met.
        from apps.api.tasks.segmentation_tasks import _run_segmentation_for_site

        await _run_segmentation_for_site(db, site)
        return True
    finally:
        await _release_lock(site_id)
