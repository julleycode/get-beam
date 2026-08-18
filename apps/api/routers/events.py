import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.database import get_db, async_session, apply_long_job_statement_timeout
from apps.api.models.event import Event
from apps.api.schemas.events import EventBatch
from apps.api.services.agent_classifier import classify_agent, classify_tier
# Top-level, unlike the flag-gated lazy import of this module further down: the
# extraction runs on every event row, so paying an import lookup per batch would
# be the wrong trade. No cycle — agent_marker's heaviest dependency is
# link_decorator, which this module already imports above.
from apps.api.services.agent_marker import edge_marker_from_url
from apps.api.services.agent_visit_persistence import build_dedup_key, persist_agent_visit, persist_agent_fetch_event
from apps.api.services.bot_filter import is_bot
from apps.api.services.ip_resolution import resolve_client_ip
from apps.api.services.link_decorator import decode_bid
from apps.api.services.orphan_ingest_metrics import record_orphan_ingest
from apps.api.services.rate_limiter import limiter, site_ceiling_tripped

router = APIRouter()
logger = structlog.get_logger()

# WS2 Detector A — server-side fingerprint mismatch (the PRIMARY detector).
#
# Vendor-independent: it fires for Brave, Firefox resist_fingerprinting, Tor and
# CanvasBlocker alike, and costs zero pixel bytes. Especially well suited here
# because a farbled browser still keeps its first-party cookie, so the visitor
# returns under the SAME visitor_id and reliably trips the comparison.
#
# Evaluated inside the visitor-stub ON CONFLICT clause rather than a preceding
# SELECT: /ingest is the hottest path in the API, and the comparison needs
# exactly the two values that upsert already has in hand — zero extra
# round-trips.
#
# Both IS NOT NULL guards are load-bearing: a NULL on either side means "no
# evidence" (brand-new visitor, or a batch carrying no fp), never a mismatch.
# Sticky-OR, same semantics as do_not_resolve / is_abuse_flagged.
#
# fp3 disjunct — LOW signal value, deliberately. fp3 = hash(fpBase | fonts |
# audio) and fpBase ALREADY CONTAINS canvas + webgl, so a browser that farbles
# canvas (Brave, i.e. the main case) rotates fp2 AND fp3 together and the fp2
# disjunct alone already catches it. The set this adds is narrow: a browser that
# randomizes fonts or audio but NOT canvas/webgl. Do not read it as a strong
# detector. It is only defensible because the pixel now suppresses fp3 entirely
# when the audio watchdog fires (tracker.js audioFp cb(value, reliable)) — before
# that fix, the 1s render race populated exactly this fp3-only-mismatch
# signature with noise from ordinary visitors.
#
# The same both-sides-NOT-NULL guards are what make the async-arrival window
# safe: fp3 routinely lands on a LATER batch than fp2, so early batches
# legitimately have a NULL on one side and must read as "no evidence".
FARBLED_MISMATCH_SQL = (
    "visitors.has_unstable_fingerprint OR ("
    "visitors.fingerprint IS NOT NULL "
    "AND EXCLUDED.fingerprint IS NOT NULL "
    "AND visitors.fingerprint <> EXCLUDED.fingerprint) OR ("
    "visitors.fingerprint_v3 IS NOT NULL "
    "AND EXCLUDED.fingerprint_v3 IS NOT NULL "
    "AND visitors.fingerprint_v3 <> EXCLUDED.fingerprint_v3)"
)

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


def _is_local_url(url: str | None) -> bool:
    """True when the page URL host is a loopback/dev host.

    A customer's local dev environment loading the production pixel snippet posts
    real-looking events from a real public IP, so only the page URL can separate
    them. Never raises — a malformed/absent URL is treated as non-local so the
    drop is never widened.
    """
    if not url:
        return False
    try:
        host = (urlsplit(url).hostname or "").lower()
    except Exception:
        return False
    return (
        host in ("localhost", "::1", "0.0.0.0")
        or host.startswith("127.")
        or host.endswith(".localhost")
    )


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


