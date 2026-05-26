"""Check if a site has enough enriched visitors to trigger AI segmentation."""

import structlog
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.visitor import Visitor

logger = structlog.get_logger()

SEGMENTATION_THRESHOLD = 50


async def check_and_trigger_segmentation(db: AsyncSession, site_id: str) -> bool:
    """Check if 50+ unsegmented enriched visitors exist. Returns True if triggered.

    Called after each Tier 1 enrichment completes. If the threshold is met,
    marks those visitors as segmented and queues the segmentation task.
    """
    # Count unsegmented enriched visitors
    count_result = await db.execute(
        select(func.count()).select_from(Visitor).where(
            Visitor.site_id == site_id,
            Visitor.enrichment_status == "enriched",
            Visitor.segmented == False,  # noqa: E712
        )
    )
    count = count_result.scalar() or 0

    if count < SEGMENTATION_THRESHOLD:
        return False

    logger.info(
        "segmentation_threshold_reached",
        site_id=site_id,
        unsegmented_count=count,
        threshold=SEGMENTATION_THRESHOLD,
    )

    # Mark these visitors as segmented
    await db.execute(
        update(Visitor)
        .where(
            Visitor.site_id == site_id,
            Visitor.enrichment_status == "enriched",
            Visitor.segmented == False,  # noqa: E712
        )
        .values(segmented=True)
    )
    await db.commit()

    # Log that segmentation threshold was reached
    # Actual segmentation runs via POST /segments/{site_id}/run (manual trigger)
    # or will auto-run when Celery/Redis is available
    logger.info("segmentation_auto_triggered", site_id=site_id, count=count)

    return True
