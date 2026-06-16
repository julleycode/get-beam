import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.database import async_session, get_db
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.known_contact import KnownContact
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.models.visitor import IdentifiedVisitor, ResolutionLog, Visitor
from apps.api.dependencies import get_current_user
from apps.api.schemas.visitors import (
    ManualIdentifyRequest,
    VisitorCountryOut,
    VisitorDetailOut,
    VisitorListResponse,
    VisitorOut,
    VisitorStatsResponse,
)
from apps.api.services.billing import check_usage_allowed, increment_usage
from apps.api.services.enricher import Enricher
from apps.api.services.identity_resolver import IdentityResolver
from apps.api.services.resolution_runner import run_resolution_for_site
from apps.api.services.osint_scanner import run_osint_scan
from apps.api.services.known_hash import email_hash
from apps.api.services.social_resolver import resolve_social
from apps.api.services.usage_limits import (
    check_enrich_budget,
    check_identify_budget,
    check_osint_budget,
    check_resolution_attempt_budget,
    increment_osint_usage,
)

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


def _row_to_dict(obj) -> dict:
    """Serialize an ORM row to a plain dict of its columns (DSAR export)."""
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}


async def _known_visitor_ids(db: AsyncSession, site_id: str) -> set[str]:
    """Visitor ids whose identified email matches the site's known-contacts list.

    Matching is hash-vs-hash — the owner's list is stored only as HMAC hashes
    (see models/known_contact.py). We hash the identified emails in Python here
    because the HMAC key lives in the app, not the DB. Loads this site's
    identified emails + known hashes; fine at current scale. If identified rows
    grow large, add an email_hash column to identified_visitors and switch this
    to a SQL join.
    """
    known_hashes = set(
        (
            await db.execute(
                select(KnownContact.email_hash).where(KnownContact.site_id == site_id)
            )
        ).scalars().all()
    )
    if not known_hashes:
        return set()
    id_rows = await db.execute(
        select(IdentifiedVisitor.visitor_id, IdentifiedVisitor.email).where(
            IdentifiedVisitor.site_id == site_id,
            IdentifiedVisitor.email.isnot(None),
        )
    )
    return {vid for vid, em in id_rows if em and email_hash(em) in known_hashes}


