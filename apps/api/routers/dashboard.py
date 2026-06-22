"""Dashboard aggregate endpoints.

Collapses the Overview page's fan-out (sites list + per-site visitor stats)
into ONE round-trip. Matters most for clients far from the origin (e.g. a VN
operator hitting the US backend): one request instead of N, with every per-site
query run server-side next to the database instead of over the ocean.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.database import get_db
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.dependencies import get_current_user
from apps.api.schemas.sites import SiteOut
from apps.api.schemas.visitors import VisitorStatsResponse
from apps.api.services.usage_limits import _today_start, is_full_byok

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
    """Sites + per-site stats in one call (replaces the Overview N+1 fan-out).

    Runs a FIXED number of queries regardless of how many sites the user owns:
    the old per-site loop issued ``1 + 5*N`` queries serially (a killer over a
    cross-region link); this batches everything with ``GROUP BY site_id`` into
    1 (sites) + 1 (BYOK, user-level) + 3 (grouped counts) = 5 queries total.
    A single AsyncSession can't run queries concurrently, so fewer round-trips
    (not asyncio.gather, which would also exhaust the size-3 pool) is the win.

    Per-site numbers MUST stay identical to GET /visitors/{site_id}/stats — the
    filters below mirror ``_compute_visitor_stat_counts`` + ``check_identify_budget``.
    """
    sites = (
        (await db.execute(select(Site).where(Site.user_id == user.id)))
        .scalars()
        .all()
    )
    if not sites:
        return DashboardOverview(sites=[], stats={})

    site_ids = [s.site_id for s in sites]

    # BYOK status is user-level, not per-site — compute once (the old loop
    # re-ran this query for every site).
    byok = await is_full_byok(db, user.id)
    today = await _today_start()

    # Visitor conditional aggregates, all five collapsed into one grouped scan.
    visitor_rows = (
        await db.execute(
            select(
                Visitor.site_id,
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
            .where(Visitor.site_id.in_(site_ids))
            .group_by(Visitor.site_id)
        )
    ).all()
    visitor_map = {row.site_id: row for row in visitor_rows}

    # could_enrich_more: low-completeness enrichment profiles (separate table).
    enrich_rows = (
        await db.execute(
            select(EnrichmentProfile.site_id, func.count().label("count"))
            .where(
                EnrichmentProfile.site_id.in_(site_ids),
                EnrichmentProfile.enrichment_completeness < 0.6,
            )
            .group_by(EnrichmentProfile.site_id)
        )
    ).all()
    enrich_map = {row.site_id: row.count for row in enrich_rows}

    # Identifications performed today (the daily-quota "used" meter).
    usage_rows = (
        await db.execute(
            select(IdentifiedVisitor.site_id, func.count().label("count"))
            .where(
                IdentifiedVisitor.site_id.in_(site_ids),
                IdentifiedVisitor.resolved_at >= today,
            )
            .group_by(IdentifiedVisitor.site_id)
        )
    ).all()
    usage_map = {row.site_id: row.count for row in usage_rows}

    stats: dict[str, VisitorStatsResponse] = {}
    for site in sites:
        counts = visitor_map.get(site.site_id)
        budget = (
            site.daily_resolution_budget
            if site.daily_resolution_budget is not None
            else settings.default_daily_resolution_budget
        )
        stats[site.site_id] = VisitorStatsResponse(
            total_visitors=counts.total if counts else 0,
            identified=counts.identified if counts else 0,
            enriched=counts.enriched if counts else 0,
            could_enrich_more=enrich_map.get(site.site_id, 0),
            enriched_unsegmented=counts.enriched_unsegmented if counts else 0,
            eligible_for_resolution=counts.eligible_for_resolution if counts else 0,
            identify_used_today=usage_map.get(site.site_id, 0),
            # check_identify_budget: limit is None (unlimited) for BYOK users.
            identify_daily_limit=None if byok else budget,
            identify_is_byok=byok,
        )

    return DashboardOverview(
        sites=[SiteOut.model_validate(s) for s in sites],
        stats=stats,
    )
