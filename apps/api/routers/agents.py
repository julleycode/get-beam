import hmac
import uuid

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
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
    FetchBeaconIn,
)
from apps.api.services.agent_aggregator import (
    aggregate_agent_analytics,
    fetch_agent_visit_rows,
    fetch_handoff_confidence_split,
    fetch_handoff_denominator,
    fetch_handoff_links_count,
    fetch_recent_ai_researched_companies,
)
from apps.api.services.agent_fetch_beacon import record_fetch_beacon

logger = structlog.get_logger()

router = APIRouter()


def _verify_beacon_secret(
    x_beam_fetch_secret: str | None = Header(default=None),
) -> None:
    """Shared-secret auth for the H5 fetch beacon. 401 on any failure.

    Order is SECURITY-CRITICAL (VALIDATE E2):

    1. Empty configured secret => 401 FIRST, BEFORE any ``hmac.compare_digest``.
       ``hmac.compare_digest('', '')`` returns ``True``, so comparing an empty
       header against an empty configured secret would ACCEPT it — an auth
       bypass. The endpoint must be dormant (reject all) when unconfigured.
    2. Empty/absent provided header => 401.
    3. Constant-time compare (mismatch => 401).
    """
    configured = settings.beam_fetch_beacon_secret
    if not configured:
        raise HTTPException(status_code=401, detail="unauthorized")
    if not x_beam_fetch_secret:
        raise HTTPException(status_code=401, detail="unauthorized")
    if not hmac.compare_digest(x_beam_fetch_secret, configured):
        raise HTTPException(status_code=401, detail="unauthorized")


@router.post("/fetch-beacon")
async def fetch_beacon(
    payload: FetchBeaconIn,
    _auth: None = Depends(_verify_beacon_secret),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Authenticated server-side AI-fetch beacon (Handoff Detection H5).

    Registered BEFORE the GET ``/{site_id}`` catch-alls (distinct HTTP method, so
    no real collision, but explicit for clarity). Auth via the shared-secret
    dependency (NO Clerk). Dormant when the flag is off (404 — endpoint not
    revealed). On success maps the service sentinel: ``"written"`` => 202,
    ``"noop"`` => 204. Never 403 for an unknown site (no id-existence leak).
    """
    if not settings.agent_fetch_beacon_enabled:
        # Dormant: do not reveal the endpoint exists when disabled.
        raise HTTPException(status_code=404, detail="Not Found")

    result = await record_fetch_beacon(db, payload)
    return Response(status_code=202 if result == "written" else 204)


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
    handoff_confidence = await fetch_handoff_confidence_split(db, site_id)
    on_demand_fetch_count = await fetch_handoff_denominator(db, site_id)
    recent_ai_researched = await fetch_recent_ai_researched_companies(db, site_id)
    result = aggregate_agent_analytics(
        rows,
        handoff_links_count,
        recent_ai_researched,
        handoff_confidence=handoff_confidence,
        on_demand_fetch_count=on_demand_fetch_count,
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