@router.get("/{site_id}", response_model=VisitorListResponse)
async def list_visitors(
    site_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    identity_status: str | None = None,
    enrichment_status: str | None = None,
    country: str | None = Query(None, max_length=5),
    visitor_type: str | None = None,  # "new" | "returning" — by session count
    known: bool | None = None,  # match against the owner's known-contacts list
    first_seen_from: datetime | None = None,
    first_seen_to: datetime | None = None,
    last_seen_from: datetime | None = None,
    last_seen_to: datetime | None = None,
    min_intent: float | None = None,
    sort_by: str = "intent_score",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VisitorListResponse:
    await _verify_site_access(db, site_id, user)

    query = select(Visitor).where(Visitor.site_id == site_id)
    count_query = select(func.count()).select_from(Visitor).where(Visitor.site_id == site_id)

    # Build the filter predicates once and apply the same list to both the row
    # query and the count query, so the paginated total always matches the rows.
    # Date bounds: *_to is EXCLUSIVE (< ) — the frontend sends the start of the
    # day AFTER the chosen end date so the whole end day is included. first_seen
    # / last_seen are naive (UTC) timestamps, so bounds are cut on UTC days.
    filters = []
    if identity_status:
        filters.append(Visitor.identity_status == identity_status)
    if enrichment_status:
        filters.append(Visitor.enrichment_status == enrichment_status)
    if country:
        filters.append(Visitor.country_code == country)
    # "new" = seen in a single session; "returning" = came back (2+ sessions).
    # total_sessions is the lifetime session count (gap > 30 min) and is always
    # >= 1, so "new" is effectively == 1. This is Beam's own visit signal, NOT a
    # known-customer/CRM signal (that's a later phase).
    if visitor_type == "new":
        filters.append(Visitor.total_sessions <= 1)
    elif visitor_type == "returning":
        filters.append(Visitor.total_sessions > 1)
    if known is not None:
        # "known" = email matches the owner's uploaded contacts. Resolve the
        # matching visitor ids once (hash-based) and filter on them. Empty set →
        # in_() matches nobody / notin_() matches everybody, both correct.
        known_ids = list(await _known_visitor_ids(db, site_id))
        if known:
            filters.append(Visitor.visitor_id.in_(known_ids))
        else:
            filters.append(Visitor.visitor_id.notin_(known_ids))
    if first_seen_from is not None:
        filters.append(Visitor.first_seen >= first_seen_from)
    if first_seen_to is not None:
        filters.append(Visitor.first_seen < first_seen_to)
    if last_seen_from is not None:
        filters.append(Visitor.last_seen >= last_seen_from)
    if last_seen_to is not None:
        filters.append(Visitor.last_seen < last_seen_to)
    if min_intent is not None:
        filters.append(Visitor.intent_score >= min_intent)

    for predicate in filters:
        query = query.where(predicate)
        count_query = count_query.where(predicate)

    sort_col = {
        "intent_score": Visitor.intent_score.desc(),
        "last_seen": Visitor.last_seen.desc(),
        "pageviews": Visitor.total_pageviews.desc(),
    }.get(sort_by, Visitor.intent_score.desc())

    query = query.order_by(sort_col).offset((page - 1) * page_size).limit(page_size)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    result = await db.execute(query)
    rows = list(result.scalars().all())
    visitors = [VisitorOut.model_validate(v) for v in rows]

    # Attach email/full_name from the identity table for this page's visitors.
    # One extra query for the whole page (not N) — identified_visitors is 1:1
    # on (site_id, visitor_id), so the map can't fan a visitor into two rows.
    vids = [v.visitor_id for v in rows]
    if vids:
        id_rows = await db.execute(
            select(
                IdentifiedVisitor.visitor_id,
                IdentifiedVisitor.email,
                IdentifiedVisitor.full_name,
            ).where(
                IdentifiedVisitor.site_id == site_id,
                IdentifiedVisitor.visitor_id.in_(vids),
            )
        )
        id_map = {r.visitor_id: (r.email, r.full_name) for r in id_rows}
        for v in visitors:
            if v.visitor_id in id_map:
                v.email, v.full_name = id_map[v.visitor_id]

        # Flag rows whose email is in the owner's known-contacts list (badge).
        # One query for the page: hash this page's emails, look them up by hash.
        page_hashes = {vid: email_hash(em) for vid, (em, _fn) in id_map.items() if em}
        if page_hashes:
            known_rows = await db.execute(
                select(KnownContact.email_hash, KnownContact.source).where(
                    KnownContact.site_id == site_id,
                    KnownContact.email_hash.in_(list(set(page_hashes.values()))),
                )
            )
            known_src = {h: src for h, src in known_rows}
            for v in visitors:
                h = page_hashes.get(v.visitor_id)
                if h and h in known_src:
                    v.is_known = True
                    v.known_source = known_src[h]

    return VisitorListResponse(visitors=visitors, total=total, page=page, page_size=page_size)


@router.get("/{site_id}/countries", response_model=list[VisitorCountryOut])
async def list_visitor_countries(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[VisitorCountryOut]:
    """Distinct GeoIP countries for this site's visitors, with counts, ordered
    by count desc. Feeds the country filter dropdown on the Visitors page.
    One cheap GROUP BY — not paginated. Defined before the /{visitor_id} route
    so "countries" isn't swallowed as a visitor id."""
    await _verify_site_access(db, site_id, user)
    rows = await db.execute(
        select(Visitor.country_code, func.count().label("count"))
        .where(Visitor.site_id == site_id, Visitor.country_code.isnot(None))
        .group_by(Visitor.country_code)
        .order_by(func.count().desc())
    )
    return [VisitorCountryOut(country_code=r.country_code, count=r.count) for r in rows]


async def _compute_visitor_stat_counts(db: AsyncSession, site_id: str) -> dict[str, int]:
    """Count-based site stats in 2 queries instead of 6.

    The five visitor-table counts are collapsed into a single table scan using
    conditional aggregates (``COUNT(*) FILTER (WHERE ...)``). The enrichment-
    profile count stays its own query because it targets a different table.
    Results are identical to issuing each ``COUNT`` separately — the per-site
    ``WHERE`` is applied once and every filtered aggregate is scoped under it.
    """
    row = (
        await db.execute(
            select(
                func.count().label("total"),
                func.count()
                .filter(Visitor.identity_status == "identified")
                .label("identified"),
                func.count()
                .filter(Visitor.enrichment_status == "enriched")
                .label("enriched"),
                func.count()
                .filter(
                    and_(
                        Visitor.enrichment_status == "enriched",
                        Visitor.segmented == False,  # noqa: E712
                    )
                )
                .label("enriched_unsegmented"),
                func.count()
                .filter(
                    and_(
                        Visitor.identity_status == "anonymous",
                        Visitor.intent_score >= 40,
                    )
                )
                .label("eligible_for_resolution"),
            )
            .select_from(Visitor)
            .where(Visitor.site_id == site_id)
        )
    ).one()

    # Could be enriched further (low completeness) — separate table.
    could_enrich_more = (
        await db.execute(
            select(func.count())
            .select_from(EnrichmentProfile)
            .where(
                EnrichmentProfile.site_id == site_id,
                EnrichmentProfile.enrichment_completeness < 0.6,
            )
        )
    ).scalar() or 0

    return {
        "total": row.total or 0,
        "identified": row.identified or 0,
        "enriched": row.enriched or 0,
        "could_enrich_more": could_enrich_more,
        "enriched_unsegmented": row.enriched_unsegmented or 0,
        "eligible_for_resolution": row.eligible_for_resolution or 0,
    }


@router.get("/{site_id}/stats", response_model=VisitorStatsResponse)
async def get_visitor_stats(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VisitorStatsResponse:
    """Get enrichment and identity stats for a site, including the
    segmentation-trigger progress count and the daily identification quota."""
    await _verify_site_access(db, site_id, user)

    counts = await _compute_visitor_stat_counts(db, site_id)
    budget = await check_identify_budget(db, site_id, user.id)

    return VisitorStatsResponse(
        total_visitors=counts["total"],
        identified=counts["identified"],
        enriched=counts["enriched"],
        could_enrich_more=counts["could_enrich_more"],
        enriched_unsegmented=counts["enriched_unsegmented"],
        eligible_for_resolution=counts["eligible_for_resolution"],
        identify_used_today=budget["used"],
        identify_daily_limit=budget["limit"],
        identify_is_byok=budget["is_byok"],
    )


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


# Cap on per-visitor events in an export payload. A single visitor almost never
# has this many; the cap just bounds a pathological payload. Truncation is
# surfaced in the response so it's never a silent omission.
_EXPORT_EVENT_CAP = 5000


@router.get("/{site_id}/{visitor_id}/data/export")
async def export_visitor_data(
    site_id: str,
    visitor_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export ALL data held for one visitor as JSON (GDPR/CCPA access request).

    The symmetric counterpart to DELETE /{site_id}/{visitor_id}/data: gathers
    the visitor row, identity, enrichment, captured emails, events, resolution
    logs, segment memberships, and any crawled social posts matching their
    handle. Site-ownership is enforced so one tenant can't read another's data.
    """
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse

    from apps.api.models.event import Event as EventRow
    from apps.api.models.post import Post
    from apps.api.models.segment import SegmentMember
    from apps.api.models.visitor_email import VisitorEmail

    await _verify_site_access(db, site_id, user)

    def _scope(model):
        return select(model).where(model.site_id == site_id, model.visitor_id == visitor_id)

    visitor = (await db.execute(_scope(Visitor))).scalar_one_or_none()
    identified = (await db.execute(_scope(IdentifiedVisitor))).scalar_one_or_none()
    enrichment = (await db.execute(_scope(EnrichmentProfile))).scalar_one_or_none()
    emails = (await db.execute(_scope(VisitorEmail))).scalars().all()
    resolution_logs = (await db.execute(_scope(ResolutionLog))).scalars().all()
    segments = (await db.execute(_scope(SegmentMember))).scalars().all()

    events_rows = (
        await db.execute(
            _scope(EventRow).order_by(EventRow.created_at.desc()).limit(_EXPORT_EVENT_CAP + 1)
        )
    ).scalars().all()
    events_truncated = len(events_rows) > _EXPORT_EVENT_CAP
    events_rows = events_rows[:_EXPORT_EVENT_CAP]

    # Crawled social posts tied to this person's Twitter handle (best-effort).
    posts: list = []
    handle = (enrichment.twitter_handle or "").lstrip("@").strip() if enrichment else ""
    if handle:
        posts = (
            await db.execute(
                select(Post).where(func.lower(Post.author_username) == handle.lower())
            )
        ).scalars().all()

    payload = {
        "site_id": site_id,
        "visitor_id": visitor_id,
        "exported_at": datetime.now(timezone.utc),
        "visitor": _row_to_dict(visitor) if visitor else None,
        "identified": _row_to_dict(identified) if identified else None,
        "enrichment": _row_to_dict(enrichment) if enrichment else None,
        "emails": [_row_to_dict(e) for e in emails],
        "events": [_row_to_dict(e) for e in events_rows],
        "events_truncated": events_truncated,
        "resolution_logs": [_row_to_dict(r) for r in resolution_logs],
        "segments": [_row_to_dict(s) for s in segments],
        "social_posts": [_row_to_dict(p) for p in posts],
    }

    logger.info(
        "visitor_data_exported",
        site_id=site_id,
        visitor_id=visitor_id[:8],
        events=len(events_rows),
        truncated=events_truncated,
    )
    return JSONResponse(
        content=jsonable_encoder(payload),
        headers={
            "Content-Disposition": f'attachment; filename="visitor-{visitor_id}-export.json"'
        },
    )


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


async def _resolution_skip_reason(
    db: AsyncSession, site: Site, visitor: Visitor, last_attempt: datetime | None
) -> str:
    """Best-effort explanation for why an anonymous visitor hasn't resolved.

    Mirrors the gates in IdentityResolver.resolve() / run_resolution_for_site,
    checked in the order the pipeline applies them. "awaiting_next_run" means
    fully eligible — just waiting on the next sweep or a manual resolve.
    """
    if visitor.intent_score < 40:
        return "below_intent_threshold"
    if not visitor.ip_address:
        return "no_ip_address"
    if last_attempt is not None:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
        if last_attempt >= cutoff:
            return "recently_attempted"
    if not await check_resolution_attempt_budget(db, site.site_id):
        return "daily_budget_exhausted"
    if not await check_usage_allowed(db, site.user_id):
        return "monthly_plan_limit_reached"
    return "awaiting_next_run"


@router.get("/{site_id}/{visitor_id}", response_model=VisitorDetailOut)
async def get_visitor_detail(
    site_id: str,
    visitor_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VisitorDetailOut:
    site = await _verify_site_access(db, site_id, user)

    result = await db.execute(
        select(Visitor).where(Visitor.site_id == site_id, Visitor.visitor_id == visitor_id)
    )
    visitor = result.scalar_one_or_none()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")

    data = VisitorOut.model_validate(visitor).model_dump()

    # Resolution observability: latest attempt + skip reason for stuck visitors
    logs_result = await db.execute(
        select(ResolutionLog).where(
            ResolutionLog.site_id == site_id,
            ResolutionLog.visitor_id == visitor_id,
        ).order_by(ResolutionLog.created_at.desc()).limit(10)
    )
    logs = list(logs_result.scalars().all())
    if logs:
        data["last_resolution_attempt"] = logs[0].created_at
        data["resolution_providers_tried"] = list(dict.fromkeys(l.provider for l in logs))
    if visitor.identity_status == "anonymous":
        data["resolution_skip_reason"] = await _resolution_skip_reason(
            db, site, visitor, logs[0].created_at if logs else None
        )

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


@router.post("/{site_id}/{visitor_id}/resolve")
async def resolve_one_visitor(
    site_id: str,
    visitor_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run the identity-resolution waterfall for ONE visitor (per-row Identify).

    Reuses the exact primitives of the site-wide sweep (`run_resolution_for_site`):
    the monthly plan gate, `IdentityResolver.resolve` (which itself enforces the
    per-site daily budget + 30-day no-retry rule and sets identity_status), a usage
    increment on success, and Tier-1 enrichment. Idempotent: a visitor that's
    already been processed is returned as-is without burning another paid lookup.
    """
    site = await _verify_site_access(db, site_id, user)

    result = await db.execute(
        select(Visitor).where(Visitor.site_id == site_id, Visitor.visitor_id == visitor_id)
    )
    visitor = result.scalar_one_or_none()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")

    # Already processed → don't re-run (no extra paid lookup).
    if visitor.identity_status != "anonymous":
        return {"status": visitor.identity_status, "message": "Already processed."}

    # Monthly plan limit (free=10/mo) — the same gate the auto sweep applies.
    if not await check_usage_allowed(db, site.user_id):
        return {
            "status": "limit_reached",
            "message": (
                "Monthly identification limit reached for your plan. "
                "Add your own API keys in Settings to unlock unlimited."
            ),
        }

    identified = await IdentityResolver(db).resolve(visitor)

    if identified:
        await increment_usage(db, site.user_id)
        try:
            await Enricher(db).enrich_tier1(visitor, identified)
        except Exception as e:
            logger.warning("resolve_one_enrich_error", visitor_id=visitor_id[:8], error=str(e))
        await db.commit()
        return {
            "status": "identified",
            "email": identified.email,
            "full_name": identified.full_name,
        }

    # resolve() set the terminal status (unresolvable / vpn_filtered) and committed,
    # or left it anonymous when a gate skipped it (recent attempt / daily budget).
    # Re-read the status with a fresh query (avoids lazy-load after commit).
    status = (
        await db.execute(
            select(Visitor.identity_status).where(
                Visitor.site_id == site_id, Visitor.visitor_id == visitor_id
            )
        )
    ).scalar_one()
    messages = {
        "unresolvable": "Couldn't identify this visitor from available providers.",
        "vpn_filtered": "Skipped — visitor is behind a VPN/proxy.",
        "anonymous": "Not resolved — daily budget used up or attempted in the last 30 days. Try later.",
    }
    return {"status": status, "message": messages.get(status, "Not resolved.")}


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
    """Background trigger for the trigger-agnostic resolution runner.

    Runs AFTER the HTTP response is sent, in its own DB session (the
    request-scoped session is already closed by the time this runs).
    All resolution logic lives in services/resolution_runner.py — shared
    with the APScheduler sweep and any future Celery/cron worker.
    """
    async with async_session() as db:
        site_result = await db.execute(select(Site).where(Site.site_id == site_id))
        site = site_result.scalar_one_or_none()
        if site is None:
            return
        await run_resolution_for_site(db, site, max_resolve=max_resolve)


@router.post("/{site_id}/resolve")
async def resolve_site_visitors(
    site_id: str,
    background_tasks: BackgroundTasks,
    reset: bool = Query(False, description="Reset unresolvable visitors back to anonymous for re-processing"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Queue identity resolution + Tier 1 enrichment for eligible visitors.

    Daily cap: Site.daily_resolution_budget identifications/day (default 50,
    free tier). BYOK all APIs to unlock unlimited.
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
        # Only flip status back to anonymous. resolution_logs are immutable:
        # both the daily identification budget and the 30-day no-retry gate
        # are computed from them, so deleting rows here (as this endpoint
        # used to do) let anyone loop reset+resolve to re-burn paid provider
        # credits on the same visitors, unbounded, same day. Reset visitors
        # become eligible again naturally once the 30-day window passes (or
        # immediately for providers exempt from the recency gate).
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


async def _run_osint_scan_job(site_id: str, visitor_id: str) -> None:
    """Background OSINT account scan for one visitor.

    Runs AFTER the HTTP response, in its own DB session. Read-modify-writes
    EnrichmentProfile.social_context under the `osint_scan` key, PRESERVING any
    existing `deep_research` (social_context is otherwise overwritten wholesale
    elsewhere). Does NOT touch social_context_updated_at — that column drives the
    deep-research daily meter and an OSINT scan must not count against it.
    """
    async with async_session() as db:
        id_row = await db.execute(
            select(IdentifiedVisitor).where(
                IdentifiedVisitor.site_id == site_id,
                IdentifiedVisitor.visitor_id == visitor_id,
            )
        )
        identified = id_row.scalar_one_or_none()
        email = identified.email if identified else None

        prof_row = await db.execute(
            select(EnrichmentProfile).where(
                EnrichmentProfile.site_id == site_id,
                EnrichmentProfile.visitor_id == visitor_id,
            )
        )
        profile = prof_row.scalar_one_or_none()
        if profile is None:
            profile = EnrichmentProfile(
                visitor_id=visitor_id, site_id=site_id, enrichment_completeness=0.0
            )
            db.add(profile)
            await db.flush()

        if not email:
            blob = {
                "status": "not_identified", "accounts": [], "engines": [],
                "summary": {}, "message": "Visitor has no email to scan.",
            }
        else:
            try:
                blob = await run_osint_scan(email)
            except Exception as e:  # defensive — run_osint_scan shouldn't raise
                logger.warning("osint_scan_job_error", visitor_id=visitor_id[:8], error=str(e))
                blob = {
                    "status": "error", "accounts": [], "engines": [],
                    "summary": {}, "message": "OSINT scan failed unexpectedly.",
                }

        # Read-modify-write: reassign a NEW dict so SQLAlchemy detects the JSONB
        # change, and keep every other social_context key (e.g. deep_research).
        merged = dict(profile.social_context or {})
        merged["osint_scan"] = blob
        profile.social_context = merged
        await db.commit()
        logger.info(
            "osint_scan_job_done", visitor_id=visitor_id[:8],
            status=blob.get("status"), accounts=len(blob.get("accounts", [])),
        )


@router.post("/{site_id}/{visitor_id}/osint-scan")
async def osint_scan_visitor(
    site_id: str,
    visitor_id: str,
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Re-run even if a completed scan exists"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run free OSINT account scanners (user-scanner + holehe) for ONE visitor.

    Manual, per-visitor trigger. Existence checks rely on public reset/registration
    signals (OSINT) — a legal gray area under some sites' ToS; use responsibly.
    Daily cap: settings.osint_scan_daily_budget scans/site (BYOK = unlimited).
    Results land in EnrichmentProfile.social_context['osint_scan']; the frontend
    polls the visitor-detail endpoint while status == 'scanning'.
    """
    if not settings.enable_osint_scan:
        return {"status": "disabled", "message": "OSINT scanning is not enabled."}

    await _verify_site_access(db, site_id, user)

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
    if not identified or not identified.email:
        return {
            "status": "not_identified",
            "message": "Visitor must have an email before OSINT scanning.",
        }

    prof_result = await db.execute(
        select(EnrichmentProfile).where(
            EnrichmentProfile.site_id == site_id,
            EnrichmentProfile.visitor_id == visitor_id,
        )
    )
    profile = prof_result.scalar_one_or_none()
    current = (profile.social_context or {}).get("osint_scan") if profile else None

    if current and current.get("status") == "scanning":
        return {"status": "scanning", "message": "A scan is already running. Refresh shortly."}
    if current and current.get("status") in ("complete", "cached") and not force:
        return {
            "status": current.get("status"),
            "message": "Already scanned. Showing existing results (use re-scan to refresh).",
        }

    budget = await check_osint_budget(db, site_id, user.id)
    if not budget["allowed"]:
        return {
            "status": "limit_reached",
            "message": (
                f"Daily OSINT scan limit reached ({budget['used']}/{budget['limit']}). "
                "Add your own API keys in Settings to unlock unlimited."
            ),
            "used": budget["used"],
            "limit": budget["limit"],
        }

    # Mark scanning so the polling UI shows a spinner immediately.
    if profile is None:
        profile = EnrichmentProfile(
            visitor_id=visitor_id, site_id=site_id, enrichment_completeness=0.0
        )
        db.add(profile)
    sc = dict(profile.social_context or {})
    sc["osint_scan"] = {"status": "scanning", "accounts": [], "engines": [],
                        "summary": {}, "message": "Scanning…"}
    profile.social_context = sc
    await db.commit()

    await increment_osint_usage(site_id)
    background_tasks.add_task(_run_osint_scan_job, site_id, visitor_id)

    return {
        "status": "started",
        "message": "Scanning accounts in the background. Refresh in ~30–60s to see results.",
    }


async def _run_social_resolution_job(site_id: str, visitor_id: str) -> None:
    """Background full social-resolution pipeline (stages A–F) for one visitor.

    Owns its own session. resolve_social() persists social_context itself
    (osint_scan + social_resolution + deep_research, read-modify-write).
    """
    async with async_session() as db:
        visitor = (await db.execute(
            select(Visitor).where(Visitor.site_id == site_id, Visitor.visitor_id == visitor_id)
        )).scalar_one_or_none()
        if visitor is None:
            return
        identified = (await db.execute(
            select(IdentifiedVisitor).where(
                IdentifiedVisitor.site_id == site_id,
                IdentifiedVisitor.visitor_id == visitor_id,
            )
        )).scalar_one_or_none()
        profile = (await db.execute(
            select(EnrichmentProfile).where(
                EnrichmentProfile.site_id == site_id,
                EnrichmentProfile.visitor_id == visitor_id,
            )
        )).scalar_one_or_none()
        if profile is None:
            profile = EnrichmentProfile(
                visitor_id=visitor_id, site_id=site_id, enrichment_completeness=0.0
            )
            db.add(profile)
            await db.flush()
        try:
            await resolve_social(db, visitor=visitor, identified=identified, profile=profile)
        except Exception as e:
            logger.warning("social_resolution_job_error", visitor_id=visitor_id[:8], error=str(e))
            merged = dict(profile.social_context or {})
            merged["social_resolution"] = {
                "status": "error", "profiles": [], "stages_run": [],
                "message": "Social resolution failed unexpectedly.",
            }
            profile.social_context = merged
            await db.commit()


@router.post("/{site_id}/{visitor_id}/resolve-social")
async def resolve_social_visitor(
    site_id: str,
    visitor_id: str,
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Re-run even if a completed resolution exists"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Full social-resolution pipeline for ONE visitor: free OSINT + Maigret +
    rule-base → (auto paid fallback) → Gemini. Manual, per-visitor. Free daily
    cap gates the trigger (settings.osint_scan_daily_budget); the paid stage has
    its own separate credit cap. Results land in
    social_context['social_resolution']; the UI polls visitor-detail while
    status == 'scanning'.
    """
    if not settings.enable_osint_scan:
        return {"status": "disabled", "message": "OSINT scanning is not enabled."}

    await _verify_site_access(db, site_id, user)

    visitor = (await db.execute(
        select(Visitor).where(Visitor.site_id == site_id, Visitor.visitor_id == visitor_id)
    )).scalar_one_or_none()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")

    identified = (await db.execute(
        select(IdentifiedVisitor).where(
            IdentifiedVisitor.site_id == site_id,
            IdentifiedVisitor.visitor_id == visitor_id,
        )
    )).scalar_one_or_none()
    if not identified or not identified.email:
        return {"status": "not_identified",
                "message": "Visitor must have an email before social resolution."}

    profile = (await db.execute(
        select(EnrichmentProfile).where(
            EnrichmentProfile.site_id == site_id,
            EnrichmentProfile.visitor_id == visitor_id,
        )
    )).scalar_one_or_none()
    current = (profile.social_context or {}).get("social_resolution") if profile else None

    if current and current.get("status") == "scanning":
        return {"status": "scanning", "message": "Resolution already running. Refresh shortly."}
    if current and current.get("status") == "complete" and not force:
        return {"status": "complete",
                "message": "Already resolved. Use re-scan to refresh."}

    budget = await check_osint_budget(db, site_id, user.id)
    if not budget["allowed"]:
        return {
            "status": "limit_reached",
            "message": (
                f"Daily resolution limit reached ({budget['used']}/{budget['limit']}). "
                "Add your own API keys in Settings to unlock unlimited."
            ),
            "used": budget["used"], "limit": budget["limit"],
        }

    if profile is None:
        profile = EnrichmentProfile(
            visitor_id=visitor_id, site_id=site_id, enrichment_completeness=0.0
        )
        db.add(profile)
    sc = dict(profile.social_context or {})
    sc["social_resolution"] = {"status": "scanning", "profiles": [], "stages_run": [],
                               "message": "Resolving social profiles…"}
    profile.social_context = sc
    await db.commit()

    await increment_osint_usage(site_id)
    background_tasks.add_task(_run_social_resolution_job, site_id, visitor_id)

    return {
        "status": "started",
        "message": "Resolving social profiles in the background. Refresh in ~30–90s.",
    }


