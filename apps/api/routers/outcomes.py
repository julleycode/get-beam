"""Conversion goals CRUD + outcomes reporting.

Goals are per-site, owner-scoped definitions of "what counts as a conversion"
(URL match today; JS event / webhook sources arrive in a later phase). The
event-ingest path (services/conversion_tracker) matches pageviews against the
enabled goals and records attributed conversions.
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_user, verify_site_access
from apps.api.models.database import get_db
from apps.api.models.outcome import ConversionGoal
from apps.api.models.user import User
from apps.api.schemas.outcomes import (
    GoalCreate,
    GoalListResponse,
    GoalOut,
    GoalUpdate,
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
