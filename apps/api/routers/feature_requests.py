"""Feature requests — public submit from the landing page FAB + owner-only listing."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_user
from apps.api.models.database import get_db
from apps.api.models.feature_request import FeatureRequest
from apps.api.models.user import User
from apps.api.schemas.feature_requests import (
    FeatureRequestCreate,
    FeatureRequestListResponse,
    FeatureRequestOut,
)

logger = structlog.get_logger()

router = APIRouter(tags=["feature-requests"])

_ALLOWED_URGENCY = {"nice", "useful", "critical"}


@router.post("", response_model=FeatureRequestOut, status_code=201)
async def create_feature_request(
    body: FeatureRequestCreate,
    db: AsyncSession = Depends(get_db),
) -> FeatureRequestOut:
    """Public endpoint — anyone on the landing page can submit a feature request."""
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title is required.")

    urgency = body.urgency if body.urgency in _ALLOWED_URGENCY else None
    email = (body.email or "").strip() or None

    req = FeatureRequest(
        id=uuid.uuid4(),
        title=title[:120],
        detail=(body.detail or "").strip() or None,
        urgency=urgency,
        email=email,
        source="landing_fab",
        status="new",
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    logger.info("feature_request_created", id=str(req.id), urgency=urgency, has_email=bool(email))
    return FeatureRequestOut.model_validate(req)


@router.get("", response_model=FeatureRequestListResponse)
async def list_feature_requests(
    status: str | None = Query(None, description="Filter by status: new / planned / shipped / closed"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeatureRequestListResponse:
    """Owner-only — view submitted feature requests (auth required)."""
    query = select(FeatureRequest)
    count_query = select(func.count()).select_from(FeatureRequest)
    if status:
        query = query.where(FeatureRequest.status == status)
        count_query = count_query.where(FeatureRequest.status == status)

    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(desc(FeatureRequest.created_at)).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).scalars().all()

    return FeatureRequestListResponse(
        requests=[FeatureRequestOut.model_validate(r) for r in rows],
        total=total,
    )