async def stash_site_id(request: Request) -> str | None:
    """Populate ``request.state.site_id`` before the rate-limit layer runs.

    The site-ceiling limiter keys on site_id, which lives in the POST body — but
    a slowapi key_func fires before the endpoint has parsed anything. FastAPI
    resolves dependencies BEFORE calling the (slowapi-wrapped) endpoint, so a
    dependency is the earliest hook that can see the body.

    Reads the body exactly once in the logical sense: Starlette caches the bytes
    on ``request._body``, so ``_parse_event_batch``'s later ``await
    request.body()`` is a free cache hit, not a second read. Fail-open — a
    malformed/oversized/absent body leaves state unset and the endpoint's own
    parse produces the 400.

    Inert when the site ceiling is disabled (the default): the stash exists ONLY
    to feed that limiter, so with the flag off we must not buffer+JSON-parse a
    body the bot filter may be about to drop unread. Flag off == byte-identical
    to pre-hardening behaviour.
    """
    from apps.api.config import settings

    site_id: str | None = None
    if not settings.site_ingest_limit_enabled:
        request.state.site_id = None
        return None
    try:
        raw = await request.body()
        if raw:
            data = json.loads(raw)
            candidate = data.get("site_id") if isinstance(data, dict) else None
            if isinstance(candidate, str) and candidate:
                site_id = candidate
    except Exception:
        site_id = None
    request.state.site_id = site_id
    return site_id


