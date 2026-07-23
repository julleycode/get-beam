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
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.database import get_db
from apps.api.services.identity_signals import record_signal
from apps.api.services.suppression import add_suppression

logger = structlog.get_logger()

router = APIRouter(tags=["webhooks"])

# Event types that should permanently suppress an address.
_SUPPRESS_EVENTS = {"bounce", "dropped", "spamreport"}
# For a 'bounce' event, only HARD bounces ('bounce'/'blocked' type) suppress —
# soft/transient bounces arrive as 'deferred' and are ignored.
_HARD_BOUNCE_TYPES = {"bounce", "blocked"}
# Engagement events captured as corroborating identity signals (owned-data-layer,
# gated by identity_signals_enabled). Separate from _SUPPRESS_EVENTS — additive.
_SIGNAL_EVENTS = {"open": "sendgrid_open", "click": "sendgrid_click"}


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
    signals = 0
    for ev in events:
        if not isinstance(ev, dict):
            continue
        event_type = (ev.get("event") or "").lower()
        email = (ev.get("email") or "").strip().lower()
        if not email:
            continue

        # ── Suppression branch (bounce/dropped/spamreport) — UNCHANGED ──
        if event_type in _SUPPRESS_EVENTS:
            if event_type == "bounce" and (ev.get("type") or "bounce").lower() not in _HARD_BOUNCE_TYPES:
                continue
            # Write a suppression-list entry (blind-index) AND cascade do_not_email
            # onto existing rows. The entry is what catches an address re-identified
            # AFTER the bounce — flagging only existing rows left that hole open.
            await add_suppression(
                db, email, scope="do_not_email", reason=f"sendgrid_{event_type}"
            )
            suppressed += 1
            continue

        # ── Corroborating-signal branch (open/click) — additive, flag-gated ──
        if event_type in _SIGNAL_EVENTS and settings.identity_signals_enabled:
            # site_id is derived from the custom_args SendGrid echoes back as
            # top-level keys on the event. If absent (send predated custom_args
            # wiring, or a non-campaign send), SKIP — never guess via reverse
            # email lookup: a wrong site_id write is worse than a missed signal.
            site_id = (ev.get("site_id") or "").strip()
            if not site_id:
                continue
            ip = (ev.get("ip") or "").strip()
            if not ip:
                continue
            await record_signal(
                db,
                site_id=site_id,
                ip=ip,
                email=email,
                signal_type=_SIGNAL_EVENTS[event_type],
            )
            signals += 1

    logger.info(
        "sendgrid_events_processed",
        count=len(events),
        suppressed=suppressed,
        signals=signals,
    )
    return {"processed": len(events), "suppressed": suppressed, "signals": signals}
