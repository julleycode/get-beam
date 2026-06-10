import asyncio
import json

import structlog
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.database import get_db, async_session
from apps.api.models.event import Event
from apps.api.schemas.events import EventBatch
from apps.api.services.bot_filter import is_bot
from apps.api.services.link_decorator import decode_bid
from apps.api.services.rate_limiter import limiter

router = APIRouter()
logger = structlog.get_logger()

# Keep strong references to background tasks so they aren't GC'd
_background_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]


def _extract_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return ""


async def _parse_event_batch(request: Request) -> EventBatch:
    """Parse EventBatch from request body.

    Accepts both application/json and text/plain content types.
    The pixel uses text/plain with sendBeacon to avoid CORS preflight.
    """
    body = await request.body()
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("Invalid JSON body")
    return EventBatch(**data)


@router.post("/ingest", status_code=204)
@limiter.limit("100/minute")
async def ingest_events(
    request: Request, db: AsyncSession = Depends(get_db)
) -> Response:
    # Extract user-agent from request header for bot detection
    request_ua = request.headers.get("user-agent", "")

    # Bot filtering — silently discard bot traffic (return 204, don't error)
    if is_bot(request_ua):
        return Response(status_code=204)

    try:
        batch = await _parse_event_batch(request)
    except Exception:
        return Response(status_code=400)

    # Validate site_id exists to prevent arbitrary data injection
    from sqlalchemy import select
    from apps.api.models.site import Site

    site_check = await db.execute(
        select(Site.site_id).where(Site.site_id == batch.site_id).limit(1)
    )
    if not site_check.scalar_one_or_none():
        return Response(status_code=403)

    ip_address = _extract_ip(request)

    # Client Hints extraction (best-effort)
    ch_ua = request.headers.get("sec-ch-ua", "")
    ch_platform = request.headers.get("sec-ch-ua-platform", "").strip('"')
    ch_mobile = request.headers.get("sec-ch-ua-mobile", "")

    # GeoIP resolution (best-effort, non-blocking on failure)
    country_code = ""
    region = ""
    try:
        from apps.api.services.geoip import resolve_geoip
        country_code, region = await resolve_geoip(ip_address)
    except Exception:
        pass  # GeoIP failure should never block event ingestion

    event_rows = [
        Event(
            site_id=batch.site_id,
            visitor_id=batch.visitor_id,
            event_type=event.type,
            url=event.url or "",
            referrer=event.referrer or "",
            utm_source=event.utm.source if event.utm and event.utm.source else "",
            utm_medium=event.utm.medium if event.utm and event.utm.medium else "",
            utm_campaign=event.utm.campaign if event.utm and event.utm.campaign else "",
            country_code=country_code,
            region=region,
            device_type=event.device or "",
            browser_lang=event.lang or "",
            scroll_depth=event.depth or 0,
            time_on_page=event.seconds or 0,
            element_text=event.element_text or "",
            element_href=event.element_href or "",
            ip_address=ip_address,
            user_agent=event.user_agent or request_ua[:500],
            page_title=event.page_title or "",
            page_path=event.page_path or "",
            created_at=event.ts.replace(tzinfo=None) if event.ts.tzinfo else event.ts,
        )
        for event in batch.events
    ]
    db.add_all(event_rows)
    try:
        await db.commit()
    except Exception as exc:
        logger.exception("event_commit_failed", error=str(exc))
        await db.rollback()
        raise

    logger.info(
        "events_ingested",
        site_id=batch.site_id,
        visitor_id=batch.visitor_id[:8],
        count=len(batch.events),
    )

    # Process identification signal events (form email capture + UTM _bid)
    await _process_signal_events(db, batch)

    # Run aggregation in background so we don't block the 204 response
    site_id = batch.site_id
    task = asyncio.create_task(_background_aggregate(site_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    # Server-side Set-Cookie: first-party HttpOnly cookie survives Safari ITP.
    # Named _rta_svid (server-side visitor ID) to coexist with client _rta_vid.
    # On future requests, the ingest endpoint can reconcile both.
    response = Response(status_code=204)
    response.set_cookie(
        key="_rta_svid",
        value=batch.visitor_id,
        max_age=365 * 86400,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
    )
    return response


async def _process_signal_events(db: AsyncSession, batch: EventBatch) -> None:
    """Extract email signals from form_email_capture and utm_identify events.

    Also stores the browser fingerprint on the visitor row so the identity
    resolver can match returning visitors across sessions.

    Upserts into visitor_emails so the identity resolver can use them in the
    pre-waterfall check instead of burning IP-resolution credits.
    """
    from sqlalchemy import update
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from apps.api.models.visitor import Visitor
    from apps.api.models.visitor_email import VisitorEmail

    # Persist fingerprint from events onto the visitor row (best-effort)
    # Any event with _fp set is sufficient; we use the first one found.
    # The pixel emits "fp2_<hash128>" (apps/pixel/src/tracker.js); older pixel
    # builds emitted "fp_<hash>" — accept both. Cap at the visitors.fingerprint
    # column length (64) so a malformed value can't fail the UPDATE.
    fp_value: str | None = None
    for event in batch.events:
        raw_fp = event.fp
        if (
            raw_fp
            and isinstance(raw_fp, str)
            and raw_fp.startswith(("fp_", "fp2_"))
            and len(raw_fp) <= 64
        ):
            fp_value = raw_fp
            break

    needs_commit = False

    if fp_value:
        try:
            # Only update visitors that don't yet have a fingerprint to avoid
            # overwriting a previously stored value with a potentially different one.
            await db.execute(
                update(Visitor)
                .where(
                    Visitor.site_id == batch.site_id,
                    Visitor.visitor_id == batch.visitor_id,
                    Visitor.fingerprint.is_(None),
                )
                .values(fingerprint=fp_value)
            )
            needs_commit = True
        except Exception as exc:
            logger.warning("fingerprint_store_failed", error=str(exc), visitor_id=batch.visitor_id[:8])

    emails_to_upsert: list[dict] = []

    from apps.api.services.email_validator import validate_email

    for event in batch.events:
        if event.type == "form_email_capture" and event.email:
            raw_email = event.email.strip().lower()
            if raw_email and "@" in raw_email:
                is_valid, reason = await validate_email(raw_email)
                if not is_valid:
                    logger.info("form_email_rejected", reason=reason, email_domain=raw_email.split("@")[-1])
                    continue
                emails_to_upsert.append({
                    "site_id": batch.site_id,
                    "visitor_id": batch.visitor_id,
                    "email": raw_email,
                    "source": "form",
                })
                logger.info(
                    "form_email_captured",
                    site_id=batch.site_id,
                    visitor_id=batch.visitor_id[:8],
                    email_domain=raw_email.split("@")[-1],
                )

        elif event.type == "utm_identify" and event.bid:
            decoded_email = decode_bid(event.bid)
            if decoded_email:
                decoded_email = decoded_email.strip().lower()
                if decoded_email and "@" in decoded_email:
                    is_valid, reason = await validate_email(decoded_email)
                    if not is_valid:
                        logger.info("utm_email_rejected", reason=reason)
                        continue
                    emails_to_upsert.append({
                        "site_id": batch.site_id,
                        "visitor_id": batch.visitor_id,
                        "email": decoded_email,
                        "source": "utm",
                    })
                    logger.info(
                        "utm_bid_identified",
                        site_id=batch.site_id,
                        visitor_id=batch.visitor_id[:8],
                        email_domain=decoded_email.split("@")[-1],
                    )

    if not emails_to_upsert:
        if needs_commit:
            try:
                await db.commit()
            except Exception as exc:
                logger.warning("fingerprint_commit_failed", error=str(exc))
                await db.rollback()
        return

    for row in emails_to_upsert:
        try:
            stmt = (
                pg_insert(VisitorEmail)
                .values(**row)
                .on_conflict_do_nothing(
                    constraint="uq_visitor_email_site_vid_email"
                )
            )
            await db.execute(stmt)
        except Exception as exc:
            logger.warning(
                "visitor_email_upsert_failed",
                error=str(exc),
                visitor_id=batch.visitor_id[:8],
            )

    try:
        await db.commit()
    except Exception as exc:
        logger.warning("visitor_email_commit_failed", error=str(exc))
        await db.rollback()


async def _background_aggregate(site_id: str) -> None:
    """Run visitor aggregation in a background task with its own DB session."""
    try:
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site
        async with async_session() as db:
            await aggregate_visitors_for_site(db, site_id)
    except Exception as e:
        logger.warning("background_aggregate_failed", error=str(e), site_id=site_id)
