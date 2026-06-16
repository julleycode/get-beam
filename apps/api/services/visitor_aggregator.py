import math
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.visitor import Visitor

logger = structlog.get_logger()

FUNNEL_STAGES: dict[int, list[str]] = {
    1: ["home", "blog", "about"],
    2: ["features", "how-it-works", "use-cases", "integrations"],
    3: ["pricing", "plans", "comparison", "demo", "contact"],
    4: ["signup", "checkout", "buy", "subscribe", "trial"],
}

SOCIAL_DOMAINS = ("twitter", "facebook", "linkedin", "x.com", "t.co", "fb.com")
SEARCH_DOMAINS = ("google", "bing", "duckduckgo", "yahoo", "baidu")


def _is_homepage(page: str) -> bool:
    from urllib.parse import urlparse
    try:
        path = urlparse(page).path if "://" in page else page
    except Exception:
        path = page
    return path.rstrip("/") == ""


def _classify_funnel_stages(pages_visited: list[str]) -> set[int]:
    stages_hit: set[int] = set()
    for page in pages_visited:
        if _is_homepage(page):
            stages_hit.add(1)
            continue
        lower = page.lower()
        for stage, keywords in FUNNEL_STAGES.items():
            if any(kw in lower for kw in keywords):
                stages_hit.add(stage)
    return stages_hit


def _score_referrer(
    top_referrer: str | None,
    utm_source: str | None,
    utm_medium: str | None,
) -> float:
    medium = (utm_medium or "").lower()
    ref = (top_referrer or "").lower()
    source = (utm_source or "").lower()

    if medium in ("cpc", "ppc", "paid"):
        return 3.0
    if medium == "email":
        return 8.0
    if medium == "social" or any(d in ref for d in SOCIAL_DOMAINS):
        return 3.0

    if any(d in ref for d in SEARCH_DOMAINS) or any(d in source for d in SEARCH_DOMAINS):
        return 10.0
    if not ref or ref == "direct":
        return 10.0

    if ref:
        return 5.0

    return 0.0


def _decay_multiplier(last_seen: datetime) -> float:
    now = datetime.now(timezone.utc)
    if last_seen.tzinfo is None:
        now = datetime.utcnow()
    hours = (now - last_seen).total_seconds() / 3600

    if hours < 24:
        return 1.0
    if hours < 168:
        return 0.9
    if hours < 720:
        return 0.7
    if hours < 2160:
        return 0.4
    return 0.2


def calculate_intent_score(
    first_seen: datetime,
    last_seen: datetime,
    total_sessions: int,
    max_scroll_depth: int,
    avg_time_on_page: float,
    pages_visited: list[str],
    top_referrer: str | None = None,
    utm_source: str | None = None,
    utm_medium: str | None = None,
) -> float:
    score = 0.0

    if total_sessions >= 3:
        score += 25
    elif total_sessions >= 2:
        score += 15

    if max_scroll_depth >= 75:
        score += 15

    if avg_time_on_page > 60:
        score += 10

    if total_sessions >= 2:
        if first_seen.tzinfo is None:
            fs = first_seen
            ls = last_seen.replace(tzinfo=None) if last_seen.tzinfo else last_seen
        else:
            fs = first_seen
            ls = last_seen if last_seen.tzinfo else last_seen.replace(tzinfo=first_seen.tzinfo)
        span_days = max((ls - fs).total_seconds() / 86400, 0)
        avg_gap = span_days / max(total_sessions - 1, 1)
        if avg_gap < 2:
            score += 15
        elif avg_gap < 5:
            score += 8

    stages = _classify_funnel_stages(pages_visited)
    stage_count = len(stages)
    if stage_count >= 4:
        score += 15
    elif stage_count == 3:
        score += 10
    elif stage_count == 2:
        score += 5

    score += _score_referrer(top_referrer, utm_source, utm_medium)

    decay = _decay_multiplier(last_seen)
    return min(score * decay, 100.0)


def _strip_tz(dt: datetime) -> datetime:
    """Strip timezone info to match TIMESTAMP WITHOUT TIME ZONE columns."""
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


