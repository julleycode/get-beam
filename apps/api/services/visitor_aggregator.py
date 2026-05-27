import math
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.visitor import Visitor

logger = structlog.get_logger()

HIGH_INTENT_KEYWORDS: list[str] = [
    "pricing", "checkout", "signup", "demo", "contact", "buy", "subscribe", "plan",
    "enterprise", "book", "plans", "quote",
]


def calculate_intent_score(
    last_seen: datetime,
    total_sessions: int,
    max_scroll_depth: int,
    avg_time_on_page: float,
    pages_visited: list[str],
) -> float:
    score = 0.0
    now = datetime.now(timezone.utc)
    # Handle both naive and aware datetimes
    if last_seen.tzinfo is None:
        now = datetime.utcnow()
    hours_since_last = (now - last_seen).total_seconds() / 3600

    if hours_since_last < 24:
        score += 30
    elif hours_since_last < 72:
        score += 20
    elif hours_since_last < 168:
        score += 10

    if total_sessions >= 3:
        score += 25
    elif total_sessions >= 2:
        score += 15

    if max_scroll_depth >= 75:
        score += 15
    if avg_time_on_page > 60:
        score += 10

    if any(kw in page.lower() for page in pages_visited for kw in HIGH_INTENT_KEYWORDS):
        score += 20

    return min(score, 100.0)


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
) -> None:
    """Upsert a single visitor row into the visitors table."""
    if avg_time_on_page is None or (isinstance(avg_time_on_page, float) and math.isnan(avg_time_on_page)):
        avg_time_on_page = 0.0

    intent = calculate_intent_score(
        last_seen=last_seen.replace(tzinfo=timezone.utc) if last_seen.tzinfo is None else last_seen,
        total_sessions=total_sessions,
        max_scroll_depth=max_scroll_depth,
        avg_time_on_page=avg_time_on_page,
        pages_visited=pages_visited or [],
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
    ).on_conflict_do_update(
        index_elements=["site_id", "visitor_id"],
        set_={
            "last_seen": last_seen,
            "total_pageviews": Visitor.total_pageviews + total_pageviews,
            "total_sessions": Visitor.total_sessions + total_sessions,
            "avg_time_on_page": avg_time_on_page,
            "max_scroll_depth": text("GREATEST(visitors.max_scroll_depth, :new_scroll)").bindparams(new_scroll=max_scroll_depth),
            "pages_visited": pages_visited or [],
            "ip_address": ip_address or Visitor.ip_address,
            "intent_score": intent,
            "updated_at": datetime.utcnow(),
        },
    )
    await db.execute(stmt)


async def aggregate_visitors_for_site(db: AsyncSession, site_id: str) -> int:
    """Aggregate visitors from the PostgreSQL events table.

    Uses window functions to detect real session boundaries:
    a new session starts when there is a gap > 30 minutes between consecutive events.
    """
    since = datetime.utcnow() - timedelta(hours=2)

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
                scroll_depth, time_on_page, ip_address,
                CASE
                    WHEN created_at - LAG(created_at) OVER (
                        PARTITION BY visitor_id ORDER BY created_at
                    ) > INTERVAL '30 minutes' THEN 1
                    ELSE 0
                END AS is_new_session
            FROM events
            WHERE site_id = :site_id AND created_at >= :since
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
            (ARRAY_AGG(ip_address ORDER BY created_at DESC) FILTER (WHERE ip_address != ''))[1] AS latest_ip
        FROM session_numbered
        GROUP BY visitor_id
    """), {"site_id": site_id, "since": since})

    count = 0
    for row in result.fetchall():
        (
            visitor_id, first_seen, last_seen, total_pageviews,
            total_sessions, max_scroll_depth, avg_time_on_page, pages_visited,
            top_referrer, utm_source, utm_medium, country_code, device_type,
            latest_ip,
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
        )
        count += 1

    await db.commit()
    logger.info("visitors_aggregated", site_id=site_id, count=count)
    return count
