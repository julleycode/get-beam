import asyncio

import structlog
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.database import get_db, async_session
from apps.api.models.event import Event
from apps.api.schemas.events import EventBatch

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

    for event in batch.events:
        db.add(Event(
            site_id=batch.site_id,
            visitor_id=batch.visitor_id,
            event_type=event.type,
            url=event.url or "",
            referrer=event.referrer or "",
            utm_source=event.utm.source if event.utm and event.utm.source else "",
            utm_medium=event.utm.medium if event.utm and event.utm.medium else "",
            utm_campaign=event.utm.campaign if event.utm and event.utm.campaign else "",
            country_code="",
            region="",
            device_type=event.device or "",
            browser_lang=event.lang or "",
            scroll_depth=event.depth or 0,
            time_on_page=event.seconds or 0,
            element_text=event.element_text or "",
            element_href=event.element_href or "",
            ip_address=ip_address,
            created_at=event.ts,
        ))

    await db.commit()

    logger.info(
        "events_ingested",
        site_id=batch.site_id,
        visitor_id=batch.visitor_id[:8],
        count=len(batch.events),
    )

    # Run aggregation in background so we don't block the 204 response
    site_id = batch.site_id
    asyncio.create_task(_background_aggregate(site_id))

    return Response(status_code=204)


async def _background_aggregate(site_id: str) -> None:
    """Run visitor aggregation in a background task with its own DB session."""
    try:
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site
        async with async_session() as db:
            await aggregate_visitors_for_site(db, site_id)
    except Exception as e:
        logger.warning("background_aggregate_failed", error=str(e), site_id=site_id)
