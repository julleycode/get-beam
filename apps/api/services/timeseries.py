"""Per-day KPI time-series for one site — powers the "View as graph" widget.

Buckets the same funnel tiers as ``services.kpi`` (visitors → identified →
high-intent) by day of ``Visitor.last_seen`` over the trailing window, returning
a gap-filled continuous series so the line chart's x-axis has no missing days.
"""

from datetime import date, datetime, timedelta

import structlog
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.visitor import Visitor
from apps.api.services.identity_classification import VERIFIED_STATUSES
from apps.api.services.kpi import HIGH_INTENT

logger = structlog.get_logger()


def build_series(counts: dict, days: int, today: date) -> list:
    """Gap-fill a {``YYYY-MM-DD`` -> {metric: n}} map into a continuous list of
    ``days`` points ending on ``today`` (quiet days become zeros). Pure —
    unit-testable without a DB."""
    start = today - timedelta(days=days - 1)
    series = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        c = counts.get(d, {})
        series.append(
            {
                "date": d,
                "visitors": int(c.get("visitors", 0)),
                "identified": int(c.get("identified", 0)),
                "high_intent": int(c.get("high_intent", 0)),
            }
        )
    return series


async def compute_timeseries(db: AsyncSession, site_id: str, days: int = 30) -> dict:
    """Daily visitors / identified / high-intent counts over the trailing window.

    Aggregated in SQL by ``func.date(last_seen)``; the same naive-UTC window and
    predicates as ``compute_kpis`` so the chart matches the funnel numbers.
    """
    since = datetime.utcnow() - timedelta(days=days)
    day = func.date(Visitor.last_seen)
    # case()-sum instead of count().filter() for SQLite (tests) portability.
    # Trusted statuses only (verified + legacy identified) — not provider_candidate.
    identified_case = case((Visitor.identity_status.in_(VERIFIED_STATUSES), 1), else_=0)
    high_intent_case = case(
        (
            Visitor.identity_status.in_(VERIFIED_STATUSES)
            & (Visitor.intent_score >= HIGH_INTENT),
            1,
        ),
        else_=0,
    )
    result = await db.execute(
        select(
            day.label("date"),
            func.count().label("visitors"),
            func.sum(identified_case).label("identified"),
            func.sum(high_intent_case).label("high_intent"),
        )
        .where(Visitor.site_id == site_id, Visitor.last_seen >= since)
        .group_by(day)
        .order_by(day)
    )
    counts = {
        str(r.date)[:10]: {
            "visitors": int(r.visitors or 0),
            "identified": int(r.identified or 0),
            "high_intent": int(r.high_intent or 0),
        }
        for r in result.all()
    }

    series = build_series(counts, days, datetime.utcnow().date())
    logger.info("timeseries_computed", site_id=site_id, days=days, points=len(series))
    return {"site_id": site_id, "window_days": days, "series": series}
