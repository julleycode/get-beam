from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.campaign import Campaign
from apps.api.models.database import get_db
from apps.api.models.segment import Segment, SegmentMember
from apps.api.models.site import Site
from apps.api.models.social_account import SocialAccount
from apps.api.models.user import User
from apps.api.models.visitor import Visitor
from apps.api.dependencies import get_current_user
from apps.api.schemas.campaigns import CampaignListResponse, CampaignOut, CampaignStatusUpdate
from apps.api.agents.campaign_planner import plan_campaign

router = APIRouter()
logger = structlog.get_logger()

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


@router.post("/{site_id}/create/{segment_id}", response_model=CampaignOut)
async def create_campaign_from_segment(
    site_id: str,
    segment_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignOut:
    """Create a campaign plan from a segment using AI.

    Pulls enriched visitor profiles from the segment, checks for connected
    social accounts, and generates a multi-channel campaign plan that includes
    social outreach for visitors with known social handles.
    """
    site_result = await db.execute(
        select(Site).where(Site.site_id == site_id, Site.user_id == user.id)
    )
    if not site_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Site not found")

    seg_result = await db.execute(
        select(Segment).where(Segment.id == segment_id, Segment.site_id == site_id)
    )
    segment = seg_result.scalar_one_or_none()
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    # Get visitor profiles in this segment
    members_result = await db.execute(
        select(SegmentMember.visitor_id).where(SegmentMember.segment_id == segment.id)
    )
    visitor_ids = [row[0] for row in members_result.all()]

    profiles: list[dict] = []
    if visitor_ids:
        visitors_result = await db.execute(
            select(Visitor).where(Visitor.visitor_id.in_(visitor_ids))
        )
        for v in visitors_result.scalars().all():
            profiles.append({
                "visitor_id": v.visitor_id,
                "email": v.email,
                "full_name": v.full_name,
                "job_title": v.job_title,
                "company_name": v.company_name,
                "industry": v.industry,
                "linkedin_url": v.linkedin_url,
                "twitter_handle": v.twitter_handle,
                "intent_score": v.intent_score,
            })

    # Get connected social accounts for this user
    accts_result = await db.execute(
        select(SocialAccount).where(
            SocialAccount.user_id == user.id,
            SocialAccount.is_active.is_(True),
        )
    )
    connected = [
        {"platform": a.platform.value, "username": a.username}
        for a in accts_result.scalars().all()
    ]

    campaign = await plan_campaign(
        db=db,
        segment=segment,
        visitor_profiles=profiles,
        connected_accounts=connected,
    )

    logger.info(
        "campaign_created",
        campaign_id=str(campaign.id),
        segment_id=segment_id,
        has_social_channels=any(
            tp.get("channel") in ("social_reply", "social_dm")
            for tp in campaign.plan.get("touchpoints", [])
        ),
    )
    return CampaignOut.model_validate(campaign)


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

    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.site_id == site_id)
    )
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

    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.site_id == site_id)
    )
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
