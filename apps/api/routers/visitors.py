from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.database import get_db
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.user import User
from apps.api.models.visitor import IdentifiedVisitor, ResolutionLog, Visitor
from apps.api.models.visitor_email import VisitorEmail
from apps.api.dependencies import get_current_user, verify_site_access as _verify_site_access
from apps.api.routers.visitors_helpers import (
    _EXPORT_EVENT_CAP,
    _SKIP_REASON_LIMIT_KIND,
    _SKIP_REASON_MESSAGES,
    _build_visitor_filters,
    _compute_visitor_stat_counts,
    _coverage_note,
    _resolution_skip_reason,
    _row_to_dict,
    _run_osint_scan_job,
    _run_resolution_job,
    _run_social_resolution_job,
)
from apps.api.schemas.visitors import (
    ManualIdentifyRequest,
    VisitorAiSourceOut,
    VisitorCountryOut,
    VisitorDetailOut,
    VisitorListResponse,
    VisitorOut,
    VisitorStatsResponse,
)
from apps.api.services.agent_visitor_filters import human_only_visitor_filter
from apps.api.services.billing import check_usage_allowed, increment_usage
from apps.api.services.conviction import build_conviction
from apps.api.services.enricher import Enricher
from apps.api.services.identity_classification import identity_level
from apps.api.services.identity_resolver import IdentityResolver
from apps.api.services.known_hash import email_hash
from apps.api.services.resolution_eligibility import site_resolves_all_us
from apps.api.services.usage_limits import (
    check_enrich_budget,
    check_identify_budget,
    check_osint_budget,
    increment_osint_usage,
)

logger = structlog.get_logger()

router = APIRouter()


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
    ai_source: str | None = None,  # AI-referral label, or "__any__" for any AI source
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

    # Hide "ghost" rows: zero-pageview fragment visitors created by
    # storage-blocked subframe tracker instances, which only ever emitted
    # interaction events (scroll / time_on_page). Identified visitors are kept
    # even at zero pageviews — an identity row or a captured email
    # (visitor_emails) both mean a real lead whose pageview beacon was lost.
    not_ghost = or_(
        Visitor.total_pageviews > 0,
        select(IdentifiedVisitor.id)
        .where(
            IdentifiedVisitor.site_id == Visitor.site_id,
            IdentifiedVisitor.visitor_id == Visitor.visitor_id,
        )
        .exists(),
        select(VisitorEmail.id)
        .where(
            VisitorEmail.site_id == Visitor.site_id,
            VisitorEmail.visitor_id == Visitor.visitor_id,
        )
        .exists(),
    )

    query = select(Visitor).where(Visitor.site_id == site_id, not_ghost)
    count_query = (
        select(func.count())
        .select_from(Visitor)
        .where(Visitor.site_id == site_id, not_ghost)
    )

    # Build the filter predicates once and apply the same list to both the row
    # query and the count query, so the paginated total always matches the rows.
    # first_seen / last_seen are naive (UTC) timestamps, so bounds cut on UTC days.
    filters = await _build_visitor_filters(
        db,
        site_id,
        identity_status=identity_status,
        enrichment_status=enrichment_status,
        country=country,
        visitor_type=visitor_type,
        known=known,
        ai_source=ai_source,
        first_seen_from=first_seen_from,
        first_seen_to=first_seen_to,
        last_seen_from=last_seen_from,
        last_seen_to=last_seen_to,
        min_intent=min_intent,
    )

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
                IdentifiedVisitor.resolution_provider,
            ).where(
                IdentifiedVisitor.site_id == site_id,
                IdentifiedVisitor.visitor_id.in_(vids),
            )
        )
        id_map = {r.visitor_id: (r.email, r.full_name, r.resolution_provider) for r in id_rows}

        # Merged visitors carry their identity on the canonical row, not their
        # own — resolve email/name from canonical_visitor_id so deduped
        # duplicates aren't shown blank. Fold into id_map so the display loop
        # and the known-contacts hash below both pick them up.
        canon_of = {
            v.visitor_id: v.canonical_visitor_id
            for v in rows
            if v.identity_status == "merged"
            and v.canonical_visitor_id
            and v.visitor_id not in id_map
        }
        if canon_of:
            canon_rows = await db.execute(
                select(
                    IdentifiedVisitor.visitor_id,
                    IdentifiedVisitor.email,
                    IdentifiedVisitor.full_name,
                    IdentifiedVisitor.resolution_provider,
                ).where(
                    IdentifiedVisitor.site_id == site_id,
                    IdentifiedVisitor.visitor_id.in_(set(canon_of.values())),
                )
            )
            canon_id_map = {
                r.visitor_id: (r.email, r.full_name, r.resolution_provider) for r in canon_rows
            }
            for vid, cvid in canon_of.items():
                if cvid in canon_id_map:
                    id_map[vid] = canon_id_map[cvid]

        for v in visitors:
            if v.visitor_id in id_map:
                v.email, v.full_name, _prov = id_map[v.visitor_id]
                v.identity_level = identity_level(_prov)

        # Flag rows whose email is in the owner's known-contacts list (badge).
        # One query for the page: hash this page's emails, look them up by hash.
        page_hashes = {vid: email_hash(em) for vid, (em, _fn, _prov) in id_map.items() if em}
        if page_hashes:
            from apps.api.services.known_contacts_match import known_source_map

            known_src = await known_source_map(db, site_id, set(page_hashes.values()))
            for v in visitors:
                h = page_hashes.get(v.visitor_id)
                if h and h in known_src:
                    v.is_known = True
                    v.known_source = known_src[h]

    # Handoff Detection H2: flag which of this page's visitors have a fetch↔click
    # handoff link, for a list-row pill. One query for the whole page (not N) —
    # prefer the strongest confidence when a visitor has multiple links.
    if vids:
        from apps.api.models.agent_handoff_link import AgentHandoffLink

        handoff_rows = await db.execute(
            select(
                AgentHandoffLink.visitor_id,
                AgentHandoffLink.confidence,
            ).where(
                AgentHandoffLink.site_id == site_id,
                AgentHandoffLink.visitor_id.in_(vids),
            )
        )
        handoff_map: dict[str, str] = {}
        for r in handoff_rows:
            # "high" beats "medium" if a visitor has more than one link.
            if handoff_map.get(r.visitor_id) == "high":
                continue
            handoff_map[r.visitor_id] = r.confidence
        for v in visitors:
            if v.visitor_id in handoff_map:
                v.handoff_confidence = handoff_map[v.visitor_id]

    for v in visitors:
        v.conviction = build_conviction(v.model_dump())

    return VisitorListResponse(visitors=visitors, total=total, page=page, page_size=page_size)


