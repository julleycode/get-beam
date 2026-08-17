"""Conversion goals CRUD + outcomes reporting.

Goals are per-site, owner-scoped definitions of "what counts as a conversion"
(URL match today; JS event / webhook sources arrive in a later phase). The
event-ingest path (services/conversion_tracker) matches pageviews against the
enabled goals and records attributed conversions.
"""

import hashlib
import hmac
import secrets as pysecrets
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.dependencies import get_current_user, verify_site_access
from apps.api.models.campaign import Campaign, CampaignTouchpoint
from apps.api.models.database import get_db
from apps.api.models.outcome import Conversion, ConversionGoal
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.models.visitor_email import VisitorEmail
from apps.api.services.campaign_stats import (
    OPEN_RATE_CAVEAT,
    clicked_count_expr,
    opened_count_expr,
    sent_count_expr,
)
from apps.api.models.segment import Segment
from apps.api.schemas.outcomes import (
    BenchmarkComparison,
    CampaignOutcomeRow,
    GoalCreate,
    GoalListResponse,
    GoalOut,
    GoalOutcomeRow,
    GoalUpdate,
    OutcomesReportResponse,
    OutcomeTotals,
    OutcomeWebhookPayload,
    OutcomeWebhookResponse,
    WebhookConfigResponse,
    WebhookSecretResponse,
    WhatsWorkingRow,
    validate_goal_pattern,
)
from apps.api.services.conversion_tracker import MAX_GOALS_PER_SITE, record_conversion
from apps.api.services.key_vault import decrypt_key, encrypt_key, make_key_hint
from apps.api.services.rate_limiter import limiter

router = APIRouter()
logger = structlog.get_logger()