@router.post("/ingest", status_code=204)
@limiter.limit("100/minute")
async def ingest_events(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _site_id_stash: str | None = Depends(stash_site_id),
) -> Response:
    # Extract user-agent from request header for bot detection
    request_ua = request.headers.get("user-agent", "")

    from apps.api.config import settings as _settings

    # EvalLayer: recognize known AI-agent UAs (OpenAI/Anthropic/Perplexity/
    # ByteSpider) so they're classified + persisted as agent visits instead of
    # dropped by is_bot() below. Gated OFF by default — when off, classification
    # is None and the ingest path is byte-identical to pre-EvalLayer behavior.
    classification = (
        classify_agent(request_ua) if _settings.agent_detection_enabled else None
    )

    # Bot filtering — silently discard bot traffic (return 204, don't error).
    # A recognized AI-agent UA (classification is not None) skips this drop even
    # if it also matches _BOT_PATTERN (e.g. "gptbot"), so it can be classified.
    if classification is None and is_bot(request_ua):
        # Mark the drop for the admin request log. Without this the response is
        # an ordinary 204, indistinguishable from a successful ingest by status
        # alone — this marker is the ONLY way the log viewer can explain a
        # silent drop. Setting request.state is inert when the log flag is off.
        request.state.log_reason = "bot_drop"
        request.state.log_reason_detail = f"is_bot() matched UA: {request_ua[:200]}"
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
        # Observability ONLY, added strictly AFTER the response is fully built
        # and strictly BEFORE the return: the status code, body, and every
        # cookie attribute above must stay byte-identical, because already
        # deployed trackers depend on this exact response and cannot be updated.
        # record_orphan_ingest is fail-open and can never raise.
        logger.warning(
            "ingest_unknown_site",
            site_id=batch.site_id,
            rejected_as="unknown_site",
        )
        await record_orphan_ingest(batch.site_id)
        return gone
    if tracking_enabled is False:
        # Tracking paused for this site — silently drop the events (same pattern
        # as the bot filter above). Pixel stays installed; no error surfaced.
        return Response(status_code=204)

    # Local/dev URL drop — a dev machine running the prod snippet has a real
    # public IP, so the page URL is the only signal. Silent 204 like the filters
    # above when the whole batch is local; otherwise only the survivors are
    # stored and signal-processed. Private LAN ranges are deliberately NOT
    # dropped (intranet deployments can be legitimate).
    if _settings.ingest_drop_local_urls:
        survivors = [e for e in batch.events if not _is_local_url(e.url)]
        if not survivors:
            return Response(status_code=204)
        batch.events = survivors

    # Trusted-proxy-aware resolution. At the default trusted_proxy_hops=0 the
    # X-Forwarded-For header is IGNORED entirely, so a caller can no longer forge
    # a fresh identity per request for the rate limiter / datacenter+proxy drops /
    # velocity signal downstream. Never raises — falls back to request.client.host.
    ip_address = resolve_client_ip(request)

    # ─── TEMPORARY DIAGNOSTIC — Phase 0 P0.1 (capacity-hardening plan 25-07-26) ───
    # WHY: the per-IP rate limiter keys on exactly this resolved value
    # (services/rate_limiter.client_ip_key_func). If Railway's edge terminates the
    # connection, request.client.host is the proxy for EVERY visitor and all traffic
    # collapses into one 100/min bucket. That hypothesis is UNVERIFIED live and
    # cannot be proven from the repo — only from production cardinality.
    #
    # PII RULE (absolute): the resolved key IS the client IP. It is NEVER logged.
    # Only the truncated SHA-256 (cardinality is preserved, the value is not
    # recoverable) and the LENGTH of the forwarded chain are emitted. The chain
    # itself is never logged either.
    #
    # REMOVAL CONDITION (Phase 2 exit gate — mandatory, not optional cleanup):
    # delete this block as soon as >=100 real ingests have been observed and the
    # distinct-`key_hash` vs distinct-`visitor_id` count has been written into the
    # plan's "Resume and Execution Handoff" item 5 (P0.1). It must not survive the
    # Phase 2 closeout regardless of what the observation shows.
    import hashlib as _hashlib

    logger.info(
        "ingest_client_key",
        key_hash=_hashlib.sha256((ip_address or "unknown").encode()).hexdigest()[:12],
        xff_len=len(
            [
                p
                for p in request.headers.get("x-forwarded-for", "").split(",")
                if p.strip()
            ]
        ),
        trusted_proxy_hops=_settings.trusted_proxy_hops,
    )
    # ─── END TEMPORARY DIAGNOSTIC (P0.1) ───

    # EvalLayer agent branch — HARD return. A recognized AI-agent visit is
    # persisted to agent_visits and answered with 204 BEFORE any human-path code
    # runs. It MUST NOT fall through to the datacenter/proxy-VPN drops, Client
    # Hints, GeoIP, the Event insert, signal/conversion processing, or the
    # background aggregation (SPEC AC2 — human tables never polluted; AC4 — agent
    # traffic is never re-dropped by the datacenter/proxy filters). Only the first
    # event's page_path in a multi-event batch is recorded this phase.
    if classification is not None:
        first_agent_event = batch.events[0] if batch.events else None
        agent_path = first_agent_event.page_path if first_agent_event else None
        await persist_agent_visit(db, batch.site_id, classification, ip_address, agent_path)
        # H1: also capture this hit as its own append-only, tier-tagged fetch
        # event (isolated fail-open write — a failure here never affects the
        # rollup above nor the 204 response).
        tier = classify_tier(classification.product_or_ua_token)
        # The pixel keeps its queue on any non-2xx and re-sends the same batch on
        # the next interval, carrying the same client-minted event_ids — so a
        # transient failure downstream of this write would otherwise log the one
        # fetch again on every retry. Reuse the batch's own idempotency key, the
        # same one the human Event insert dedupes on. Older pixel builds send no
        # event_id; those keep inserting unconditionally.
        await persist_agent_fetch_event(
            db, batch.site_id, classification, tier, ip_address, agent_path,
            dedup_key=build_dedup_key(
                site_id=batch.site_id,
                vendor=classification.vendor,
                raw_ua_token=classification.product_or_ua_token,
                page_path=agent_path,
                natural_key=first_agent_event.event_id if first_agent_event else None,
            ),
        )
        return Response(status_code=204)

    # Datacenter / cloud-compute traffic = bots (Azure/AWS/GCP server scanners,
    # AI-agent browsers that spoof a real Chrome UA and slip past is_bot above).
    # Drop silently like the UA filter. Cached + fail-open: a lookup error never
    # blocks a real visitor's events.
    if _settings.block_datacenter_traffic:
        from apps.api.services.company_resolver import is_datacenter_ip
        if await is_datacenter_ip(ip_address):
            return Response(status_code=204)

    # Proxy / VPN / Tor / hosting traffic = automated scrapers hiding behind a
    # real-looking UA and an ASN the datacenter org-token net misses (e.g. Sprious).
    # IPinfo Privacy Detection flags these regardless of reverse-DNS, so a no-PTR
    # commercial proxy is caught WITHOUT dropping mobile CGNAT humans (never flagged
    # proxy) or Apple Private Relay users (relay is not a drop signal). Same silent
    # 204, cached 7d + fail-open as the datacenter check above.
    if _settings.block_proxy_vpn_traffic:
        from apps.api.services.company_resolver import check_ip_privacy, is_proxy_or_vpn
        if is_proxy_or_vpn(await check_ip_privacy(ip_address)):
            return Response(status_code=204)

    # ── Abuse signals (P3 site ceiling + P4 velocity) ──────────────────
    # F3: site ceiling is hard 429, 0 INSERT (disk). Do not leak site internals
    # in the body. Velocity (P4) stays Option C flag-but-store.
    if site_ceiling_tripped(batch.site_id):
        logger.warning(
            "site_ingest_ceiling_tripped",
            site_id=batch.site_id,
            limit_per_minute=_settings.site_ingest_limit_per_minute,
        )
        request.state.site_id = batch.site_id
        request.state.log_reason = "site_ceiling"
        request.state.log_reason_detail = "ingest ceiling — retry later"
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please retry later.",
        )

    # P4 velocity: one check per BATCH, not per event — velocity is a
    # per-visitor-ARRIVAL signal, and site_id/visitor_id are batch-level fields.
    # The fingerprint is the first usable per-event _fp in the batch.
    # Gate BEFORE touching Redis: with the flag off this branch must be entirely
    # inert — no client construction, no connection — so ingest behaviour is
    # byte-identical to pre-hardening. (get_redis() caches a module-global client
    # bound to the creating event loop, so building one here unconditionally
    # would also strand that client across loops.)
    abuse_flagged = False
    if _settings.ingest_velocity_enabled:
        batch_fp: str | None = None
        for _event in batch.events:
            _raw_fp = _event.fp
            if _raw_fp and isinstance(_raw_fp, str) and _raw_fp.startswith(("fp_", "fp2_")):
                batch_fp = _raw_fp[:64]
                break
        try:
            from apps.api.services.ingest_velocity import check_velocity
            from apps.api.services.redis_client import get_redis

            abuse_flagged = await check_velocity(
                get_redis(), batch.site_id, batch.visitor_id, batch_fp
            )
        except Exception as exc:
            # Fail-open: velocity detection must never block a real visitor.
            logger.warning("ingest_velocity_unavailable", error=str(exc))

    # Admin request log markers. `stash_site_id` only populates state.site_id when
    # the site-ceiling limiter is enabled, so set it here too — the log viewer's
    # per-site facet must work independently of that flag. A velocity-flagged
    # batch is stored (flag-but-store), so without this marker it would look like
    # an ordinary 204 in the log.
    request.state.site_id = batch.site_id
    if abuse_flagged:
        request.state.log_reason = "abuse_flag"
        request.state.log_reason_detail = "ingest velocity flagged this batch"

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
            event_id=event.event_id,
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
            # Edge-minted AI-fetch marker lifted out of the landing URL. Extracted
            # here rather than read from ``url`` at query time so the join against
            # AgentFetchEvent.link_marker is an index lookup instead of a LIKE
            # scan of this table. Shape-checked inside the helper: the value is
            # attacker-supplied (anyone can append ``?_bfm=``), and junk that
            # cannot have been minted is stored as NULL.
            link_marker=edge_marker_from_url(event.url),
            optout=bool(event.optout),
            # WS2 Detector B (pixel navigator.brave probe). Rolled up per visitor
            # via BOOL_OR into visitors.has_unstable_fingerprint. Never a drop or
            # block signal on this path.
            farbled=bool(event.farbled),
            # P4 velocity flag (site ceiling never reaches INSERT — hard 429).
            # Written in the SAME INSERT that stores the row.
            is_flagged_abuse=abuse_flagged,
            # WS2 agent-operated session signals. Purely additive and purely
            # observational: nothing on this request path reads it, no branch
            # depends on it, and no session is ever dropped or blocked because of
            # it (SPEC AC-7). Whitelisted/bounded by the schema validator before
            # it reaches here — never the raw client object.
            agent_sig=event.agent_sig,
            # F2 / Validation S1: aggregation window is server now(), never event.ts.
            created_at=datetime.utcnow(),
        )
        for event in batch.events
    ]
    # Idempotent insert: a re-delivered beacon batch (browser retry after tab
    # kill, proxy replay) carries the same client-generated event_ids and is
    # silently dropped instead of double-counting pageviews/sessions/intent.
    # Conflict target is (site_id, event_id) so the same id on two sites
    # inserts both rows (F1). Schema requires event_id; NULLs are legacy only.
    insert_stmt = (
        pg_insert(Event)
        .values(event_rows)
        .on_conflict_do_nothing(index_elements=["site_id", "event_id"])
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

    # Job-change detection Trigger A: a returning visitor is the cheapest signal
    # that their stored profile is worth re-checking. Fire-and-forget dispatch
    # ONLY — no DB read, no await on the result, so the ingest response is
    # unaffected whether or not a re-check ends up happening.
    #
    # The identity_status / stored-profile checks deliberately live inside the
    # task, not here: this handler holds no Visitor ORM row (visitor rows are
    # built by the aggregator), so gating here would cost an extra query on the
    # hot path for a check the task must repeat anyway.
    if _settings.job_change_detection_enabled:
        try:
            from apps.api.tasks.job_change_tasks import recheck_returning_visitor

            recheck_returning_visitor.delay(batch.visitor_id, batch.site_id)
        except Exception as exc:
            logger.debug("job_change_trigger_dispatch_failed", error=str(exc))

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

    # Agent handoff attribution (F2): an offers-feed link carries _bam=<marker>
    # naming the exact agent fetch that surfaced it, so the human who clicked it
    # is matched deterministically instead of guessed at by the 30-minute
    # temporal sweep. Read off the landing URL the pixel already sends, the same
    # way _tp is — no tracker change is involved. Site-scoped inside the service,
    # so a marker replayed at another tenant writes nothing.
    #
    # Kept OUT of _process_signal_events deliberately: that function leaves
    # fingerprint/svid updates pending until its own commit, and this write owns
    # its transaction (it rolls back on failure), which would discard them.
    if _settings.agent_marker_enabled:
        from apps.api.services.agent_marker import (
            marker_from_url,
            record_marker_handoff,
        )

        for _marker in {m for m in (marker_from_url(e.url) for e in batch.events) if m}:
            await record_marker_handoff(
                db, site_id=batch.site_id, visitor_id=batch.visitor_id, marker=_marker
            )

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
    # overlapping aggregations. This in-memory set is now only the cheap FIRST
    # layer; the cross-container Redis debounce + sweep-yield checks live in
    # _background_aggregate (Phase 3 item 7 / E16b).
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
    from sqlalchemy import select, text as sa_text, update
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from apps.api.models.visitor import Visitor
    from apps.api.models.visitor_email import VisitorEmail

    # Persist fingerprint from events onto the visitor row (best-effort)
    # Any event with _fp set is sufficient; we use the first one found.
    # The pixel emits "fp2_<hash128>" (apps/pixel/src/tracker.js); older pixel
    # builds emitted "fp_<hash>" — accept both. Cap at the visitors.fingerprint
    # column length (64) so a malformed value can't fail the UPDATE.
    fp_value: str | None = None
    fp3_value: str | None = None
    for event in batch.events:
        raw_fp = event.fp
        if (
            fp_value is None
            and raw_fp
            and isinstance(raw_fp, str)
            and raw_fp.startswith(("fp_", "fp2_"))
            and len(raw_fp) <= 64
        ):
            fp_value = raw_fp
        # fp3 resolves asynchronously on the client, so it can appear on a LATER
        # event than fp2 (or on a later batch entirely) — keep scanning for it
        # instead of breaking on the first fp2 hit.
        raw_fp3 = event.fp3
        if (
            fp3_value is None
            and raw_fp3
            and isinstance(raw_fp3, str)
            and raw_fp3.startswith("fp3_")
            and len(raw_fp3) <= 64
        ):
            fp3_value = raw_fp3
        if fp_value and fp3_value:
            break

    needs_commit = False

    # Aggregation creates visitor rows asynchronously AFTER this function runs.
    # A bare UPDATE then matches 0 rows and one-shot visitors never get FP/svid.
    # Upsert a minimal stub with write-once FP/svid in ONE statement so a stub
    # failure cannot leave the stamps silently dropped; aggregator later fills
    # pageview/session totals on the same PK without touching those columns.
    #
    # Gate note (reconciliation E-8): the condition is `fp_value or fp3_value or
    # svid`. All three are independent client-side signals — dropping `or svid`
    # would silently reintroduce the exact race this upsert-stub exists to fix
    # for a batch that carries only the durable _rta_svid server cookie and no
    # fingerprint at all; dropping `or fp3_value` would lose an fp3 that resolved
    # on a later batch than fp2.
    if fp_value or fp3_value or svid:
        try:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            seen_times: list[datetime] = []
            for event in batch.events:
                ts = getattr(event, "ts", None)
                if isinstance(ts, datetime):
                    seen_times.append(ts.replace(tzinfo=None) if ts.tzinfo else ts)
            first_seen = min(seen_times) if seen_times else now
            last_seen = max(seen_times) if seen_times else now
            await db.execute(
                pg_insert(Visitor)
                .values(
                    site_id=batch.site_id,
                    visitor_id=batch.visitor_id,
                    first_seen=first_seen,
                    last_seen=last_seen,
                    total_pageviews=0,
                    total_sessions=0,
                    avg_time_on_page=0.0,
                    max_scroll_depth=0,
                    pages_visited=[],
                    intent_score=0.0,
                    identity_status="anonymous",
                    enrichment_status="pending",
                    segmented=False,
                    fingerprint=fp_value,
                    fingerprint_v3=fp3_value,
                    server_visitor_id=svid,
                )
                .on_conflict_do_update(
                    index_elements=["site_id", "visitor_id"],
                    set_={
                        # Write-once: keep existing stamp; fill only when NULL.
                        "fingerprint": sa_text(
                            "COALESCE(visitors.fingerprint, EXCLUDED.fingerprint)"
                        ),
                        # Same write-once semantics as fingerprint: fp3 resolves
                        # asynchronously on the client and may land on a later
                        # batch, so never blank a stored value with a NULL.
                        "fingerprint_v3": sa_text(
                            "COALESCE(visitors.fingerprint_v3, EXCLUDED.fingerprint_v3)"
                        ),
                        "server_visitor_id": sa_text(
                            "COALESCE(visitors.server_visitor_id, EXCLUDED.server_visitor_id)"
                        ),
                        # Prefer earliest first_seen if stub raced ahead of events.
                        "first_seen": sa_text(
                            "LEAST(visitors.first_seen, EXCLUDED.first_seen)"
                        ),
                        # WS2 Detector A — server-side fingerprint mismatch.
                        #
                        # The COALESCE above SILENTLY DISCARDS an incoming
                        # fingerprint whenever the row already has one. That
                        # discarded value is EVIDENCE: same visitor_id (Brave and
                        # friends keep the first-party cookie), different fp2 =>
                        # the fingerprinting surface is randomized per session.
                        #
                        # Evaluated inside THIS statement rather than a preceding
                        # SELECT: /ingest is the hottest path in the API and the
                        # comparison needs exactly the two values the upsert
                        # already has in hand, so it costs zero extra round-trips.
                        #
                        # The stored `fingerprint` column keeps its write-once
                        # COALESCE semantics untouched above — only the new flag
                        # is written, and it is sticky-OR like do_not_resolve.
                        # Both NOT NULL guards matter: a NULL on either side is
                        # "no evidence", not a mismatch.
                        #
                        # fp3 is compared the same way, with the same guards —
                        # but adds little detection power, because fpBase (and
                        # therefore fp3) already contains canvas + webgl, so a
                        # canvas-farbling browser rotates fp2 and fp3 together.
                        # See the FARBLED_MISMATCH_SQL comment at module level.
                        "has_unstable_fingerprint": sa_text(
                            FARBLED_MISMATCH_SQL
                        ),
                    },
                )
            )
            needs_commit = True
        except Exception as exc:
            logger.warning(
                "visitor_stub_ensure_failed",
                error=str(exc),
                visitor_id=batch.visitor_id[:8],
            )

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
                # newsletter/identify/mailto_click/url_param). Sanitized, capped,
                # and normalized to the canonical source enum (AC13) — an
                # unrecognized value becomes "other", never free text.
                from apps.api.models.visitor_email import normalize_source

                src = normalize_source(event.source)
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
    """Run visitor aggregation in a background task with its own DB session.

    Capacity-hardening Phase 3 (W1) checklist item 7 + instruction E16(b), plus
    Phase 1 F6/F7/F8. Two coordination checks run BEFORE any DB work, both
    against Redis so they hold across containers (the in-memory `_aggregating`
    set above is only a cheap per-process first layer and cannot dedup N
    containers):

    1. `agg:sweep_pending:{site_id}` — the repair sweep's yield marker. When it is
       set the sweep is waiting for the debounce key so it can run a FULL
       recompute, which is a strict superset of this run's work. We stand down and
       deliberately do NOT take the debounce key; taking it is exactly what
       starves the sweep on a continuously-ingesting site.
    2. `agg:debounce:{site_id}` — mutex held until ``release`` in ``finally``
       (F8). Already held means another run covers these events.

    Redis degraded (``acquired is None``): flag ON → SKIP agg (F7, same as
    sweep); flag OFF → fail open so the 204 contract is unchanged.
    """
    lock = None
    try:
        from sqlalchemy import text

        from apps.api.config import settings as _s
        from apps.api.services import aggregation_debounce as _dbnc
        from apps.api.services.visitor_aggregator import (
            advance_watermark,
            aggregate_visitors_for_site,
            get_aggregation_watermark,
        )

        pending = await _dbnc.exists(_dbnc.sweep_pending_key(site_id))
        if pending is True:
            logger.info("aggregation_yielded_to_sweep", site_id=site_id)
            return

        lock = _dbnc.RunLock(site_id, _s.aggregation_min_interval_seconds)
        acquired = await lock.acquire()
        if acquired is False:
            logger.info("aggregation_debounced", site_id=site_id)
            return
        if acquired is None:
            if _s.aggregation_incremental_enabled:
                logger.warning(
                    "aggregation_ingest_skipped_redis_degraded", site_id=site_id
                )
                return
            logger.info(
                "aggregation_ingest_redis_degraded_proceeding", site_id=site_id
            )

        async with async_session() as db:
            # F5 — ingest agg must not inherit a 30s request timeout.
            await apply_long_job_statement_timeout(db)
            since = None
            run_started_at = None
            if _s.aggregation_incremental_enabled:
                # A NULL watermark means "never aggregated" → full recompute,
                # then stamp from the clock taken BEFORE the read (F6).
                since = await get_aggregation_watermark(db, site_id)
                if since is None:
                    run_started_at = (await db.execute(text("SELECT now()"))).scalar()
            await aggregate_visitors_for_site(db, site_id, since=since)
            if run_started_at is not None:
                await advance_watermark(db, site_id, run_started_at)
    except Exception as e:
        logger.warning("background_aggregate_failed", error=str(e), site_id=site_id)
    finally:
        if lock is not None:
            await lock.release()
