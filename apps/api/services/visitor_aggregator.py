import json
import math
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.visitor import Visitor
from apps.api.services.clickhouse_client import get_clickhouse_client

logger = structlog.get_logger()

HIGH_INTENT_KEYWORDS: list[str] = [
    "pricing", "checkout", "signup", "demo", "contact", "buy", "subscribe", "plan",
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
    max_scroll_depth: int,
    avg_time_on_page: float,
    pages_visited: list[str],
    top_referrer: str | None,
    utm_source: str | None,
    utm_medium: str | None,
    country_code: str | None,
    device_type: str | None,
) -> None:
    """Upsert a single visitor row into the visitors table."""
    if avg_time_on_page is None or (isinstance(avg_time_on_page, float) and math.isnan(avg_time_on_page)):
        avg_time_on_page = 0.0

    intent = calculate_intent_score(
        last_seen=last_seen.replace(tzinfo=timezone.utc) if last_seen.tzinfo is None else last_seen,
        total_sessions=1,
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
        total_sessions=1,
        avg_time_on_page=avg_time_on_page,
        max_scroll_depth=max_scroll_depth,
        pages_visited=pages_visited or [],
        top_referrer=top_referrer or None,
        utm_source=utm_source or None,
        utm_medium=utm_medium or None,
        country_code=country_code or None,
        device_type=device_type or None,
        intent_score=intent,
    ).on_conflict_do_update(
        index_elements=["site_id", "visitor_id"],
        set_={
            "last_seen": last_seen,
            "total_pageviews": Visitor.total_pageviews + total_pageviews,
            "total_sessions": Visitor.total_sessions + 1,
            "avg_time_on_page": avg_time_on_page,
            "max_scroll_depth": text(f"GREATEST(visitors.max_scroll_depth, {max_scroll_depth})"),
            "pages_visited": pages_visited or [],
            "intent_score": intent,
            "updated_at": datetime.utcnow(),
        },
    )
    await db.execute(stmt)


async def _aggregate_from_pg_fallback(db: AsyncSession, site_id: str) -> int:
    """Aggregate visitors from the events_fallback Postgres table."""
    since = datetime.utcnow() - timedelta(hours=2)

    # Check if events_fallback table exists
    check = await db.execute(text(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'events_fallback')"
    ))
    if not check.scalar():
        return 0

    result = await db.execute(text("""
        SELECT
            visitor_id,
            MIN((event_data->>'created_at')::timestamp) AS first_seen,
            MAX((event_data->>'created_at')::timestamp) AS last_seen,
            COUNT(*) FILTER (WHERE event_data->>'event_type' = 'pageview') AS total_pageviews,
            COALESCE(MAX((event_data->>'scroll_depth')::int), 0) AS max_scroll_depth,
            COALESCE(AVG((event_data->>'time_on_page')::float) FILTER (WHERE (event_data->>'time_on_page')::float > 0), 0) AS avg_time_on_page,
            ARRAY_AGG(DISTINCT event_data->>'url') FILTER (WHERE event_data->>'event_type' = 'pageview' AND event_data->>'url' != '') AS pages_visited,
            MAX(event_data->>'referrer') FILTER (WHERE event_data->>'referrer' != '') AS top_referrer,
            MAX(event_data->>'utm_source') FILTER (WHERE event_data->>'utm_source' != '') AS utm_source,
            MAX(event_data->>'utm_medium') FILTER (WHERE event_data->>'utm_medium' != '') AS utm_medium,
            MAX(event_data->>'country_code') FILTER (WHERE event_data->>'country_code' != '') AS country_code,
            MAX(event_data->>'device_type') FILTER (WHERE event_data->>'device_type' != '') AS device_type
        FROM events_fallback
        WHERE site_id = :site_id AND created_at >= :since
        GROUP BY visitor_id
    """), {"site_id": site_id, "since": since})

    count = 0
    for row in result.fetchall():
        (
            visitor_id, first_seen, last_seen, total_pageviews,
            max_scroll_depth, avg_time_on_page, pages_visited,
            top_referrer, utm_source, utm_medium, country_code, device_type,
        ) = row

        await _upsert_visitor(
            db, site_id, visitor_id,
            first_seen or datetime.utcnow(),
            last_seen or datetime.utcnow(),
            total_pageviews or 0,
            max_scroll_depth or 0,
            avg_time_on_page or 0.0,
            pages_visited or [],
            top_referrer, utm_source, utm_medium, country_code, device_type,
        )
        count += 1

    await db.commit()
    logger.info("visitors_aggregated_pg_fallback", site_id=site_id, count=count)
    return count


async def aggregate_visitors_for_site(db: AsyncSession, site_id: str) -> int:
    ch = get_clickhouse_client()
    if ch is None:
        # Use Postgres fallback instead of skipping
        return await _aggregate_from_pg_fallback(db, site_id)

    since = datetime.utcnow() - timedelta(hours=2)

    rows = ch.query(
        """
        SELECT
            visitor_id,
            min(created_at) AS first_seen,
            max(created_at) AS last_seen,
            countIf(event_type = 'pageview') AS total_pageviews,
            max(scroll_depth) AS max_scroll_depth,
            avgIf(time_on_page, time_on_page > 0) AS avg_time_on_page,
            groupUniqArrayIf(url, event_type = 'pageview') AS pages_visited,
            anyIf(referrer, referrer != '') AS top_referrer,
            anyIf(utm_source, utm_source != '') AS utm_source,
            anyIf(utm_medium, utm_medium != '') AS utm_medium,
            anyIf(country_code, country_code != '') AS country_code,
            anyIf(device_type, device_type != '') AS device_type
        FROM events
        WHERE site_id = %(site_id)s AND created_at >= %(since)s
        GROUP BY visitor_id
        """,
        parameters={"site_id": site_id, "since": since},
    )

    count = 0
    for row in rows.result_rows:
        (
            visitor_id, first_seen, last_seen, total_pageviews,
            max_scroll_depth, avg_time_on_page, pages_visited,
            top_referrer, utm_source, utm_medium, country_code, device_type,
        ) = row

        await _upsert_visitor(
            db, site_id, visitor_id,
            first_seen, last_seen, total_pageviews or 0,
            max_scroll_depth or 0, avg_time_on_page or 0.0,
            pages_visited or [], top_referrer, utm_source, utm_medium,
            country_code, device_type,
        )
        count += 1

    await db.commit()
    logger.info("visitors_aggregated", site_id=site_id, count=count)
    return count
