"""Dashboard aggregate endpoints.

Collapses the Overview page's fan-out (sites list + per-site visitor stats)
into ONE round-trip. Matters most for clients far from the origin (e.g. a VN
operator hitting the US backend): one request instead of N, with every per-site
query run server-side next to the database instead of over the ocean.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.database import get_db
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.dependencies import get_current_user
from apps.api.schemas.sites import SiteOut
from apps.api.schemas.visitors import VisitorStatsResponse
from apps.api.routers.visitors import _compute_visitor_stat_counts
from apps.api.services.usage_limits import check_identify_budget

router = APIRouter()


class DashboardOverview(BaseModel):
    sites: list[SiteOut]
    # Per-site visitor stats, keyed by site_id. Same shape as
    # GET /api/v1/visitors/{site_id}/stats so the frontend can reuse it.
    stats: dict[str, VisitorStatsResponse]


@router.get("/overview", response_model=DashboardOverview)
async def get_overview(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardOverview:
    """Sites + per-site stats in one call (replaces the Overview N+1 fan-out)."""
    sites = (
        (await db.execute(select(Site).where(Site.user_id == user.id)))
        .scalars()
        .all()
    )

    # ponytail: sequential per-site loop. One AsyncSession can't run concurrent
    # queries, and real accounts have 1-3 sites; these run US-local (fast). If a
    # single account ever has many sites, give each its own session + gather.
    stats: dict[str, VisitorStatsResponse] = {}
    for site in sites:
        counts = await _compute_visitor_stat_counts(db, site.site_id)
        budget = await check_identify_budget(db, site.site_id, user.id)
        stats[site.site_id] = VisitorStatsResponse(
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

    return DashboardOverview(
        sites=[SiteOut.model_validate(s) for s in sites],
        stats=stats,
    )