async def _upsert_visitor(
    db: AsyncSession,
    site_id: str,
    visitor_id: str,
    first_seen: datetime,
    last_seen: datetime,
    total_pageviews: int,
    total_sessions: int,
    max_scroll_depth: int,
    avg_time_on_page: float,
    pages_visited: list[str],
    top_referrer: str | None,
    utm_source: str | None,
    utm_medium: str | None,
    country_code: str | None,
    device_type: str | None,
    ip_address: str | None,
    do_not_resolve: bool = False,
) -> None:
    """Upsert a single visitor row into the visitors table."""
    if avg_time_on_page is None or (isinstance(avg_time_on_page, float) and math.isnan(avg_time_on_page)):
        avg_time_on_page = 0.0

    intent = calculate_intent_score(
        first_seen=first_seen.replace(tzinfo=timezone.utc) if first_seen.tzinfo is None else first_seen,
        last_seen=last_seen.replace(tzinfo=timezone.utc) if last_seen.tzinfo is None else last_seen,
        total_sessions=total_sessions,
        max_scroll_depth=max_scroll_depth,
        avg_time_on_page=avg_time_on_page,
        pages_visited=pages_visited or [],
        top_referrer=top_referrer,
        utm_source=utm_source,
        utm_medium=utm_medium,
    )

    first_seen = _strip_tz(first_seen)
    last_seen = _strip_tz(last_seen)

    stmt = pg_insert(Visitor).values(
        site_id=site_id,
        visitor_id=visitor_id,
        first_seen=first_seen,
        last_seen=last_seen,
        total_pageviews=total_pageviews,
        total_sessions=total_sessions,
        avg_time_on_page=avg_time_on_page,
        max_scroll_depth=max_scroll_depth,
        pages_visited=pages_visited or [],
        top_referrer=top_referrer or None,
        utm_source=utm_source or None,
        utm_medium=utm_medium or None,
        country_code=country_code or None,
        device_type=device_type or None,
        ip_address=ip_address or None,
        intent_score=intent,
        do_not_resolve=do_not_resolve,
    ).on_conflict_do_update(
        index_elements=["site_id", "visitor_id"],
        set_={
            "last_seen": last_seen,
            # Full recompute each run → SET totals (not increment) to avoid double-counting.
            "total_pageviews": total_pageviews,
            "total_sessions": total_sessions,
            "avg_time_on_page": avg_time_on_page,
            "max_scroll_depth": text("GREATEST(visitors.max_scroll_depth, :new_scroll)").bindparams(new_scroll=max_scroll_depth),
            "pages_visited": pages_visited or [],
            "ip_address": ip_address or Visitor.ip_address,
            "intent_score": intent,
            # Sticky opt-out: once true it stays true, even if a later recompute
            # sees events without the flag (e.g. a different browser/session).
            "do_not_resolve": text("visitors.do_not_resolve OR EXCLUDED.do_not_resolve"),
            "updated_at": datetime.utcnow(),
        },
    )
    await db.execute(stmt)


