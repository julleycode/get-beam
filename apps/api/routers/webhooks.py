"""Inbound provider webhooks — SendGrid email events.

SendGrid Event Webhook → mark hard-bounced / dropped / spam-reported addresses as
``do_not_email`` so we never mail them again (deliverability + CAN-SPAM).

Authenticated by a shared secret query token — set the SAME token in the SendGrid
webhook URL: ``/webhooks/sendgrid?token=<SENDGRID_WEBHOOK_SECRET>``. Without a
configured secret the endpoint is disabled (403) so it can never be used as an
open suppression vector.
"""

import hmac

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.database import get_db
from apps.api.models.visitor import IdentifiedVisitor

logger = structlog.get_logger()

router = APIRouter(tags=["webhooks"])

# Event types that should permanently suppress an address.
_SUPPRESS_EVENTS = {"bounce", "dropped", "spamreport"}
# For a 'bounce' event, only HARD bounces ('bounce'/'blocked' type) suppress —
# soft/transient bounces arrive as 'deferred' and are ignored.
_HARD_BOUNCE_TYPES = {"bounce", "blocked"}


@router.post("/webhooks/sendgrid")
async def sendgrid_events(
    request: Request,
    token: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
) -> dict:
    secret = settings.sendgrid_webhook_secret
    if not secret or not hmac.compare_digest(token, secret):
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        events = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    if isinstance(events, dict):
        events = [events]
    if not isinstance(events, list):
        raise HTTPException(status_code=400, detail="Expected a JSON array of events")

    suppressed = 0
    for ev in events:
        if not isinstance(ev, dict):
            continue
        event_type = (ev.get("event") or "").lower()
        email = (ev.get("email") or "").strip().lower()
        if not email or event_type not in _SUPPRESS_EVENTS:
            continue
        if event_type == "bounce" and (ev.get("type") or "bounce").lower() not in _HARD_BOUNCE_TYPES:
            continue
        # Case-insensitive: stored emails may be mixed case (provider-supplied);
        # `email` is already stripped + lowercased above.
        await db.execute(
            update(IdentifiedVisitor)
            .where(func.lower(IdentifiedVisitor.email) == email)
            .values(do_not_email=True)
        )
        suppressed += 1

    if suppressed:
        await db.commit()
    logger.info("sendgrid_events_processed", count=len(events), suppressed=suppressed)
    return {"processed": len(events), "suppressed": suppressed}
