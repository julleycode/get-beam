"""Conversion goals CRUD + outcomes reporting.

Goals are per-site, owner-scoped definitions of "what counts as a conversion"
(URL match today; JS event / webhook sources arrive in a later phase). The
event-ingest path (services/conversion_tracker) matches pageviews against the
enabled goals and records attributed conversions.
"""

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_user, verify_site_access
from apps.api.models.campaign import Campaign, CampaignTouchpoint
from apps.api.models.database import get_db
from apps.api.models.outcome import Conversion, ConversionGoal
from apps.api.models.user import User
from apps.api.schemas.outcomes import (
    CampaignOutcomeRow,
    GoalCreate,
    GoalListResponse,
    GoalOut,
    GoalOutcomeRow,
    GoalUpdate,
    OutcomesReportResponse,
    OutcomeTotals,
    validate_goal_pattern,
)
from apps.api.services.conversion_tracker import MAX_GOALS_PER_SITE

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
                func.count()
                .filter(
                    CampaignTouchpoint.status == "sent",
                    CampaignTouchpoint.sent_at >= cutoff,
                )
                .label("sent"),
                func.count()
                .filter(
                    CampaignTouchpoint.opened_at.is_not(None),
                    CampaignTouchpoint.sent_at >= cutoff,
                )
                .label("opened"),
                func.count()
                .filter(
                    CampaignTouchpoint.clicked_at.is_not(None),
                    CampaignTouchpoint.sent_at >= cutoff,
                )
                .label("clicked"),
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

    return OutcomesReportResponse(days=days, totals=totals, campaigns=campaigns, goals=goals)


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
