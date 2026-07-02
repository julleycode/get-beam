import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.database import get_db
from apps.api.models.campaign import Campaign
from apps.api.models.segment import Segment
from apps.api.models.user import User
from apps.api.models.visitor import Visitor
from apps.api.dependencies import get_current_user, verify_site_access
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
    await verify_site_access(db, site_id, user)

    result = await db.execute(
        select(Segment).where(Segment.site_id == site_id).order_by(Segment.created_at.desc())
    )
    segments = [SegmentOut.model_validate(s) for s in result.scalars().all()]

    return SegmentListResponse(segments=segments, total=len(segments))


@router.delete("/{site_id}/{segment_id}", status_code=204)
async def delete_segment(
    site_id: str,
    segment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a segment. Members are removed via FK cascade; campaigns that
    were generated from it are kept but unlinked (segment_id -> NULL)."""
    await verify_site_access(db, site_id, user)

    result = await db.execute(
        select(Segment).where(Segment.id == segment_id, Segment.site_id == site_id)
    )
    segment = result.scalar_one_or_none()
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment not found")

    await db.execute(
        update(Campaign)
        .where(Campaign.segment_id == segment_id)
        .values(segment_id=None)
    )
    await db.delete(segment)
    await db.commit()
    logger.info("segment_deleted", site_id=site_id, segment_id=str(segment_id))


@router.post("/{site_id}/run")
async def trigger_segmentation(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    site = await verify_site_access(db, site_id, user)

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
    try:
        segments = await run_segmentation(
            db=db,
            site_id=site_id,
            site_name=site.name,
            site_description=site.description or "",
            site_category=site.category or "",
            visitors=visitors,
        )
    except Exception:
        logger.exception("segmentation_failed", site_id=site_id)
        raise HTTPException(
            status_code=502,
            detail="Segmentation failed — the AI service returned an error. Please try again.",
        )

    logger.info("segmentation_triggered", site_id=site_id, segments=len(segments))
    return {
        "status": "completed",
        "segments_created": len(segments),
        "visitors_analyzed": len(visitors),
    }