async def aggregate_visitors_for_site(db: AsyncSession, site_id: str) -> int:
    """Aggregate visitors from the PostgreSQL events table.

    Uses window functions to detect real session boundaries:
    a new session starts when there is a gap > 30 minutes between consecutive events.

    Aggregates the FULL event history per visitor (idempotent recompute) so the
    intent score and pages_visited reflect all activity, not just a recent window.
    Totals are SET (not incremented) on conflict — see _upsert_visitor.
    """
    # Check if events table exists
    check = await db.execute(text(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'events')"
    ))
    if not check.scalar():
        return 0

    # Session-aware aggregation using window functions:
    # 1. Detect session boundaries (gap > 30 min between events)
    # 2. Count distinct sessions per visitor
    # 3. Extract latest IP address
    result = await db.execute(text("""
        WITH session_boundaries AS (
            SELECT
                visitor_id, created_at, event_type, url, referrer,
                utm_source, utm_medium, country_code, device_type,
                scroll_depth, time_on_page, ip_address, optout,
                CASE
                    WHEN created_at - LAG(created_at) OVER (
                        PARTITION BY visitor_id ORDER BY created_at
                    ) > INTERVAL '30 minutes' THEN 1
                    ELSE 0
                END AS is_new_session
            FROM events
            WHERE site_id = :site_id
        ),
        session_numbered AS (
            SELECT *,
                SUM(is_new_session) OVER (
                    PARTITION BY visitor_id ORDER BY created_at
                ) + 1 AS session_num
            FROM session_boundaries
        )
        SELECT
            visitor_id,
            MIN(created_at) AS first_seen,
            MAX(created_at) AS last_seen,
            COUNT(*) FILTER (WHERE event_type = 'pageview') AS total_pageviews,
            MAX(session_num) AS total_sessions,
            COALESCE(MAX(scroll_depth), 0) AS max_scroll_depth,
            COALESCE(AVG(time_on_page) FILTER (WHERE time_on_page > 0), 0) AS avg_time_on_page,
            ARRAY_AGG(DISTINCT url) FILTER (WHERE event_type = 'pageview' AND url != '') AS pages_visited,
            MAX(referrer) FILTER (WHERE referrer != '') AS top_referrer,
            MAX(utm_source) FILTER (WHERE utm_source != '') AS utm_source,
            MAX(utm_medium) FILTER (WHERE utm_medium != '') AS utm_medium,
            MAX(country_code) FILTER (WHERE country_code != '') AS country_code,
            MAX(device_type) FILTER (WHERE device_type != '') AS device_type,
            (ARRAY_AGG(ip_address ORDER BY created_at DESC) FILTER (WHERE ip_address != ''))[1] AS latest_ip,
            BOOL_OR(optout) AS do_not_resolve
        FROM session_numbered
        GROUP BY visitor_id
    """), {"site_id": site_id})

    count = 0
    for row in result.fetchall():
        (
            visitor_id, first_seen, last_seen, total_pageviews,
            total_sessions, max_scroll_depth, avg_time_on_page, pages_visited,
            top_referrer, utm_source, utm_medium, country_code, device_type,
            latest_ip, do_not_resolve,
        ) = row

        await _upsert_visitor(
            db, site_id, visitor_id,
            first_seen or datetime.utcnow(),
            last_seen or datetime.utcnow(),
            total_pageviews or 0,
            total_sessions or 1,
            max_scroll_depth or 0,
            avg_time_on_page or 0.0,
            pages_visited or [],
            top_referrer, utm_source, utm_medium, country_code, device_type,
            latest_ip,
            do_not_resolve=bool(do_not_resolve),
        )
        count += 1

    await db.commit()

    # Phase 4: Resolve IP → company domain for visitors that don't have one yet
    await _resolve_companies(db, site_id)

    logger.info("visitors_aggregated", site_id=site_id, count=count)
    return count


async def _resolve_companies(db: AsyncSession, site_id: str) -> None:
    """Resolve company domains from IP for visitors missing company_domain."""
    try:
        from apps.api.services.company_resolver import resolve_company_cached

        # Get visitors with IP but no company_domain (limit 20 per run to avoid slowdowns)
        result = await db.execute(
            select(Visitor).where(
                Visitor.site_id == site_id,
                Visitor.ip_address.isnot(None),
                Visitor.ip_address != "",
                (Visitor.company_domain.is_(None)) | (Visitor.company_domain == ""),
            ).limit(20)
        )
        visitors = result.scalars().all()

        if not visitors:
            return

        resolved = 0
        for visitor in visitors:
            domain = await resolve_company_cached(visitor.ip_address)
            if domain:
                visitor.company_domain = domain
                resolved += 1

                # Upsert into companies table
                await _upsert_company(db, site_id, domain, visitor)

        if resolved:
            await db.commit()
            logger.info("companies_resolved", site_id=site_id, resolved=resolved, total=len(visitors))

    except Exception as e:
        logger.warning("company_resolution_failed", site_id=site_id, error=str(e))


async def _upsert_company(
    db: AsyncSession,
    site_id: str,
    domain: str,
    visitor: Visitor,
) -> None:
    """Upsert a company row from a resolved visitor."""
    from apps.api.models.company import Company

    stmt = pg_insert(Company).values(
        site_id=site_id,
        domain=domain,
        total_visitors=1,
        total_sessions=visitor.total_sessions or 1,
        total_pageviews=visitor.total_pageviews or 0,
        intent_score=visitor.intent_score or 0.0,
        first_seen=visitor.first_seen or datetime.utcnow(),
        last_seen=visitor.last_seen or datetime.utcnow(),
    ).on_conflict_do_update(
        index_elements=["site_id", "domain"],
        set_={
            "total_visitors": text("companies.total_visitors + 1"),
            "total_sessions": text("companies.total_sessions + EXCLUDED.total_sessions"),
            "total_pageviews": text("companies.total_pageviews + EXCLUDED.total_pageviews"),
            "intent_score": text(
                "LEAST("
                "  GREATEST(companies.intent_score, EXCLUDED.intent_score)"
                "  + LEAST(companies.intent_score, EXCLUDED.intent_score) * 0.3,"
                "  100)"
            ),
            "last_seen": text("GREATEST(companies.last_seen, EXCLUDED.last_seen)"),
            "updated_at": datetime.utcnow(),
        },
    )
    await db.execute(stmt)
