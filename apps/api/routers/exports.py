from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.database import get_db
from apps.api.models.segment import Segment
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.dependencies import get_current_user
from apps.api.services.csv_exporter import export_google_csv, export_linkedin_csv, export_meta_csv

router = APIRouter()

PLATFORMS = {
    "meta": export_meta_csv,
    "google": export_google_csv,
    "linkedin": export_linkedin_csv,
}


@router.get("/{site_id}/{segment_id}")
async def export_segment(
    site_id: str,
    segment_id: str,
    platform: str = Query(..., pattern="^(meta|google|linkedin)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    site_result = await db.execute(
        select(Site).where(Site.site_id == site_id, Site.user_id == user.id)
    )
    if not site_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Site not found")

    seg_result = await db.execute(
        select(Segment).where(Segment.id == segment_id, Segment.site_id == site_id)
    )
    if not seg_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Segment not found")

    exporter = PLATFORMS[platform]
    csv_content = await exporter(db, segment_id)

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={platform}_audience_{segment_id[:8]}.csv"
        },
    )
