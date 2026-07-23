"""Read-only aggregation over ``AgentVisit`` rollup rows for the agents dashboard.

Structurally isolated from human Visitor/Event data (SPEC AC2): the fetch step
SELECTs ONLY from ``agent_visits`` and NEVER joins or queries ``visitors`` /
``events``. Mirrors the ``services.timeseries`` pure-split precedent — the DB
fetch (``fetch_agent_visit_rows``) is separated from the pure aggregation
(``aggregate_agent_analytics``) so the aggregation is unit-testable without a DB.
"""

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.agent_handoff_link import AgentHandoffLink
from apps.api.models.agent_visit import AgentVisit

logger = structlog.get_logger()


async def fetch_agent_visit_rows(db: AsyncSession, site_id: str) -> list[dict]:
    """Fetch the minimal agent-visit columns for a site as plain dicts.

    AC2 boundary: SELECTs ONLY from ``AgentVisit`` filtered by ``site_id`` — no
    join, no reference to ``Visitor``/``Event`` anywhere. Returns ``list[dict]``
    (not ORM rows) so ``aggregate_agent_analytics`` stays pure and DB-independent.
    """
    query = select(
        AgentVisit.vendor,
        AgentVisit.visit_count,
        AgentVisit.page_paths,
        AgentVisit.verification_method,
    ).where(AgentVisit.site_id == site_id)

    result = await db.execute(query)
    rows = [
        {
            "vendor": r.vendor,
            "visit_count": r.visit_count,
            "page_paths": r.page_paths,
            "verification_method": r.verification_method,
        }
        for r in result.all()
    ]
    logger.info("agent_analytics_fetched", site_id=site_id, rows=len(rows))
    return rows


async def fetch_handoff_links_count(db: AsyncSession, site_id: str) -> int:
    """Count fetch↔click handoff links for a site (Handoff Detection H2, AC-H2-4).

    Sibling DB-fetch to ``fetch_agent_visit_rows`` — keeps the DB read out of the
    pure ``aggregate_agent_analytics``. SELECTs ONLY from ``agent_handoff_links``
    filtered by ``site_id`` — no join, no ``Visitor``/``Event`` reference.
    """
    query = select(func.count()).select_from(AgentHandoffLink).where(
        AgentHandoffLink.site_id == site_id
    )
    result = await db.execute(query)
    return int(result.scalar() or 0)


def aggregate_agent_analytics(
    rows: list[dict], handoff_links_count: int, top_n: int = 10
) -> dict:
    """Pure aggregation over agent-visit rows — no DB, no I/O, unit-testable.

    ``handoff_links_count`` is passed in by the caller (fetched via the sibling
    ``fetch_handoff_links_count`` DB read) and echoed into the result dict,
    keeping this function's pure/no-DB contract intact.

    Returns a dict with four fields:
    - ``by_vendor``: sum of ``visit_count`` grouped by ``vendor``.
    - ``top_pages``: for each distinct path in any row's ``page_paths``, the sum
      of ``visit_count`` of every row containing it; sorted descending by count
      (ties keep first-seen order); the top ``top_n`` entries as
      ``{"path": str, "count": int}``.
    - ``by_verification``: sum of ``visit_count`` grouped by ``verification_method``.

    Edge cases: empty ``rows`` → all three empty; tied counts → stable
    (first-seen) order; fewer distinct paths than ``top_n`` → all of them.
    """
    by_vendor: dict[str, int] = {}
    by_verification: dict[str, int] = {}
    # Preserve first-seen order for stable tie-breaking in the ranked list.
    page_counts: dict[str, int] = {}

    for row in rows:
        count = int(row.get("visit_count") or 0)

        vendor = row.get("vendor")
        if vendor is not None:
            by_vendor[vendor] = by_vendor.get(vendor, 0) + count

        method = row.get("verification_method")
        if method is not None:
            by_verification[method] = by_verification.get(method, 0) + count

        # A path appearing multiple times in one row's page_paths counts once
        # for that row (distinct paths per row), so dedupe within the row.
        seen_in_row: set[str] = set()
        for path in row.get("page_paths") or []:
            if path in seen_in_row:
                continue
            seen_in_row.add(path)
            page_counts[path] = page_counts.get(path, 0) + count

    # Stable descending sort: Python's sort is stable, so equal counts retain
    # insertion (first-seen) order when we sort only by the negated count.
    ranked = sorted(page_counts.items(), key=lambda kv: -kv[1])
    top_pages = [{"path": path, "count": count} for path, count in ranked[:top_n]]

    return {
        "by_vendor": by_vendor,
        "top_pages": top_pages,
        "by_verification": by_verification,
        "handoff_links_count": handoff_links_count,
    }
