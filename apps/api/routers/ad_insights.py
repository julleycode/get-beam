"""Ad insights -> SEO/AEO content opportunities (ad-insights-seo-aeo_27-11-26).

All routes under /api/v1/ad-insights, scoped to a site owned by the caller
(404 for unknown/foreign ids — never 403). Flag ``ad_insights_enabled`` OFF =>
every route 404s. Suggestions only: the PATCH route changes ``status`` and
nothing else; there is no write path to AgentProfile / llms.txt.
"""

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.dependencies import get_current_user, verify_site_access
from apps.api.models.content_opportunity import ContentOpportunity
from apps.api.models.database import async_session, get_db
from apps.api.models.user import User
from apps.api.schemas.ad_insights import (
    ContentOpportunityOut,
    OpportunityStatusIn,
    RefreshResponse,
    TopAdOut,
    TopAdsResponse,
)

logger = structlog.get_logger()
router = APIRouter()

_REFRESH_TTL_S = 86400


def _require_enabled() -> None:
    if not settings.ad_insights_enabled:
        raise HTTPException(status_code=404, detail="Not found")


def _out(row: ContentOpportunity) -> ContentOpportunityOut:
    return ContentOpportunityOut(
        id=str(row.id),
        kind=row.kind,
        title=row.title,
        body=row.body or "",
        rationale=row.rationale,
        source_ad_ids=[str(x) for x in (row.source_ad_ids or [])],
        signals=row.signals or {},
        status=row.status,
        generated_on=row.generated_on,
        created_at=row.created_at,
    )


@router.get("/{site_id}/top-ads", response_model=TopAdsResponse)
async def top_ads(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TopAdsResponse:
    _require_enabled()
    await verify_site_access(db, site_id, user)
    from apps.api.services.content_opportunities import top_ads_for_site

    ads = await top_ads_for_site(db, site_id)
    return TopAdsResponse(
        min_impressions=settings.ad_insights_min_impressions,
        min_qualifying_ads=settings.ad_insights_min_qualifying_ads,
        enough_data=len(ads) >= settings.ad_insights_min_qualifying_ads,
        ads=[
            TopAdOut(
                rank=a.rank, platform_ad_id=a.platform_ad_id, provider=a.provider,
                headline=a.headline, landing_url=a.landing_url, campaign_name=a.campaign_name,
                impressions=a.impressions, clicks=a.clicks, conversions=round(a.conversions, 2),
                ctr=round(a.ctr, 4), conv_rate=round(a.conv_rate, 4), angles=a.angles,
            )
            for a in ads
        ],
    )


@router.get("/{site_id}/opportunities", response_model=list[ContentOpportunityOut])
async def list_opportunities(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ContentOpportunityOut]:
    _require_enabled()
    await verify_site_access(db, site_id, user)
    rows = (
        await db.execute(
            select(ContentOpportunity)
            .where(ContentOpportunity.site_id == site_id, ContentOpportunity.status != "dismissed")
            .order_by(ContentOpportunity.generated_on.desc(), ContentOpportunity.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    return [_out(r) for r in rows]


@router.patch("/{site_id}/opportunities/{opportunity_id}", response_model=ContentOpportunityOut)
async def update_opportunity_status(
    site_id: str,
    opportunity_id: str,
    body: OpportunityStatusIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContentOpportunityOut:
    _require_enabled()
    await verify_site_access(db, site_id, user)
    try:
        oid = uuid.UUID(opportunity_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")
    row = (
        await db.execute(
            select(ContentOpportunity).where(
                ContentOpportunity.id == oid, ContentOpportunity.site_id == site_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    row.status = body.status
    await db.commit()
    await db.refresh(row)
    return _out(row)


async def _refresh_site(site_id: str) -> None:
    """Background work with a fresh session (request session is closed by now)."""
    from apps.api.services.ad_insights_ingest import ingest_site
    from apps.api.services.content_opportunities import generate_for_site

    try:
        async with async_session() as db:
            await ingest_site(db, site_id)
            await generate_for_site(db, site_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ad_insights_refresh_failed", site_id=site_id, error=type(exc).__name__)


@router.post("/{site_id}/refresh", response_model=RefreshResponse, status_code=202)
async def refresh(
    site_id: str,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RefreshResponse:
    """1 attempt per site per day (AC-10). The Redis marker is taken BEFORE any
    work and is NOT released on failure, so a failed generation still consumes
    the day's attempt. Redis errors fail CLOSED (429) — E10."""
    _require_enabled()
    await verify_site_access(db, site_id, user)
    from apps.api.services.content_opportunities import generated_today
    from apps.api.services.redis_client import get_redis

    today = datetime.now(timezone.utc).date()
    if await generated_today(db, site_id, today):
        raise HTTPException(status_code=429, detail="Suggestions already generated today")
    try:
        took = await get_redis().set(f"ad_insights:refresh:{site_id}", "1", nx=True, ex=_REFRESH_TTL_S)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ad_insights_refresh_marker_error", site_id=site_id, error=type(exc).__name__)
        raise HTTPException(status_code=429, detail="Refresh unavailable, try again later")
    if not took:
        raise HTTPException(status_code=429, detail="Refresh already used today")
    background.add_task(_refresh_site, site_id)
    return RefreshResponse(scheduled=True)
