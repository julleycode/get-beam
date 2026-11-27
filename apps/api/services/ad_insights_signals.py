"""Read-only on-site / AEO signals for content opportunities (B2).

Site-scoped SELECTs only: top pages AI agents fetch (``agent_fetch_events``
per-hit rows — ``agent_visits`` has no per-page counts, G-9) and which AI
answer surfaces referred humans (``Visitor.ai_source``). Never writes.
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.agent_fetch_event import AgentFetchEvent
from apps.api.models.visitor import Visitor

_WINDOW_DAYS = 30
_TOP_PAGES = 10


def url_path(value: str | None) -> str:
    """Path only — no scheme/host/query/fragment (G-6: works for path-only input)."""
    if not value:
        return ""
    try:
        return urlsplit(str(value)).path or "/"
    except ValueError:
        return ""


async def top_agent_pages(db: AsyncSession, site_id: str) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=_WINDOW_DAYS)
    rows = await db.execute(
        select(AgentFetchEvent.page_path, func.count().label("n"))
        .where(
            AgentFetchEvent.site_id == site_id,
            AgentFetchEvent.page_path.isnot(None),
            AgentFetchEvent.created_at >= cutoff,
        )
        .group_by(AgentFetchEvent.page_path)
        .order_by(func.count().desc(), AgentFetchEvent.page_path)
        .limit(_TOP_PAGES * 3)
    )
    merged: dict[str, int] = {}
    for path, n in rows.all():
        p = url_path(path)
        if p:
            merged[p] = merged.get(p, 0) + int(n)
    ordered = sorted(merged.items(), key=lambda kv: (-kv[1], kv[0]))[:_TOP_PAGES]
    return [{"path": p, "agent_fetches": n} for p, n in ordered]


async def ai_source_counts(db: AsyncSession, site_id: str) -> dict[str, int]:
    cutoff = datetime.utcnow() - timedelta(days=_WINDOW_DAYS)
    rows = await db.execute(
        select(Visitor.ai_source, func.count())
        .where(
            Visitor.site_id == site_id,
            Visitor.ai_source.isnot(None),
            Visitor.last_seen >= cutoff,
        )
        .group_by(Visitor.ai_source)
    )
    return {str(src): int(n) for src, n in rows.all()}


async def collect_signals(db: AsyncSession, site_id: str, landing_urls: list[str]) -> dict:
    pages = await top_agent_pages(db, site_id)
    by_path = {p["path"]: p["agent_fetches"] for p in pages}
    matches = []
    for u in dict.fromkeys(url_path(x) for x in landing_urls if x):
        if u:
            matches.append({"path": u, "agent_fetches": by_path.get(u, 0)})
    return {
        "top_agent_pages": pages,
        "ai_sources": await ai_source_counts(db, site_id),
        "landing_page_matches": matches,
    }
