from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.database import get_db
from apps.api.models.segment import Segment
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.routers.auth import get_current_user
from apps.api.schemas.segments import SegmentListResponse, SegmentOut
from apps.api.tasks.segmentation_tasks import run_segmentation_manual

router = APIRouter()


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
    if not site_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Site not found")

    run_segmentation_manual.delay(site_id)
    return {"status": "segmentation_triggered"}
