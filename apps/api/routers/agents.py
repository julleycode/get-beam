import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_user, verify_site_access as _verify_site_access
from apps.api.models.agent_visit import AgentVisit
from apps.api.models.database import get_db
from apps.api.models.user import User
from apps.api.schemas.agents import (
    AgentAnalyticsResponse,
    AgentDetailOut,
    AgentListResponse,
    AgentOut,
    AgentStatsResponse,
)
from apps.api.services.agent_aggregator import (
    aggregate_agent_analytics,
    fetch_agent_visit_rows,
    fetch_handoff_links_count,
    fetch_recent_ai_researched_companies,
)

logger = structlog.get_logger()

router = APIRouter()


@router.get("/{site_id}", response_model=AgentListResponse)
async def list_agents(
    site_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    vendor: str | None = None,
    verification_method: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentListResponse:
    await _verify_site_access(db, site_id, user)

    # AC6: query ONLY AgentVisit — never join Visitor/Event.
    query = select(AgentVisit).where(AgentVisit.site_id == site_id)
    count_query = (
        select(func.count()).select_from(AgentVisit).where(AgentVisit.site_id == site_id)
    )

    # Apply the same filter predicates to both the row query and the count query
    # so the paginated total always matches the filtered rows.
    filters = []
    if vendor is not None:
        filters.append(AgentVisit.vendor == vendor)
    if verification_method is not None:
        filters.append(AgentVisit.verification_method == verification_method)
    for predicate in filters:
        query = query.where(predicate)
        count_query = count_query.where(predicate)

    total = (await db.execute(count_query)).scalar_one()

    query = (
        query.order_by(AgentVisit.last_seen_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await db.execute(query)).scalars().all())
    agents = [AgentOut.model_validate(r) for r in rows]

    return AgentListResponse(agents=agents, total=total, page=page, page_size=page_size)


@router.get("/{site_id}/stats", response_model=AgentStatsResponse)
async def get_agent_stats(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentStatsResponse:
    """Aggregate agent-visit stats for a site: total visits, distinct vendors,
    and per-vendor visit counts.

    MUST be registered before the /{agent_visit_id} detail route — FastAPI
    matches routes in registration order and "stats" would otherwise be
    swallowed by the path-param catch-all (same sharp edge visitors.py avoids)."""
    await _verify_site_access(db, site_id, user)

    total_visits = (
        await db.execute(
            select(func.coalesce(func.sum(AgentVisit.visit_count), 0)).where(
                AgentVisit.site_id == site_id
            )
        )
    ).scalar_one()

    by_vendor_rows = await db.execute(
        select(AgentVisit.vendor, func.count().label("count"))
        .where(AgentVisit.site_id == site_id)
        .group_by(AgentVisit.vendor)
    )
    by_vendor = {row.vendor: row.count for row in by_vendor_rows}

    return AgentStatsResponse(
        total_visits=int(total_visits),
        distinct_vendors=len(by_vendor),
        by_vendor=by_vendor,
    )


@router.get("/{site_id}/analytics", response_model=AgentAnalyticsResponse)
async def get_agent_analytics(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentAnalyticsResponse:
    """Read-only GEO/AEO analytics snapshot for a site: per-vendor visit counts,
    top read pages, and verification-method split (SPEC AC11).

    Isolated from human data (SPEC AC2) — reads ONLY agent_visits, never
    Visitor/Event. MUST be registered before the /{agent_visit_id} detail route:
    FastAPI matches routes in registration order and "analytics" would otherwise
    be swallowed by the path-param catch-all (same sharp edge as /stats)."""
    await _verify_site_access(db, site_id, user)

    rows = await fetch_agent_visit_rows(db, site_id)
    handoff_links_count = await fetch_handoff_links_count(db, site_id)
    recent_ai_researched = await fetch_recent_ai_researched_companies(db, site_id)
    result = aggregate_agent_analytics(
        rows, handoff_links_count, recent_ai_researched
    )
    return AgentAnalyticsResponse(**result)


@router.get("/{site_id}/{agent_visit_id}", response_model=AgentDetailOut)
async def get_agent_detail(
    site_id: str,
    agent_visit_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentDetailOut:
    await _verify_site_access(db, site_id, user)

    # AgentVisit has no distinct business-id column — the only identifier is the
    # Base-inherited `id` UUID PK. Parse the path param as a UUID; a malformed id
    # returns 404 (never 500, never leak cross-tenant existence), same posture as
    # the not-found case below.
    try:
        parsed_id = uuid.UUID(agent_visit_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Agent visit not found")

    result = await db.execute(
        select(AgentVisit).where(
            AgentVisit.id == parsed_id, AgentVisit.site_id == site_id
        )
    )
    agent_visit = result.scalar_one_or_none()
    if not agent_visit:
        raise HTTPException(status_code=404, detail="Agent visit not found")

    return AgentDetailOut.model_validate(agent_visit)
