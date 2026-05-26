import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.database import get_db
from apps.api.models.segment import Segment
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.models.visitor import Visitor
from apps.api.dependencies import get_current_user
from apps.api.schemas.segments import SegmentListResponse, SegmentOut
from apps.api.agents.segmenter import run_segmentation

router = APIRouter()
logger = structlog.get_logger()


@router.get("/{site_id}", response_model=SegmentListResponse)
async def list_segments(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SegmentListResponse:
    site_result = await db.execute(
        select(Site).where(Site.site_id == site_id, Site.user_id == user.id)
    )
    if not site_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Site not found")

    result = await db.execute(
        select(Segment).where(Segment.site_id == site_id).order_by(Segment.created_at.desc())
    )
    segments = [SegmentOut.model_validate(s) for s in result.scalars().all()]

    return SegmentListResponse(segments=segments, total=len(segments))


@router.post("/{site_id}/run")
async def trigger_segmentation(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    site_result = await db.execute(
        select(Site).where(Site.site_id == site_id, Site.user_id == user.id)
    )
    site = site_result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # Get enriched visitors for segmentation
    result = await db.execute(
        select(Visitor).where(
            Visitor.site_id == site_id,
            Visitor.enrichment_status == "enriched",
        ).order_by(Visitor.intent_score.desc()).limit(50)
    )
    visitors = list(result.scalars().all())

    if len(visitors) < 3:
        return {"status": "not_enough", "message": f"Need at least 3 enriched visitors, have {len(visitors)}"}

    # Run segmentation synchronously (no Celery/Redis needed for MVP)
    segments = await run_segmentation(
        db=db,
        site_id=site_id,
        site_name=site.name,
        site_description=site.description or "",
        site_category=site.category or "",
        visitors=visitors,
    )

    logger.info("segmentation_triggered", site_id=site_id, segments=len(segments))
    return {
        "status": "completed",
        "segments_created": len(segments),
        "visitors_analyzed": len(visitors),
    }
