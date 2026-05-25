import json

import structlog
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.database import get_db
from apps.api.schemas.events import EventBatch
from apps.api.services.clickhouse_client import get_clickhouse_client

router = APIRouter()
logger = structlog.get_logger()


def _extract_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return ""


@router.post("/ingest", status_code=204)
async def ingest_events(
    batch: EventBatch, request: Request, db: AsyncSession = Depends(get_db)
) -> Response:
    ip_address = _extract_ip(request)
    client = get_clickhouse_client()

    rows: list[list[object]] = []
    for event in batch.events:
        rows.append([
            batch.site_id,
            batch.visitor_id,
            event.type,
            event.url or "",
            event.referrer or "",
            event.utm.source if event.utm and event.utm.source else "",
            event.utm.medium if event.utm and event.utm.medium else "",
            event.utm.campaign if event.utm and event.utm.campaign else "",
            "",  # country_code — filled by GeoIP later
            "",  # region
            event.device or "",
            event.lang or "",
            event.depth or 0,
            event.seconds or 0,
            event.element_text or "",
            event.element_href or "",
            ip_address,
            event.ts,
        ])

    column_names = [
        "site_id", "visitor_id", "event_type", "url", "referrer",
        "utm_source", "utm_medium", "utm_campaign", "country_code", "region",
        "device_type", "browser_lang", "scroll_depth", "time_on_page",
        "element_text", "element_href", "ip_address", "created_at",
    ]

    if client:
        try:
            client.insert("events", rows, column_names=column_names)
        except Exception as e:
            logger.warning("clickhouse_insert_failed", error=str(e))
            await _fallback_pg_insert(db, batch, rows, column_names)
    else:
        # ClickHouse unavailable — store in Postgres fallback table
        await _fallback_pg_insert(db, batch, rows, column_names)

    logger.info(
        "events_ingested",
        site_id=batch.site_id,
        visitor_id=batch.visitor_id[:8],
        count=len(batch.events),
    )

    # Auto-aggregate this visitor after ingestion
    try:
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site
        await aggregate_visitors_for_site(db, batch.site_id)
    except Exception as e:
        logger.warning("auto_aggregate_failed", error=str(e), site_id=batch.site_id)

    return Response(status_code=204)


async def _fallback_pg_insert(
    db: AsyncSession,
    batch: EventBatch,
    rows: list[list[object]],
    column_names: list[str],
) -> None:
    """Store events in Postgres when ClickHouse is unavailable."""
    # Create fallback table if not exists
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS events_fallback (
            id SERIAL PRIMARY KEY,
            site_id VARCHAR NOT NULL,
            visitor_id VARCHAR NOT NULL,
            event_data JSONB NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """))
    for row in rows:
        event_data = dict(zip(column_names, row))
        # Convert datetime to string for JSON
        if hasattr(event_data.get("created_at"), "isoformat"):
            event_data["created_at"] = event_data["created_at"].isoformat()
        await db.execute(
            text("INSERT INTO events_fallback (site_id, visitor_id, event_data) VALUES (:sid, :vid, :data)"),
            {"sid": batch.site_id, "vid": batch.visitor_id, "data": json.dumps(event_data, default=str)},
        )
    await db.commit()