async def _get_goal(db: AsyncSession, site_id: str, goal_id: str) -> ConversionGoal:
    try:
        gid = uuid.UUID(goal_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Goal not found")
    goal = (
        await db.execute(
            select(ConversionGoal).where(
                ConversionGoal.id == gid, ConversionGoal.site_id == site_id
            )
        )
    ).scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goal


async def _name_taken(
    db: AsyncSession, site_id: str, name: str, exclude_id: uuid.UUID | None = None
) -> bool:
    query = select(ConversionGoal.id).where(
        ConversionGoal.site_id == site_id,
        func.lower(ConversionGoal.name) == name.lower(),
    )
    if exclude_id:
        query = query.where(ConversionGoal.id != exclude_id)
    return (await db.execute(query.limit(1))).scalar_one_or_none() is not None


@router.get("/{site_id}/goals", response_model=GoalListResponse)
async def list_goals(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GoalListResponse:
    await verify_site_access(db, site_id, user)
    rows = (
        (
            await db.execute(
                select(ConversionGoal)
                .where(ConversionGoal.site_id == site_id)
                .order_by(ConversionGoal.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    goals = [GoalOut.model_validate(g) for g in rows]
    return GoalListResponse(goals=goals, total=len(goals))


@router.post("/{site_id}/goals", response_model=GoalOut)
async def create_goal(
    site_id: str,
    body: GoalCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GoalOut:
    await verify_site_access(db, site_id, user)

    count = (
        await db.execute(
            select(func.count())
            .select_from(ConversionGoal)
            .where(ConversionGoal.site_id == site_id)
        )
    ).scalar_one()
    if count >= MAX_GOALS_PER_SITE:
        raise HTTPException(
            status_code=400,
            detail=f"Goal limit reached ({MAX_GOALS_PER_SITE} per site)",
        )

    if await _name_taken(db, site_id, body.name):
        raise HTTPException(status_code=409, detail="A goal with this name already exists")

    goal = ConversionGoal(
        id=uuid.uuid4(),
        site_id=site_id,
        name=body.name,
        goal_type=body.goal_type,
        match_type=body.match_type,
        pattern=body.pattern,
        value_cents=body.value_cents,
        repeatable=body.repeatable,
        enabled=True,
    )
    db.add(goal)
    try:
        await db.commit()
    except IntegrityError:
        # Race with a concurrent create of the same name — same outcome as the
        # pre-check, just detected by the unique constraint instead.
        await db.rollback()
        raise HTTPException(status_code=409, detail="A goal with this name already exists")
    await db.refresh(goal)
    logger.info("conversion_goal_created", site_id=site_id, goal=goal.name)
    return GoalOut.model_validate(goal)


@router.patch("/{site_id}/goals/{goal_id}", response_model=GoalOut)
async def update_goal(
    site_id: str,
    goal_id: str,
    body: GoalUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GoalOut:
    await verify_site_access(db, site_id, user)
    goal = await _get_goal(db, site_id, goal_id)

    if body.name is not None and body.name.lower() != goal.name.lower():
        if await _name_taken(db, site_id, body.name, exclude_id=goal.id):
            raise HTTPException(status_code=409, detail="A goal with this name already exists")
    if body.name is not None:
        goal.name = body.name
    if body.match_type is not None:
        goal.match_type = body.match_type
    if body.pattern is not None:
        goal.pattern = body.pattern
    # Re-validate the FINAL (match_type, pattern) pair — either half may have
    # just changed while the other came from the stored row.
    if body.match_type is not None or body.pattern is not None:
        try:
            goal.pattern = validate_goal_pattern(goal.match_type, goal.pattern)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    if body.value_cents is not None:
        goal.value_cents = body.value_cents
    if body.repeatable is not None:
        goal.repeatable = body.repeatable
    if body.enabled is not None:
        goal.enabled = body.enabled

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A goal with this name already exists")
    await db.refresh(goal)
    return GoalOut.model_validate(goal)


@router.get("/{site_id}/report", response_model=OutcomesReportResponse)
async def outcomes_report(
    site_id: str,
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OutcomesReportResponse:
    """Site-wide outcomes: totals, per-campaign funnel, per-goal breakdown.

    Window filters conversions by occurred_at and campaign sends by sent_at.
    Campaign rows include anything with sends OR conversions in the window;
    ``converted`` counts DISTINCT visitors so repeatable goals don't inflate
    the people number (revenue still sums every conversion).
    """
    await verify_site_access(db, site_id, user)
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    totals_row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Conversion.attribution == "campaign"),
                func.coalesce(func.sum(Conversion.value_cents), 0),
                func.coalesce(
                    func.sum(Conversion.value_cents).filter(
                        Conversion.attribution == "campaign"
                    ),
                    0,
                ),
            ).where(Conversion.site_id == site_id, Conversion.occurred_at >= cutoff)
        )
    ).one()
    total_conversions = int(totals_row[0] or 0)
    attributed = int(totals_row[1] or 0)
    totals = OutcomeTotals(
        conversions=total_conversions,
        attributed=attributed,
        organic=total_conversions - attributed,
        revenue_cents=int(totals_row[2] or 0),
        attributed_revenue_cents=int(totals_row[3] or 0),
    )

    # Per-goal breakdown — LEFT JOIN so zero-conversion goals still appear.
    conv_by_goal = (
        select(
            Conversion.goal_id,
            func.count().label("conversions"),
            func.count().filter(Conversion.attribution == "campaign").label("attributed"),
            func.coalesce(func.sum(Conversion.value_cents), 0).label("revenue_cents"),
        )
        .where(Conversion.site_id == site_id, Conversion.occurred_at >= cutoff)
        .group_by(Conversion.goal_id)
        .subquery()
    )
    goal_rows = (
        await db.execute(
            select(
                ConversionGoal.id,
                ConversionGoal.name,
                ConversionGoal.goal_type,
                ConversionGoal.enabled,
                conv_by_goal.c.conversions,
                conv_by_goal.c.attributed,
                conv_by_goal.c.revenue_cents,
            )
            .outerjoin(conv_by_goal, conv_by_goal.c.goal_id == ConversionGoal.id)
            .where(ConversionGoal.site_id == site_id)
            .order_by(ConversionGoal.created_at.desc())
        )
    ).all()
    goals = [
        GoalOutcomeRow(
            goal_id=r[0],
            name=r[1],
            goal_type=r[2],
            enabled=r[3],
            conversions=int(r[4] or 0),
            attributed=int(r[5] or 0),
            revenue_cents=int(r[6] or 0),
        )
        for r in goal_rows
    ]

    # Per-campaign funnel: touchpoint counters and conversion counters come
    # from two grouped queries, merged in Python (a campaign can have sends
    # without conversions and — after deletes/reassigns — vice versa).
    tp_rows = (
        await db.execute(
            select(
                Campaign.id,
                Campaign.name,
                # Shared predicate set — services/campaign_stats.py is the SINGLE
                # funnel definition. Imported as EXPRESSIONS so this stays one
                # grouped aggregate: no rows are materialized, per-campaign
                # grouping is preserved, and the query cost is unchanged.
                # Deliberately unfiltered by channel: /outcomes has never
                # filtered on channel and must keep counting every touchpoint.
                sent_count_expr(cutoff).label("sent"),
                opened_count_expr(cutoff).label("opened"),
                clicked_count_expr(cutoff).label("clicked"),
            )
            .join(CampaignTouchpoint, CampaignTouchpoint.campaign_id == Campaign.id)
            .where(Campaign.site_id == site_id)
            .group_by(Campaign.id, Campaign.name)
        )
    ).all()
    funnel: dict[uuid.UUID, dict] = {
        r[0]: {"name": r[1], "sent": int(r[2] or 0), "opened": int(r[3] or 0), "clicked": int(r[4] or 0)}
        for r in tp_rows
    }

    conv_rows = (
        await db.execute(
            select(
                Conversion.campaign_id,
                func.count(func.distinct(Conversion.visitor_id)).label("converted"),
                func.coalesce(func.sum(Conversion.value_cents), 0).label("revenue_cents"),
            )
            .where(
                Conversion.site_id == site_id,
                Conversion.occurred_at >= cutoff,
                Conversion.campaign_id.is_not(None),
            )
            .group_by(Conversion.campaign_id)
        )
    ).all()
    conv_by_campaign = {r[0]: {"converted": int(r[1] or 0), "revenue_cents": int(r[2] or 0)} for r in conv_rows}

    # Names for campaigns that converted but sent nothing in the window.
    missing_ids = [cid for cid in conv_by_campaign if cid not in funnel]
    if missing_ids:
        name_rows = (
            await db.execute(
                select(Campaign.id, Campaign.name).where(
                    Campaign.id.in_(missing_ids), Campaign.site_id == site_id
                )
            )
        ).all()
        for cid, name in name_rows:
            funnel[cid] = {"name": name, "sent": 0, "opened": 0, "clicked": 0}

    campaigns: list[CampaignOutcomeRow] = []
    for cid, agg in funnel.items():
        conv = conv_by_campaign.get(cid, {"converted": 0, "revenue_cents": 0})
        if agg["sent"] == 0 and conv["converted"] == 0:
            continue  # nothing happened in the window
        campaigns.append(
            CampaignOutcomeRow(
                campaign_id=cid,
                name=agg["name"],
                sent=agg["sent"],
                opened=agg["opened"],
                clicked=agg["clicked"],
                converted=conv["converted"],
                conversion_rate=round(conv["converted"] / agg["sent"], 4) if agg["sent"] else 0.0,
                revenue_cents=conv["revenue_cents"],
            )
        )
    campaigns.sort(key=lambda c: (c.converted, c.sent), reverse=True)

    # ── "What's working" (marketing-claims-gap Phase 3, D2) ──
    # Ranked by CAMPAIGN and SEGMENT only. Subject-line ranking is a named
    # deferral: tenant-authored subject text would need clean_text sanitization
    # before it could be surfaced, so nothing here reads it.
    # open_rate is None for a campaign that sent nothing — no sends is not a
    # measured zero — and every open-rate value ships with OPEN_RATE_CAVEAT.
    whats_working: list[WhatsWorkingRow] = [
        WhatsWorkingRow(
            kind="campaign",
            label=c.name,
            sent=c.sent,
            clicked=c.clicked,
            converted=c.converted,
            conversion_rate=c.conversion_rate,
            open_rate=round(c.opened / c.sent, 4) if c.sent else None,
        )
        for c in campaigns
    ]
    segment_names = dict(
        (
            await db.execute(
                select(Campaign.id, Segment.name)
                .join(Segment, Segment.id == Campaign.segment_id)
                .where(Campaign.site_id == site_id)
            )
        ).all()
    )
    by_segment: dict[str, dict[str, int]] = {}
    for cid, agg in funnel.items():
        name = segment_names.get(cid)
        if not name:
            continue
        conv = conv_by_campaign.get(cid, {"converted": 0})
        bucket = by_segment.setdefault(
            name, {"sent": 0, "opened": 0, "clicked": 0, "converted": 0}
        )
        bucket["sent"] += agg["sent"]
        bucket["opened"] += agg["opened"]
        bucket["clicked"] += agg["clicked"]
        bucket["converted"] += conv["converted"]
    whats_working.extend(
        WhatsWorkingRow(
            kind="segment",
            label=name,
            sent=agg["sent"],
            clicked=agg["clicked"],
            converted=agg["converted"],
            conversion_rate=(
                round(agg["converted"] / agg["sent"], 4) if agg["sent"] else 0.0
            ),
            open_rate=round(agg["opened"] / agg["sent"], 4) if agg["sent"] else None,
        )
        for name, agg in by_segment.items()
        if agg["sent"] or agg["converted"]
    )
    whats_working.sort(key=lambda r: (r.converted, r.sent), reverse=True)

    # Absolute pooled category average only — no period-over-period delta.
    benchmark = None
    if settings.campaign_benchmark_enabled:
        from apps.api.services.campaign_benchmark import benchmark_for_category

        site_row = (
            await db.execute(
                select(Site.category, Site.benchmark_contribution_enabled).where(
                    Site.site_id == site_id
                )
            )
        ).first()
        if site_row is not None and site_row[1]:
            row = await benchmark_for_category(db, site_row[0])
            if row is not None and row.sends:
                site_sent = sum(c.sent for c in campaigns)
                site_opened = sum(c.opened for c in campaigns)
                benchmark = BenchmarkComparison(
                    category=row.category_normalized,
                    site_open_rate=(
                        round(site_opened / site_sent, 4) if site_sent else None
                    ),
                    category_open_rate=round(row.opens / row.sends, 4),
                    caveat=OPEN_RATE_CAVEAT,
                )

    return OutcomesReportResponse(
        days=days,
        totals=totals,
        campaigns=campaigns,
        goals=goals,
        whats_working=whats_working,
        open_rate_caveat=OPEN_RATE_CAVEAT,
        benchmark=benchmark,
    )


@router.delete("/{site_id}/goals/{goal_id}", status_code=204)
async def delete_goal(
    site_id: str,
    goal_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a goal. FK CASCADE removes its recorded conversions with it."""
    await verify_site_access(db, site_id, user)
    goal = await _get_goal(db, site_id, goal_id)
    await db.delete(goal)
    await db.commit()
    logger.info("conversion_goal_deleted", site_id=site_id, goal_id=goal_id)
    return Response(status_code=204)


# ── Server-side conversion webhook ──


@router.post("/{site_id}/webhook-secret", response_model=WebhookSecretResponse)
async def rotate_webhook_secret(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WebhookSecretResponse:
    """Generate (or rotate) the site's webhook signing secret.

    The plaintext is returned exactly once — only the Fernet ciphertext and a
    display hint are stored. Rotating immediately invalidates the old secret.
    """
    site = await verify_site_access(db, site_id, user)
    secret = pysecrets.token_urlsafe(32)
    site.outcomes_webhook_secret_ciphertext = encrypt_key(secret)
    site.outcomes_webhook_secret_hint = make_key_hint(secret)
    await db.commit()
    logger.info("outcomes_webhook_secret_rotated", site_id=site_id)
    return WebhookSecretResponse(secret=secret, hint=site.outcomes_webhook_secret_hint)


@router.get("/{site_id}/webhook-config", response_model=WebhookConfigResponse)
async def get_webhook_config(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WebhookConfigResponse:
    site = await verify_site_access(db, site_id, user)
    return WebhookConfigResponse(
        configured=bool(site.outcomes_webhook_secret_ciphertext),
        hint=site.outcomes_webhook_secret_hint,
        url=f"{settings.api_base_url.rstrip('/')}/api/v1/outcomes/{site_id}/webhook",
    )


@router.post("/{site_id}/webhook", response_model=OutcomeWebhookResponse, status_code=202)
@limiter.limit("60/minute")
async def outcomes_webhook(
    site_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> OutcomeWebhookResponse:
    """Record a conversion from the customer's server (Stripe/Zapier/backend).

    NO bearer auth — verified via ``X-Beam-Signature``: hex HMAC-SHA256 of the
    raw request body with the site's webhook secret (billing-webhook pattern).
    Payload: {goal, email|visitor_id, value?, occurred_at?, event_id?}.

    Demo-booking v2 route (NOT implemented in v1): a booking provider
    (Calendly / Cal.com) can POST its booking event straight here, giving
    attribution without ever handing a third party Beam's encrypted ``_bid``
    click token. v1 instead relies on the customer redirecting their booking
    confirmation to their own pixel'd thank-you page, matched by a "Demo booked"
    url_match ConversionGoal. See process/features/campaigns-outreach/backlog/
    third-party-link-attribution_NOTE_16-08-26.md.
    """
    body = await request.body()

    site = (
        await db.execute(select(Site).where(Site.site_id == site_id))
    ).scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    if not site.outcomes_webhook_secret_ciphertext:
        raise HTTPException(status_code=503, detail="Webhook not configured for this site")

    signature = request.headers.get("X-Beam-Signature")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing X-Beam-Signature header")
    try:
        secret = decrypt_key(site.outcomes_webhook_secret_ciphertext)
    except ValueError:
        logger.error("outcomes_webhook_secret_undecryptable", site_id=site_id)
        raise HTTPException(status_code=503, detail="Webhook secret unavailable")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature.strip().lower()):
        logger.warning("outcomes_webhook_invalid_signature", site_id=site_id)
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        payload = OutcomeWebhookPayload.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {exc.errors()[0].get('msg', 'validation error')}")

    goal = (
        await db.execute(
            select(ConversionGoal).where(
                ConversionGoal.site_id == site_id,
                func.lower(ConversionGoal.name) == payload.goal.strip().lower(),
                ConversionGoal.enabled.is_(True),
            )
        )
    ).scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found or disabled")

    # Resolve the visitor: explicit id wins; else the most recent visitor who
    # used this email on this site (blind-index lookup — never plaintext); else
    # mint the stable per-email id, SAME derivation as the click redirect
    # (routers/click.py), so ESP-click-minted identities join up for free.
    from apps.api.services.pii_crypto import email_hash

    if payload.visitor_id:
        visitor_id = payload.visitor_id
    else:
        email = (payload.email or "").strip().lower()
        bidx = email_hash(email)
        known = (
            await db.execute(
                select(VisitorEmail.visitor_id)
                .where(
                    VisitorEmail.site_id == site_id,
                    VisitorEmail.email_bidx == bidx,
                )
                .order_by(VisitorEmail.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        visitor_id = known or ("ec" + bidx[:30])

    occurred_at = payload.occurred_at or datetime.now(timezone.utc)
    if occurred_at.tzinfo:
        occurred_at = occurred_at.replace(tzinfo=None)
    value_cents = round(payload.value * 100) if payload.value is not None else None

    recorded, attribution = await record_conversion(
        db,
        site_id=site_id,
        goal=goal,
        visitor_id=visitor_id,
        occurred_at=occurred_at,
        value_cents=value_cents,
        source="webhook",
        event_id=payload.event_id,
    )
    await db.commit()
    logger.info(
        "outcomes_webhook_received",
        site_id=site_id,
        goal=goal.name,
        recorded=recorded,
        attributed=attribution is not None,
    )
    return OutcomeWebhookResponse(recorded=recorded, attributed=attribution is not None)
