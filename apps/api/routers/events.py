import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
# Sites with an aggregation already in-flight — coalesce so a burst of ingest
# batches for one site spawns at most one aggregation at a time (the in-flight
# run reads current state, so it covers the newly-arrived events).
_aggregating: set[str] = set()


def _tp_from_url(url: str | None) -> UUID | None:
    """Extract a valid _tp campaign-touchpoint UUID from a landing URL, or None.

    Campaign-decorated links carry ``_tp=<touchpoint uuid>`` next to ``_bid`` so
    a click can be attributed to the exact sent email.
    """
    if not url or "_tp=" not in url:
        return None
    try:
        vals = parse_qs(urlsplit(url).query).get("_tp")
        return UUID(vals[0]) if vals else None
    except Exception:
        return None


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
        select(Site.tracking_enabled).where(Site.site_id == batch.site_id).limit(1)
    )
    tracking_enabled = site_check.scalar_one_or_none()
    if tracking_enabled is None:
        # Site does not exist (never created, or DELETED). Reject to prevent
        # arbitrary data injection — and purge the durable HttpOnly _rta_svid
        # cookie for this site, since JS can't clear an HttpOnly cookie (only the
        # server can). The pixel clears its own client cookies when it reads this
        # 403. Best-effort: under wildcard-CORS cross-origin the browser may not
        # apply the Set-Cookie, but it works for first-party / same-site installs
        # and is harmless otherwise. Attrs must match the original Set-Cookie
        # (see below) or the browser won't overwrite the cookie.
        gone = Response(status_code=403)
        svid_cookie_name = "_rta_svid_" + "".join(
            c for c in batch.site_id if c.isalnum() or c == "_"
        )
        gone.delete_cookie(
            key=svid_cookie_name,
            path="/",
            secure=True,
            httponly=True,
            samesite="none",
        )
        return gone
    if tracking_enabled is False:
        # Tracking paused for this site — silently drop the events (same pattern
        # as the bot filter above). Pixel stays installed; no error surfaced.
        return Response(status_code=204)

    ip_address = _extract_ip(request)

    # Datacenter / cloud-compute traffic = bots (Azure/AWS/GCP server scanners,
    # AI-agent browsers that spoof a real Chrome UA and slip past is_bot above).
    # Drop silently like the UA filter. Cached + fail-open: a lookup error never
    # blocks a real visitor's events.
    from apps.api.config import settings as _settings
    if _settings.block_datacenter_traffic:
        from apps.api.services.company_resolver import is_datacenter_ip
        if await is_datacenter_ip(ip_address):
            return Response(status_code=204)

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
        dict(
            event_id=(event.event_id or None),
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
            optout=bool(event.optout),
            created_at=event.ts.replace(tzinfo=None) if event.ts.tzinfo else event.ts,
        )
        for event in batch.events
    ]
    # Idempotent insert: a re-delivered beacon batch (browser retry after tab
    # kill, proxy replay) carries the same client-generated event_ids and is
    # silently dropped instead of double-counting pageviews/sessions/intent.
    # Rows with NULL event_id (older pixel builds) never conflict.
    insert_stmt = (
        pg_insert(Event)
        .values(event_rows)
        .on_conflict_do_nothing(index_elements=["event_id"])
    )
    try:
        await db.execute(insert_stmt)
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

    # Durable identity reconciliation: the HttpOnly _rta_svid cookie carries the
    # ORIGINAL visitor_id even after the client id (_rta_vid) is wiped by Safari
    # ITP. If it differs from this batch's (client) visitor_id, the resolver uses
    # it to recover a prior identification for free. Only trust a Beam-shaped id.
    #
    # Named PER SITE (_rta_svid_<site>): the pixel posts to one shared API host,
    # so a single cookie name would be clobbered across customers — site A's
    # durable id overwritten by site B's. Per-site keeps each site's root id.
    svid_cookie_name = "_rta_svid_" + "".join(
        c for c in batch.site_id if c.isalnum() or c == "_"
    )
    existing_svid = request.cookies.get(svid_cookie_name)
    svid = existing_svid
    if not (svid and isinstance(svid, str) and 0 < len(svid) <= 100 and svid != batch.visitor_id):
        svid = None

    # Process identification signal events (form email capture + UTM _bid)
    await _process_signal_events(db, batch, svid)

    # Conversion goal matching (best-effort — never blocks the 204). Runs AFTER
    # signal processing so a landing pageview that carries _tp has its
    # campaign_clicks link committed before attribution looks for it.
    try:
        from apps.api.services.conversion_tracker import process_batch as _track_conversions

        await _track_conversions(db, batch)
    except Exception as exc:
        logger.warning("conversion_tracking_failed", error=str(exc))

    # Run aggregation in background so we don't block the 204 response — but
    # coalesce per site so a burst of batches can't spawn an unbounded pile of
    # overlapping aggregations.
    site_id = batch.site_id
    if site_id not in _aggregating:
        _aggregating.add(site_id)
        task = asyncio.create_task(_background_aggregate(site_id))
        _background_tasks.add(task)

        def _done(t: "asyncio.Task", _sid: str = site_id) -> None:
            _background_tasks.discard(t)
            _aggregating.discard(_sid)

        task.add_done_callback(_done)

    # Server-side Set-Cookie: first-party HttpOnly cookie survives Safari ITP.
    # Coexists with the client _rta_vid. Set ONCE and PRESERVED across visits:
    # only write when the request didn't already carry a durable id, so the
    # cookie keeps pointing at the ORIGINAL (root) visitor_id. Rewriting it to the
    # current client id each visit would break the reconciliation chain after the
    # first ITP wipe (the rewritten id may have been merged and have no identity row).
    response = Response(status_code=204)
    if not existing_svid:
        response.set_cookie(
            key=svid_cookie_name,
            value=batch.visitor_id,
            max_age=365 * 86400,
            httponly=True,
            secure=True,
            samesite="none",
            path="/",
        )
    return response


