import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.api_key import UserApiKey
from apps.api.models.database import get_db
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.routers.auth import get_current_user
from apps.api.schemas.visitors import VisitorDetailOut, VisitorListResponse, VisitorOut
from apps.api.services.enricher import Enricher
from apps.api.services.identity_resolver import IdentityResolver

logger = structlog.get_logger()

router = APIRouter()


async def _verify_site_access(db: AsyncSession, site_id: str, user: User) -> Site:
    result = await db.execute(
        select(Site).where(Site.site_id == site_id, Site.user_id == user.id)
    )
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


@router.get("/{site_id}", response_model=VisitorListResponse)
async def list_visitors(
    site_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    identity_status: str | None = None,
    min_intent: float | None = None,
    sort_by: str = "intent_score",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VisitorListResponse:
    await _verify_site_access(db, site_id, user)

    query = select(Visitor).where(Visitor.site_id == site_id)
    count_query = select(func.count()).select_from(Visitor).where(Visitor.site_id == site_id)

    if identity_status:
        query = query.where(Visitor.identity_status == identity_status)
        count_query = count_query.where(Visitor.identity_status == identity_status)
    if min_intent is not None:
        query = query.where(Visitor.intent_score >= min_intent)
        count_query = count_query.where(Visitor.intent_score >= min_intent)

    sort_col = {
        "intent_score": Visitor.intent_score.desc(),
        "last_seen": Visitor.last_seen.desc(),
        "pageviews": Visitor.total_pageviews.desc(),
    }.get(sort_by, Visitor.intent_score.desc())

    query = query.order_by(sort_col).offset((page - 1) * page_size).limit(page_size)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    result = await db.execute(query)
    visitors = [VisitorOut.model_validate(v) for v in result.scalars().all()]

    return VisitorListResponse(visitors=visitors, total=total, page=page, page_size=page_size)


@router.get("/{site_id}/stats")
async def get_visitor_stats(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get enrichment and identity stats for a site."""
    await _verify_site_access(db, site_id, user)

    # Total visitors
    total_r = await db.execute(
        select(func.count()).select_from(Visitor).where(Visitor.site_id == site_id)
    )
    total = total_r.scalar() or 0

    # Identified visitors
    identified_r = await db.execute(
        select(func.count()).select_from(Visitor).where(
            Visitor.site_id == site_id,
            Visitor.identity_status == "identified",
        )
    )
    identified = identified_r.scalar() or 0

    # Enriched visitors (Tier 1+)
    enriched_r = await db.execute(
        select(func.count()).select_from(Visitor).where(
            Visitor.site_id == site_id,
            Visitor.enrichment_status == "enriched",
        )
    )
    enriched = enriched_r.scalar() or 0

    # Could be enriched further (identified but low completeness)
    partial_r = await db.execute(
        select(func.count()).select_from(EnrichmentProfile).where(
            EnrichmentProfile.site_id == site_id,
            EnrichmentProfile.enrichment_completeness < 0.6,
        )
    )
    could_enrich_more = partial_r.scalar() or 0

    return {
        "total_visitors": total,
        "identified": identified,
        "enriched": enriched,
        "could_enrich_more": could_enrich_more,
    }


@router.get("/{site_id}/{visitor_id}", response_model=VisitorDetailOut)
async def get_visitor_detail(
    site_id: str,
    visitor_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VisitorDetailOut:
    await _verify_site_access(db, site_id, user)

    result = await db.execute(
        select(Visitor).where(Visitor.site_id == site_id, Visitor.visitor_id == visitor_id)
    )
    visitor = result.scalar_one_or_none()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")

    data = VisitorOut.model_validate(visitor).model_dump()

    id_result = await db.execute(
        select(IdentifiedVisitor).where(
            IdentifiedVisitor.site_id == site_id,
            IdentifiedVisitor.visitor_id == visitor_id,
        )
    )
    identified = id_result.scalar_one_or_none()
    if identified:
        data.update({
            "email": identified.email,
            "full_name": identified.full_name,
            "phone": identified.phone,
            "city": identified.city,
            "region": identified.region,
            "country": identified.country,
        })

    enrich_result = await db.execute(
        select(EnrichmentProfile).where(
            EnrichmentProfile.site_id == site_id,
            EnrichmentProfile.visitor_id == visitor_id,
        )
    )
    enriched = enrich_result.scalar_one_or_none()
    if enriched:
        data.update({
            "job_title": enriched.job_title,
            "company_name": enriched.company_name,
            "industry": enriched.industry,
            "linkedin_url": enriched.linkedin_url,
            "twitter_handle": enriched.twitter_handle,
            "linkedin_headline": enriched.linkedin_headline,
            "twitter_bio": enriched.twitter_bio,
            "enrichment_completeness": enriched.enrichment_completeness,
        })

    return VisitorDetailOut(**data)


@router.post("/{site_id}/{visitor_id}/enrich")
async def enrich_visitor(
    site_id: str,
    visitor_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger Tier 2 (BYOK) enrichment for a specific visitor."""
    await _verify_site_access(db, site_id, user)

    # Check visitor exists
    result = await db.execute(
        select(Visitor).where(Visitor.site_id == site_id, Visitor.visitor_id == visitor_id)
    )
    visitor = result.scalar_one_or_none()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")

    # Check user has BYOK keys
    key_result = await db.execute(
        select(UserApiKey).where(
            UserApiKey.user_id == user.id,
            UserApiKey.is_valid == True,  # noqa: E712
        )
    )
    user_keys = list(key_result.scalars().all())
    if not user_keys:
        return {
            "status": "no_keys",
            "message": "Add your Proxycurl or Twitter API key in Settings to unlock full profiles.",
        }

    # Run Tier 2 enrichment
    enricher = Enricher(db)
    profile = await enricher.enrich_tier2(visitor, str(user.id))

    if profile:
        return {
            "status": "enriched",
            "completeness": profile.enrichment_completeness,
            "message": "Profile enriched with additional data.",
        }
    else:
        return {
            "status": "partial",
            "message": "Could not enrich further. Ensure Tier 1 enrichment has run first.",
        }


@router.post("/{site_id}/resolve")
async def resolve_site_visitors(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger identity resolution + Tier 1 enrichment for all eligible visitors."""
    await _verify_site_access(db, site_id, user)

    # Find anonymous visitors with intent >= 40
    result = await db.execute(
        select(Visitor).where(
            Visitor.site_id == site_id,
            Visitor.identity_status == "anonymous",
            Visitor.intent_score >= 40,
        ).order_by(Visitor.intent_score.desc()).limit(50)
    )
    visitors = list(result.scalars().all())

    if not visitors:
        return {"status": "no_eligible", "message": "No visitors with intent >= 40 to resolve."}

    resolver = IdentityResolver(db)
    enricher = Enricher(db)
    resolved = 0
    enriched = 0

    for visitor in visitors:
        try:
            identified = await resolver.resolve(visitor)
            if identified:
                resolved += 1
                profile = await enricher.enrich_tier1(visitor, identified)
                if profile:
                    enriched += 1
        except Exception as e:
            logger.warning("resolve_visitor_error", visitor_id=visitor.visitor_id, error=str(e))

    return {
        "status": "completed",
        "processed": len(visitors),
        "resolved": resolved,
        "enriched": enriched,
    }
