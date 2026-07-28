"""Read-only aggregation over ``AgentVisit`` rollup rows for the agents dashboard.

Structurally isolated from human Visitor/Event data (SPEC AC2): the fetch step
SELECTs ONLY from ``agent_visits`` and NEVER joins or queries ``visitors`` /
``events``. Mirrors the ``services.timeseries`` pure-split precedent — the DB
fetch (``fetch_agent_visit_rows``) is separated from the pure aggregation
(``aggregate_agent_analytics``) so the aggregation is unit-testable without a DB.
"""

from datetime import timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.agent_fetch_event import AgentFetchEvent
from apps.api.models.agent_handoff_link import AgentHandoffLink
from apps.api.models.agent_visit import AgentVisit
from apps.api.models.company import Company
from apps.api.models.company_graph import CompanyGraphNode
from apps.api.services.agent_intent_signals import is_commercial_page

logger = structlog.get_logger()

# A company counts as "AI-researched" if it first appeared within this window
# AFTER an on-demand agent fetch of one of its commercial pages.
_RESEARCH_CORRELATION_HOURS = 48
# Read-side cap for the correlation list surfaced on the analytics response.
_RECENT_RESEARCH_CAP = 20


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


async def fetch_handoff_denominator(db: AsyncSession, site_id: str) -> int:
    """Count on-demand agent fetches for a site — the pool handoff links draw from.

    Without it a ``handoff_links_count`` of 0 is unreadable: it cannot distinguish
    "no agent ever fetched this site" from "agents fetched but no human click
    followed" from "the correlation is broken". Pairing the link count with the
    number of fetches that were eligible to produce one makes the zero legible.

    SELECTs only ``agent_fetch_events`` filtered by ``site_id`` — no join, no
    ``Visitor``/``Event`` reference (same isolation as the sibling fetches).
    """
    query = select(func.count()).select_from(AgentFetchEvent).where(
        AgentFetchEvent.site_id == site_id,
        AgentFetchEvent.tier == "on-demand",
    )
    result = await db.execute(query)
    return int(result.scalar() or 0)


async def fetch_handoff_confidence_split(
    db: AsyncSession, site_id: str
) -> dict[str, int]:
    """Break a site's handoff links down by confidence tier.

    The sweep writes both ``high`` and ``medium`` links, so a single total mixes
    an exact-page match seconds after the fetch with a page mismatch half an hour
    later. Callers surface the split rather than one number.
    """
    query = (
        select(AgentHandoffLink.confidence, func.count())
        .where(AgentHandoffLink.site_id == site_id)
        .group_by(AgentHandoffLink.confidence)
    )
    result = await db.execute(query)
    return {str(confidence): int(count) for confidence, count in result.all()}


async def fetch_recent_ai_researched_companies(
    db: AsyncSession, site_id: str
) -> list[dict]:
    """Correlate on-demand agent fetches of commercial pages to companies (H3, AC-H3-3).

    Read-only, on-read, NO storage: for the requesting ``site_id``, find ``Company``
    rows whose ``first_seen`` falls within 48h AFTER an on-demand
    ``AgentFetchEvent`` of a commercial page at the same site. This is pure
    metadata ("appeared after AI research") — it is NEVER a person-level claim and
    NEVER a write path into any campaign/outreach surface.

    Primary (and only) join: the durable cross-tenant ``company_graph`` table
    (``CompanyGraphNode.ip`` → ``domain``), gated by
    ``settings.company_graph_enabled``. Join is
    ``AgentFetchEvent.ip_address == CompanyGraphNode.ip`` AND
    ``CompanyGraphNode.domain == Company.domain`` AND ``Company.site_id == site_id``.
    A fetch event with no matching ``CompanyGraphNode`` row is simply excluded.

    KNOWN-GAP: if ``company_graph_enabled`` is False deployment-wide (the default),
    no queryable IP→company linkage exists at read time, so this degrades to an
    empty list rather than inventing a stored join (which would need a migration —
    out of scope this phase). Documented in the phase report either way.
    """
    if not settings.company_graph_enabled:
        return []

    window = timedelta(hours=_RESEARCH_CORRELATION_HOURS)
    # site_id-scoped via Company.site_id — CompanyGraphNode is cross-tenant (no
    # site column), so the Company join is what enforces tenant isolation.
    query = (
        select(
            Company.name.label("company_name"),
            Company.domain.label("domain"),
            AgentFetchEvent.page_path.label("matched_page"),
            AgentFetchEvent.created_at.label("researched_at"),
        )
        .select_from(AgentFetchEvent)
        .join(CompanyGraphNode, CompanyGraphNode.ip == AgentFetchEvent.ip_address)
        .join(Company, Company.domain == CompanyGraphNode.domain)
        .where(
            AgentFetchEvent.site_id == site_id,
            Company.site_id == site_id,
            AgentFetchEvent.tier == "on-demand",
            AgentFetchEvent.page_path.is_not(None),
            Company.first_seen >= AgentFetchEvent.created_at,
            Company.first_seen <= AgentFetchEvent.created_at + window,
        )
        .order_by(AgentFetchEvent.created_at.desc())
        # Over-fetch, then Python-filter by is_commercial_page (pure/no-SQL) and
        # cap — the commercial-prefix rule is not expressible in portable SQL.
        .limit(_RECENT_RESEARCH_CAP * 10)
    )
    result = await db.execute(query)

    entries: list[dict] = []
    for r in result.all():
        if not is_commercial_page(r.matched_page):
            continue
        entries.append(
            {
                "company_name": r.company_name or r.domain or "Unknown company",
                "domain": r.domain,
                "matched_page": r.matched_page,
                "researched_at": r.researched_at,
            }
        )
        if len(entries) >= _RECENT_RESEARCH_CAP:
            break

    logger.info(
        "ai_researched_companies_fetched", site_id=site_id, rows=len(entries)
    )
    return entries


def aggregate_agent_analytics(
    rows: list[dict],
    handoff_links_count: int,
    recent_ai_researched_companies: list[dict] | None = None,
    top_n: int = 10,
    handoff_confidence: dict[str, int] | None = None,
    on_demand_fetch_count: int = 0,
) -> dict:
    """Pure aggregation over agent-visit rows — no DB, no I/O, unit-testable.

    ``handoff_links_count``, ``handoff_confidence``, ``on_demand_fetch_count`` and
    ``recent_ai_researched_companies`` are passed in by the caller (fetched via the
    sibling ``fetch_handoff_links_count`` / ``fetch_handoff_confidence_split`` /
    ``fetch_handoff_denominator`` / ``fetch_recent_ai_researched_companies`` DB
    reads) and echoed into the result dict, keeping this function's pure/no-DB
    contract intact.

    Returns a dict with the vendor/page/verification aggregates plus the two
    echoed fields:
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
        # Context for the link count: how it splits by confidence, and how many
        # on-demand fetches it was drawn from. Without these a count of 0 cannot
        # be told apart from a correlation that never ran.
        "handoff_confidence": handoff_confidence or {},
        "on_demand_fetch_count": on_demand_fetch_count,
        # Echoed straight through (fetched via the sibling DB-read
        # fetch_recent_ai_researched_companies), keeping this function pure/no-DB.
        "recent_ai_researched_companies": recent_ai_researched_companies or [],
    }
