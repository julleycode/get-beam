from datetime import datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import require_admin
from apps.api.models.api_usage import ApiUsageLog
from apps.api.models.database import get_db
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.schemas.costs import (
    CostCategoryRow,
    CostDayRow,
    CostProviderRow,
    CostSummaryResponse,
)

logger = structlog.get_logger()

router = APIRouter()


async def _verify_site_access(db: AsyncSession, site_id: str, user: User) -> Site:
    """A site belongs to exactly one user; 404 (not 403) if it isn't theirs so
    we don't leak which site_ids exist. Mirrors visitors._verify_site_access."""
    result = await db.execute(
        select(Site).where(Site.site_id == site_id, Site.user_id == user.id)
    )
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


# success is a Boolean column; sum a 1/0 case so one query yields both the call
# count and the success count without a second round-trip.
_SUCCESS_SUM = func.coalesce(
    func.sum(case((ApiUsageLog.success.is_(True), 1), else_=0)), 0
)
_COST_SUM = func.coalesce(func.sum(ApiUsageLog.cost_usd), 0.0)


@router.get("/{site_id}/summary", response_model=CostSummaryResponse)
async def get_cost_summary(
    site_id: str,
    days: int = Query(30, ge=1, le=365),
    category: str | None = Query(None),
    provider: str | None = Query(None),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CostSummaryResponse:
    """Total estimated API spend for a site over the last `days` days, read from
    the unified api_usage_logs ledger (identity + enrichment + osint).

    Optional `category` / `provider` narrow every rollup. Money figures are
    estimates — see services/api_pricing.py.
    """
    await _verify_site_access(db, site_id, user)

    # created_at is stored as naive UTC (see ApiUsageLog / events.py) — use a
    # naive cutoff so asyncpg binds it against the timestamp column. An aware
    # datetime here triggers "can't subtract offset-naive and offset-aware".
    since = datetime.utcnow() - timedelta(days=days)
    scope = [ApiUsageLog.site_id == site_id, ApiUsageLog.created_at >= since]
    if category:
        scope.append(ApiUsageLog.category == category)
    if provider:
        scope.append(ApiUsageLog.provider == provider)

    total_cost, total_calls, success_calls = (
        await db.execute(
            select(_COST_SUM, func.count(), _SUCCESS_SUM).where(*scope)
        )
    ).one()

    provider_rows = (
        await db.execute(
            select(ApiUsageLog.provider, func.count(), _COST_SUM, _SUCCESS_SUM)
            .where(*scope)
            .group_by(ApiUsageLog.provider)
            .order_by(_COST_SUM.desc())
        )
    ).all()

    category_rows = (
        await db.execute(
            select(ApiUsageLog.category, func.count(), _COST_SUM)
            .where(*scope)
            .group_by(ApiUsageLog.category)
            .order_by(_COST_SUM.desc())
        )
    ).all()

    # func.date() returns a date on Postgres and a str on SQLite — str() both.
    day = func.date(ApiUsageLog.created_at)
    day_rows = (
        await db.execute(
            select(day, func.count(), _COST_SUM)
            .where(*scope)
            .group_by(day)
            .order_by(day)
        )
    ).all()

    return CostSummaryResponse(
        site_id=site_id,
        days=days,
        total_usd=round(float(total_cost), 4),
        total_calls=int(total_calls),
        success_calls=int(success_calls),
        failed_calls=int(total_calls) - int(success_calls),
        by_provider=[
            CostProviderRow(
                provider=prov,
                calls=int(calls),
                cost_usd=round(float(cost), 4),
                success_rate=round(succ / calls, 4) if calls else 0.0,
            )
            for prov, calls, cost, succ in provider_rows
        ],
        by_category=[
            CostCategoryRow(
                category=cat,
                calls=int(calls),
                cost_usd=round(float(cost), 4),
            )
            for cat, calls, cost in category_rows
        ],
        by_day=[
            CostDayRow(
                date=str(d),
                calls=int(calls),
                cost_usd=round(float(cost), 4),
            )
            for d, calls, cost in day_rows
        ],
    )
