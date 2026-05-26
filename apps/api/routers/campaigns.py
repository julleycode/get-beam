from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.campaign import Campaign
from apps.api.models.database import get_db
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.dependencies import get_current_user
from apps.api.schemas.campaigns import CampaignListResponse, CampaignOut, CampaignStatusUpdate

router = APIRouter()

VALID_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["approved"],
    "approved": ["active", "draft"],
    "active": ["paused", "completed"],
    "paused": ["active", "completed"],
}


@router.get("/{site_id}", response_model=CampaignListResponse)
async def list_campaigns(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignListResponse:
    site_result = await db.execute(
        select(Site).where(Site.site_id == site_id, Site.user_id == user.id)
    )
    if not site_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Site not found")

    result = await db.execute(
        select(Campaign).where(Campaign.site_id == site_id).order_by(Campaign.created_at.desc())
    )
    campaigns = [CampaignOut.model_validate(c) for c in result.scalars().all()]
    return CampaignListResponse(campaigns=campaigns, total=len(campaigns))


@router.get("/{site_id}/{campaign_id}", response_model=CampaignOut)
async def get_campaign(
    site_id: str,
    campaign_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignOut:
    site_result = await db.execute(
        select(Site).where(Site.site_id == site_id, Site.user_id == user.id)
    )
    if not site_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Site not found")

    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return CampaignOut.model_validate(campaign)


@router.patch("/{site_id}/{campaign_id}/status", response_model=CampaignOut)
async def update_campaign_status(
    site_id: str,
    campaign_id: str,
    body: CampaignStatusUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignOut:
    site_result = await db.execute(
        select(Site).where(Site.site_id == site_id, Site.user_id == user.id)
    )
    if not site_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Site not found")

    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    allowed = VALID_TRANSITIONS.get(campaign.status, [])
    if body.status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from '{campaign.status}' to '{body.status}'",
        )

    campaign.status = body.status
    if body.status == "approved":
        campaign.approved_at = datetime.now(timezone.utc)
    elif body.status == "active":
        campaign.started_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(campaign)
    return CampaignOut.model_validate(campaign)
