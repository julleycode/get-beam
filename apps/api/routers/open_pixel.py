"""Email open-tracking pixel.

Campaign emails embed a 1x1 transparent GIF pointing at ``/o/{touchpoint_id}``.
Loading it stamps ``opened_at`` on the CampaignTouchpoint (first open only).

Open counts OVERCOUNT with Apple Mail Privacy Protection (its proxy prefetches
images), and undercount when images are blocked — clicks are the reliable
signal. The endpoint always answers 200 with the GIF, valid id or not, so it
never leaks whether a touchpoint exists.
"""
from datetime import datetime, timezone
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.campaign import CampaignTouchpoint
from apps.api.models.database import get_db
from apps.api.services.rate_limiter import limiter

router = APIRouter()
logger = structlog.get_logger()

# Smallest valid transparent 1x1 GIF (43 bytes).
_TRANSPARENT_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00"
    b"!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00"
    b"\x02\x02D\x01\x00;"
)


def _gif() -> Response:
    return Response(
        content=_TRANSPARENT_GIF,
        media_type="image/gif",
        headers={"Cache-Control": "no-store, no-cache, private", "Pragma": "no-cache"},
    )


@router.get("/{touchpoint_id}")
@limiter.limit("300/minute")
async def open_pixel(
    touchpoint_id: str, request: Request, db: AsyncSession = Depends(get_db)
) -> Response:
    try:
        tp_uuid = UUID(touchpoint_id)
    except ValueError:
        return _gif()

    try:
        # Naive UTC — opened_at is TIMESTAMP WITHOUT TIME ZONE (same convention
        # as the rest of the campaign columns).
        result = await db.execute(
            update(CampaignTouchpoint)
            .where(
                CampaignTouchpoint.id == tp_uuid,
                CampaignTouchpoint.opened_at.is_(None),
            )
            .values(opened_at=datetime.now(timezone.utc).replace(tzinfo=None))
        )
        await db.commit()
        if result.rowcount:
            logger.info("email_open_tracked", touchpoint_id=touchpoint_id[:8])
    except Exception as exc:
        logger.warning("email_open_track_failed", error=str(exc))

    return _gif()