@router.get("/{site_id}/countries", response_model=list[VisitorCountryOut])
async def list_visitor_countries(
    site_id: str,
    identity_status: str | None = None,
    enrichment_status: str | None = None,
    visitor_type: str | None = None,
    known: bool | None = None,
    first_seen_from: datetime | None = None,
    first_seen_to: datetime | None = None,
    last_seen_from: datetime | None = None,
    last_seen_to: datetime | None = None,
    min_intent: float | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[VisitorCountryOut]:
    """Distinct GeoIP countries for this site's visitors, with counts, ordered
    by count desc. Feeds the country filter dropdown on the Visitors page.

    Counts are FACETED: they honour every other active filter (date ranges,
    visitor type, known, status) so the dropdown reflects what the list will
    actually show. The ``country`` predicate itself is intentionally NOT applied
    here — a facet must not constrain its own counts, otherwise picking one
    country would collapse the dropdown to that single option.
    One GROUP BY — not paginated. Defined before the /{visitor_id} route so
    "countries" isn't swallowed as a visitor id."""
    await _verify_site_access(db, site_id, user)
    filters = await _build_visitor_filters(
        db,
        site_id,
        identity_status=identity_status,
        enrichment_status=enrichment_status,
        country=None,  # faceted: don't constrain the facet by itself
        visitor_type=visitor_type,
        known=known,
        first_seen_from=first_seen_from,
        first_seen_to=first_seen_to,
        last_seen_from=last_seen_from,
        last_seen_to=last_seen_to,
        min_intent=min_intent,
    )
    stmt = (
        select(Visitor.country_code, func.count().label("count"))
        .where(Visitor.site_id == site_id, Visitor.country_code.isnot(None))
    )
    for predicate in filters:
        stmt = stmt.where(predicate)
    stmt = stmt.group_by(Visitor.country_code).order_by(func.count().desc())
    rows = await db.execute(stmt)
    return [VisitorCountryOut(country_code=r.country_code, count=r.count) for r in rows]


@router.get("/{site_id}/ai-sources", response_model=list[VisitorAiSourceOut])
async def list_visitor_ai_sources(
    site_id: str,
    identity_status: str | None = None,
    enrichment_status: str | None = None,
    country: str | None = Query(None, max_length=5),
    visitor_type: str | None = None,
    known: bool | None = None,
    first_seen_from: datetime | None = None,
    first_seen_to: datetime | None = None,
    last_seen_from: datetime | None = None,
    last_seen_to: datetime | None = None,
    min_intent: float | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[VisitorAiSourceOut]:
    """Distinct AI answer-engine sources for this site's visitors, with counts,
    ordered by count desc. Feeds the Source filter dropdown on the Visitors page.

    Faceted exactly like the country facet: honours every other active filter but
    NOT the ai_source predicate itself (a facet must not constrain its own
    counts). ``ai_source IS NOT NULL`` excludes non-AI-referred visitors, and
    ``human_only_visitor_filter()`` (inherited at the _build_visitor_filters choke
    point) excludes synthetic agent-derived rows. Attribution-only surface —
    never touches emailability. Defined before /{visitor_id} so "ai-sources"
    isn't swallowed as a visitor id."""
    await _verify_site_access(db, site_id, user)
    filters = await _build_visitor_filters(
        db,
        site_id,
        identity_status=identity_status,
        enrichment_status=enrichment_status,
        country=country,
        visitor_type=visitor_type,
        known=known,
        ai_source=None,  # faceted: don't constrain the facet by itself
        first_seen_from=first_seen_from,
        first_seen_to=first_seen_to,
        last_seen_from=last_seen_from,
        last_seen_to=last_seen_to,
        min_intent=min_intent,
    )
    stmt = (
        select(Visitor.ai_source, func.count().label("count"))
        .where(Visitor.site_id == site_id, Visitor.ai_source.isnot(None))
    )
    for predicate in filters:
        stmt = stmt.where(predicate)
    stmt = stmt.group_by(Visitor.ai_source).order_by(func.count().desc())
    rows = await db.execute(stmt)
    return [VisitorAiSourceOut(ai_source=r.ai_source, count=r.count) for r in rows]


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
        # Scope to the requesting user's own social accounts. The posts table is
        # global with no site_id/visitor_id; the only tenancy link is
        # social_account_id -> SocialAccount.user_id. Without this join a DSAR
        # export would include posts another customer imported for the same handle.
        from apps.api.models.social_account import SocialAccount
        posts = (
            await db.execute(
                select(Post)
                .join(SocialAccount, Post.social_account_id == SocialAccount.id)
                .where(
                    SocialAccount.user_id == user.id,
                    func.lower(Post.author_username) == handle.lower(),
                )
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

    # Delete the visitors' satellite rows too (identity, enrichment, captured
    # emails) — deleting only Visitor used to leave these behind as orphans
    # that no page can ever render (2026-07-02: 8 orphan enrichment_profiles
    # found on prod from exactly this gap).
    from apps.api.models.visitor_email import VisitorEmail

    await db.execute(
        IdentifiedVisitor.__table__.delete().where(
            IdentifiedVisitor.site_id == site_id,
            IdentifiedVisitor.visitor_id.in_(test_vids),
        )
    )
    await db.execute(
        EnrichmentProfile.__table__.delete().where(
            EnrichmentProfile.site_id == site_id,
            EnrichmentProfile.visitor_id.in_(test_vids),
        )
    )
    await db.execute(
        VisitorEmail.__table__.delete().where(
            VisitorEmail.site_id == site_id,
            VisitorEmail.visitor_id.in_(test_vids),
        )
    )

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
    site = await _verify_site_access(db, site_id, user)

    result = await db.execute(
        select(Visitor).where(
            Visitor.site_id == site_id,
            Visitor.visitor_id == visitor_id,
            # AC2 (GUARD #2): a synthetic agent-derived row must never render in
            # the human visitor UI even if its id were somehow guessed/enumerated.
            human_only_visitor_filter(),
        )
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
    elif visitor.identity_status == "unresolvable":
        # Explain a structural miss (non-US residential) instead of a bare badge.
        data["coverage_note"] = _coverage_note(visitor)

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
            "identity_level": identity_level(identified.resolution_provider),
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
            "avatar_url": enriched.avatar_url,
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
    data["conviction"] = build_conviction(data)

    # Handoff Detection H2 (AC-H2-1/4): surface the latest fetch↔click handoff link
    # for this visitor, if any. Read-only, additive — PROBABILISTIC attribution, and
    # NEVER a factor in emailability (separate write path from source_agent_visit_id).
    from apps.api.models.agent_fetch_event import AgentFetchEvent
    from apps.api.models.agent_handoff_link import AgentHandoffLink

    handoff_result = await db.execute(
        select(AgentHandoffLink, AgentFetchEvent)
        .join(
            AgentFetchEvent,
            AgentFetchEvent.id == AgentHandoffLink.agent_fetch_event_id,
        )
        .where(
            AgentHandoffLink.site_id == site_id,
            AgentHandoffLink.visitor_id == visitor_id,
        )
        .order_by(AgentHandoffLink.created_at.desc())
        .limit(1)
    )
    handoff_row = handoff_result.first()
    if handoff_row is not None:
        link, fetch_event = handoff_row
        data.update({
            "handoff_vendor": fetch_event.vendor,
            "handoff_confidence": link.confidence,
            "handoff_delta_seconds": link.delta_seconds,
            "handoff_matched_page": link.matched_page,
            "handoff_fetch_at": fetch_event.created_at,
        })

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
            "limit_kind": "daily_enrichment",
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

    # Already processed → don't re-run (no extra paid lookup), EXCEPT for an
    # `unresolvable` row: a human clicking Retry is deliberately re-running a
    # visitor whose prior attempt may have failed during a provider outage
    # (402/403 look identical to a real no-match). Reset it to anonymous and
    # fall through to the same waterfall with force_retry.
    # `vpn_filtered` stays non-retryable — the IP is still masked.
    is_retry = False
    if visitor.identity_status == "unresolvable":
        is_retry = True
        visitor.identity_status = "anonymous"
    elif visitor.identity_status != "anonymous":
        return {"status": visitor.identity_status, "message": "Already processed."}

    # Privacy opt-out / intent gates BEFORE the paid waterfall: resolve() would
    # bail on these anyway, but bailing here lets us return the real reason (not
    # a canned "budget used up" line) and avoids burning provider calls on the
    # intent<40 visitors the auto sweep never touches.
    if visitor.do_not_resolve:
        return {"status": "anonymous", "skip_reason": "privacy_opt_out",
                "message": _SKIP_REASON_MESSAGES["privacy_opt_out"]}
    # Intent gate honours the site-scoped all-US eligibility rule: on an all-US
    # site every US visitor qualifies regardless of intent score.
    if visitor.intent_score < 40 and not (
        site_resolves_all_us(site.url) and (visitor.country_code or "").upper() == "US"
    ):
        return {"status": "anonymous", "skip_reason": "below_intent_threshold",
                "message": _SKIP_REASON_MESSAGES["below_intent_threshold"]}

    # Monthly plan limit (free=10/mo) — the same gate the auto sweep applies.
    if not await check_usage_allowed(db, site.user_id):
        return {
            "status": "limit_reached",
            "limit_kind": "monthly_plan",
            "message": _SKIP_REASON_MESSAGES["monthly_plan_limit_reached"],
        }

    identified = await IdentityResolver(db).resolve(visitor, force_retry=is_retry)

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
    if status == "anonymous":
        # Left anonymous by a gate (recent attempt / daily budget / etc.). Report
        # the REAL reason instead of guessing — reuses the same logic the visitor
        # detail page shows. Needs the latest attempt for the 30-day cooldown check.
        last_attempt = (
            await db.execute(
                select(func.max(ResolutionLog.created_at)).where(
                    ResolutionLog.site_id == site_id,
                    ResolutionLog.visitor_id == visitor_id,
                )
            )
        ).scalar_one_or_none()
        reason = await _resolution_skip_reason(db, site, visitor, last_attempt)
        resp = {
            "status": "anonymous",
            "skip_reason": reason,
            "message": _SKIP_REASON_MESSAGES.get(reason, "Not resolved. Try again later."),
        }
        limit_kind = _SKIP_REASON_LIMIT_KIND.get(reason)
        if limit_kind:
            resp["limit_kind"] = limit_kind
        return resp
    messages = {
        "unresolvable": _coverage_note(visitor)
        or "Couldn't identify this visitor from available providers.",
        "vpn_filtered": "Skipped — visitor is behind a VPN/proxy.",
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

    site = await _verify_site_access(db, site_id, user)

    budget = await check_identify_budget(db, site_id, user.id)
    if not budget["allowed"]:
        return {
            "status": "limit_reached",
            "limit_kind": "daily_budget",
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
            resolution_intent_filter([site_id] if site_resolves_all_us(site.url) else []),
        )
    )
    eligible_raw = count_result.scalar() or 0

    remaining = (budget["limit"] - budget["used"]) if budget["limit"] else eligible_raw
    eligible = min(eligible_raw, remaining)

    if eligible == 0:
        if eligible_raw > 0:
            return {
                "status": "limit_reached",
                "limit_kind": "daily_budget",
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