async def _process_signal_events(
    db: AsyncSession, batch: EventBatch, svid: str | None = None
) -> None:
    """Extract email signals from form_email_capture and utm_identify events.

    Also stores the browser fingerprint on the visitor row so the identity
    resolver can match returning visitors across sessions.

    `svid` is the value of the durable _rta_svid server cookie when it differs
    from the client visitor_id — stored write-once on the visitor row so the
    resolver can reconcile a wiped-client returning visitor to their original id.

    Upserts into visitor_emails so the identity resolver can use them in the
    pre-waterfall check instead of burning IP-resolution credits.
    """
    from sqlalchemy import select, update
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

    # Durable server-cookie reconciliation: stamp the original visitor_id (from
    # _rta_svid) onto this returning-but-wiped visitor, write-once like the
    # fingerprint. The resolver follows it to a prior identification for free.
    if svid:
        try:
            await db.execute(
                update(Visitor)
                .where(
                    Visitor.site_id == batch.site_id,
                    Visitor.visitor_id == batch.visitor_id,
                    Visitor.server_visitor_id.is_(None),
                )
                .values(server_visitor_id=svid)
            )
            needs_commit = True
        except Exception as exc:
            logger.warning("svid_store_failed", error=str(exc), visitor_id=batch.visitor_id[:8])

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
                # Where the pixel captured it (form/input/login/checkout/
                # newsletter/identify). Sanitized + capped to the column width.
                src = (event.source or "form").strip().lower()[:20] or "form"
                emails_to_upsert.append({
                    "site_id": batch.site_id,
                    "visitor_id": batch.visitor_id,
                    "email": raw_email,
                    "source": src,
                })
                logger.info(
                    "form_email_captured",
                    site_id=batch.site_id,
                    visitor_id=batch.visitor_id[:8],
                    email_domain=raw_email.split("@")[-1],
                    source=src,
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

    # Campaign click attribution: campaign links carry _tp=<touchpoint uuid>
    # next to _bid. Stamp clicked_at (and opened_at — a click proves an open) on
    # those touchpoints, scoped to this site's campaigns so a forged or foreign
    # _tp is a no-op. Collected across ALL events (utm_identify + pageview carry
    # the landing URL), independent of email validity.
    tp_ids = {tid for tid in (_tp_from_url(e.url) for e in batch.events) if tid}
    if tp_ids:
        from apps.api.models.campaign import Campaign, CampaignTouchpoint

        try:
            now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
            site_campaign_ids = select(Campaign.id).where(Campaign.site_id == batch.site_id)
            clicked = await db.execute(
                update(CampaignTouchpoint)
                .where(
                    CampaignTouchpoint.id.in_(tp_ids),
                    CampaignTouchpoint.campaign_id.in_(site_campaign_ids),
                    CampaignTouchpoint.clicked_at.is_(None),
                )
                .values(clicked_at=now_naive)
            )
            await db.execute(
                update(CampaignTouchpoint)
                .where(
                    CampaignTouchpoint.id.in_(tp_ids),
                    CampaignTouchpoint.campaign_id.in_(site_campaign_ids),
                    CampaignTouchpoint.opened_at.is_(None),
                )
                .values(opened_at=now_naive)
            )
            # Durable touchpoint ↔ landing-visitor link for conversion
            # attribution. Runs even when clicked_at was already stamped — a
            # second device clicking the same link needs its own link row (the
            # unique constraint keeps beacon replays idempotent). Scoped by the
            # same site subquery, so a forged/foreign _tp inserts nothing.
            from apps.api.models.outcome import CampaignClick

            tp_rows = (
                await db.execute(
                    select(CampaignTouchpoint.id, CampaignTouchpoint.campaign_id).where(
                        CampaignTouchpoint.id.in_(tp_ids),
                        CampaignTouchpoint.campaign_id.in_(site_campaign_ids),
                    )
                )
            ).all()
            for tp_id, tp_campaign_id in tp_rows:
                await db.execute(
                    pg_insert(CampaignClick)
                    .values(
                        touchpoint_id=tp_id,
                        campaign_id=tp_campaign_id,
                        site_id=batch.site_id,
                        visitor_id=batch.visitor_id,
                        clicked_at=now_naive,
                    )
                    .on_conflict_do_nothing(constraint="uq_campaign_clicks_tp_visitor")
                )
            if clicked.rowcount:
                logger.info(
                    "campaign_click_tracked",
                    site_id=batch.site_id,
                    touchpoints=clicked.rowcount,
                )
            needs_commit = True
        except Exception as exc:
            logger.warning("campaign_click_track_failed", error=str(exc))

    if not emails_to_upsert:
        if needs_commit:
            try:
                await db.commit()
            except Exception as exc:
                logger.warning("fingerprint_commit_failed", error=str(exc))
                await db.rollback()
        return

    # Phase 05 (5b): dual-write encrypted columns. This is a CORE insert, so the
    # ORM mapper-event hooks don't fire — populate ciphertext + blind index here.
    from apps.api.services.pii_crypto import email_hash, encrypt_pii

    for row in emails_to_upsert:
        try:
            row["email_ciphertext"] = encrypt_pii(row["email"])
            row["email_bidx"] = email_hash(row["email"])
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
