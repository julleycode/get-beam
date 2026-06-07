import uuid

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.database import async_session, get_db
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.dependencies import get_current_user
from apps.api.schemas.visitors import ManualIdentifyRequest, VisitorDetailOut, VisitorListResponse, VisitorOut
from apps.api.services.enricher import Enricher
from apps.api.services.identity_resolver import IdentityResolver
from apps.api.services.usage_limits import check_enrich_budget, check_identify_budget

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


@router.delete("/{site_id}/{visitor_id}/data")
async def delete_visitor_data(
    site_id: str,
    visitor_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Erase ALL data for a single visitor (GDPR / deletion-request compliance).

    Removes the visitor row plus identity, enrichment, events, and resolution
    logs. Site-ownership is enforced so one tenant can't delete another's data.
    """
    from sqlalchemy import text as sql_text

    await _verify_site_access(db, site_id, user)

    deleted: dict[str, int] = {}
    for table in (
        "resolution_logs",
        "identified_visitors",
        "enrichment_profiles",
        "events",
        "segment_members",
        "visitors",
    ):
        try:
            r = await db.execute(
                sql_text(f"DELETE FROM {table} WHERE site_id = :sid AND visitor_id = :vid"),
                {"sid": site_id, "vid": visitor_id},
            )
            deleted[table] = r.rowcount
        except Exception as e:
            logger.warning("visitor_data_delete_partial", table=table, error=str(e))
    await db.commit()

    logger.info("visitor_data_deleted", site_id=site_id, visitor_id=visitor_id[:8], deleted=deleted)
    return {"status": "deleted", "visitor_id": visitor_id, "deleted": deleted}


@router.delete("/{site_id}/cleanup-test")
async def cleanup_test_visitors(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete test/debug visitors and their events from a site."""
    from sqlalchemy import or_
    from apps.api.models.event import Event

    await _verify_site_access(db, site_id, user)

    test_patterns = [
        "test%", "pg-%", "chrome-test-%", "auto-agg-%",
        "mobile-test-%", "real-browser-%", "test-tz-%", "bounce-visitor-%",
    ]

    pattern_conditions = [Visitor.visitor_id.like(p) for p in test_patterns]

    # Get visitor_ids to delete their events too
    vid_result = await db.execute(
        select(Visitor.visitor_id).where(
            Visitor.site_id == site_id,
            or_(*pattern_conditions),
        )
    )
    test_vids = [row[0] for row in vid_result.all()]

    if not test_vids:
        return {"status": "clean", "visitors_deleted": 0, "events_deleted": 0}

    # Delete events for these visitors
    event_del = await db.execute(
        Event.__table__.delete().where(
            Event.site_id == site_id,
            Event.visitor_id.in_(test_vids),
        )
    )
    events_deleted = event_del.rowcount

    # Delete the visitors
    visitor_del = await db.execute(
        Visitor.__table__.delete().where(
            Visitor.site_id == site_id,
            or_(*pattern_conditions),
        )
    )
    visitors_deleted = visitor_del.rowcount

    await db.commit()

    logger.info(
        "test_data_cleaned",
        site_id=site_id,
        visitors_deleted=visitors_deleted,
        events_deleted=events_deleted,
    )

    return {
        "status": "cleaned",
        "visitors_deleted": visitors_deleted,
        "events_deleted": events_deleted,
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
            "resolution_provider": identified.resolution_provider,
            "confidence_score": identified.confidence_score,
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
            "social_context": enriched.social_context,
        })

    # Count auto-generated drafts for this visitor
    from apps.api.models.draft import Draft
    draft_count_result = await db.execute(
        select(func.count()).select_from(Draft).where(
            Draft.visitor_id == visitor_id,
            Draft.auto_generated.is_(True),
        )
    )
    data["auto_draft_count"] = draft_count_result.scalar() or 0

    return VisitorDetailOut(**data)


