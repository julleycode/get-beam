"""Engagement attribution router — track Beam flywheel ROI."""

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_user
from apps.api.models.database import get_db
from apps.api.models.user import User
from apps.api.services.engagement_tracker import EngagementTracker
from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter()


class TrackEngagementRequest(BaseModel):
    platform: str
    engagement_type: str = "comment"
    post_url: Optional[str] = None
    draft_id: Optional[uuid.UUID] = None
    site_id: str


class TrackEngagementResponse(BaseModel):
    utm_tag: str


class EngagementROIResponse(BaseModel):
    total_engagements: int
    new_visitors_attributed: int
    identified_from_engagement: int
    period_days: int


@router.get("/roi", response_model=EngagementROIResponse)
async def get_engagement_roi(
    days: int = Query(30, ge=1, le=365, description="Look-back period in days"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EngagementROIResponse:
    """Return engagement ROI stats for the authenticated user."""
    tracker = EngagementTracker(db)
    stats = await tracker.get_engagement_roi(user.id, days=days)
    return EngagementROIResponse(**stats)


@router.post("/track", response_model=TrackEngagementResponse)
async def track_engagement(
    body: TrackEngagementRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrackEngagementResponse:
    """Record an engagement event and return a UTM tag for attribution tracking."""
    tracker = EngagementTracker(db)
    utm_tag = await tracker.record_engagement(
        user_id=user.id,
        site_id=body.site_id,
        platform=body.platform,
        engagement_type=body.engagement_type,
        post_url=body.post_url,
        draft_id=body.draft_id,
    )
    return TrackEngagementResponse(utm_tag=utm_tag)