@router.post("/{site_id}/{visitor_id}/enrich")
async def enrich_visitor(
    site_id: str,
    visitor_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Deep-research enrichment via Claude API with web search.

    Daily cap: 3 enrichments/day (free tier). BYOK all APIs to unlock unlimited.
    """
    await _verify_site_access(db, site_id, user)

    budget = await check_enrich_budget(db, site_id, user.id)
    if not budget["allowed"]:
        return {
            "status": "limit_reached",
            "message": (
                f"Daily enrichment limit reached ({budget['used']}/{budget['limit']}). "
                "Add your own API keys in Settings to unlock unlimited enrichments."
            ),
            "used": budget["used"],
            "limit": budget["limit"],
        }

    result = await db.execute(
        select(Visitor).where(Visitor.site_id == site_id, Visitor.visitor_id == visitor_id)
    )
    visitor = result.scalar_one_or_none()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")

    id_result = await db.execute(
        select(IdentifiedVisitor).where(
            IdentifiedVisitor.site_id == site_id,
            IdentifiedVisitor.visitor_id == visitor_id,
        )
    )
    identified = id_result.scalar_one_or_none()
    if not identified:
        return {
            "status": "not_identified",
            "message": "Visitor must be identified (email/name) before enrichment.",
        }

    enrich_result = await db.execute(
        select(EnrichmentProfile).where(
            EnrichmentProfile.site_id == site_id,
            EnrichmentProfile.visitor_id == visitor_id,
        )
    )
    profile = enrich_result.scalar_one_or_none()

    enricher = Enricher(db)
    return await enricher.deep_research(visitor, identified, profile)


@router.post("/{site_id}/{visitor_id}/identify")
async def manual_identify_visitor(
    site_id: str,
    visitor_id: str,
    body: ManualIdentifyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually identify a visitor — for residential IPs or site-owner self-identification."""
    await _verify_site_access(db, site_id, user)

    result = await db.execute(
        select(Visitor).where(Visitor.site_id == site_id, Visitor.visitor_id == visitor_id)
    )
    visitor = result.scalar_one_or_none()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")

    # Upsert identified visitor
    existing = await db.execute(
        select(IdentifiedVisitor).where(
            IdentifiedVisitor.site_id == site_id,
            IdentifiedVisitor.visitor_id == visitor_id,
        )
    )
    identified = existing.scalar_one_or_none()
    if identified:
        identified.email = body.email
        if body.full_name:
            identified.full_name = body.full_name
        identified.resolution_provider = "manual"
        identified.confidence_score = 1.0
    else:
        identified = IdentifiedVisitor(
            visitor_id=visitor_id,
            site_id=site_id,
            email=body.email,
            full_name=body.full_name,
            resolution_provider="manual",
            confidence_score=1.0,
        )
        db.add(identified)

    visitor.identity_status = "identified"
    await db.commit()

    # Also create/update enrichment profile if company info provided
    if body.company_name or body.job_title:
        from apps.api.models.enrichment import EnrichmentProfile

        ep_result = await db.execute(
            select(EnrichmentProfile).where(
                EnrichmentProfile.site_id == site_id,
                EnrichmentProfile.visitor_id == visitor_id,
            )
        )
        profile = ep_result.scalar_one_or_none()
        if profile:
            if body.company_name:
                profile.company_name = body.company_name
            if body.job_title:
                profile.job_title = body.job_title
        else:
            profile = EnrichmentProfile(
                visitor_id=visitor_id,
                site_id=site_id,
                company_name=body.company_name,
                job_title=body.job_title,
                enrichment_completeness=0.3,
            )
            db.add(profile)
        visitor.enrichment_status = "enriched"
        await db.commit()

    logger.info("visitor_manually_identified", visitor_id=visitor_id[:8], email=body.email[:5] + "***")

    return {
        "status": "identified",
        "visitor_id": visitor_id,
        "email": body.email,
        "full_name": body.full_name,
    }


async def _run_resolution_job(site_id: str, max_resolve: int = 20) -> None:
    """Background worker: resolve + enrich eligible visitors for a site.

    Runs AFTER the HTTP response is sent, in its own DB session (the
    request-scoped session is already closed by the time this runs).
    Each visitor is resolved in isolation so one failure can't abort the batch.
    """
    async with async_session() as db:
        result = await db.execute(
            select(Visitor).where(
                Visitor.site_id == site_id,
                Visitor.identity_status == "anonymous",
                Visitor.intent_score >= 40,
            ).order_by(Visitor.intent_score.desc()).limit(max_resolve)
        )
        visitors = list(result.scalars().all())
        if not visitors:
            return

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

        logger.info(
            "resolution_job_complete",
            site_id=site_id, processed=len(visitors), resolved=resolved, enriched=enriched,
        )


@router.post("/{site_id}/resolve")
async def resolve_site_visitors(
    site_id: str,
    background_tasks: BackgroundTasks,
    reset: bool = Query(False, description="Reset unresolvable visitors back to anonymous for re-processing"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Queue identity resolution + Tier 1 enrichment for eligible visitors.

    Daily cap: 20 identifications/day (free tier). BYOK all APIs to unlock unlimited.
    """
    from sqlalchemy import text as sql_text

    await _verify_site_access(db, site_id, user)

    budget = await check_identify_budget(db, site_id, user.id)
    if not budget["allowed"]:
        return {
            "status": "limit_reached",
            "message": (
                f"Daily identification limit reached ({budget['used']}/{budget['limit']}). "
                "Add your own API keys in Settings to unlock unlimited identifications."
            ),
            "used": budget["used"],
            "limit": budget["limit"],
        }

    if reset:
        await db.execute(
            sql_text(
                "DELETE FROM resolution_logs WHERE site_id = :sid AND visitor_id IN "
                "(SELECT visitor_id FROM visitors WHERE site_id = :sid AND identity_status = 'unresolvable')"
            ),
            {"sid": site_id},
        )
        await db.execute(
            sql_text("UPDATE visitors SET identity_status = 'anonymous' WHERE site_id = :sid AND identity_status = 'unresolvable'"),
            {"sid": site_id},
        )
        await db.commit()

    count_result = await db.execute(
        select(func.count()).select_from(Visitor).where(
            Visitor.site_id == site_id,
            Visitor.identity_status == "anonymous",
            Visitor.intent_score >= 40,
        )
    )
    eligible_raw = count_result.scalar() or 0

    remaining = (budget["limit"] - budget["used"]) if budget["limit"] else eligible_raw
    eligible = min(eligible_raw, remaining)

    if eligible == 0:
        if eligible_raw > 0:
            return {
                "status": "limit_reached",
                "message": (
                    f"Daily limit allows {remaining} more identification(s) today, "
                    f"but {eligible_raw} visitor(s) are eligible. "
                    "Add your own API keys to unlock unlimited."
                ),
                "used": budget["used"],
                "limit": budget["limit"],
            }
        return {"status": "no_eligible", "message": "No visitors with intent >= 40 to resolve."}

    background_tasks.add_task(_run_resolution_job, site_id, eligible)

    return {
        "status": "started",
        "queued": eligible,
        "used_today": budget["used"],
        "daily_limit": budget["limit"],
        "is_byok": budget["is_byok"],
        "message": f"Resolving {eligible} visitor(s) in the background. Refresh in a moment to see results.",
    }


