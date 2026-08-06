import asyncio
import os
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from urllib.parse import parse_qsl

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from apps.api.config import settings
from apps.api.models.database import engine, Base
from apps.api.models.api_key import UserApiKey  # noqa: F401 — register for create_all
from apps.api.models.request_log import RequestLog  # noqa: F401 — register for create_all
from apps.api.services import request_logger
from apps.api.models.event import Event as EventModel  # noqa: F401 — register for create_all
from apps.api.models.visitor_email import VisitorEmail  # noqa: F401 — register for create_all
from apps.api.models.social_account import SocialAccount  # noqa: F401
from apps.api.models.post import Post  # noqa: F401
from apps.api.models.message import Message  # noqa: F401
from apps.api.models.draft import Draft  # noqa: F401
from apps.api.models.voice_example import VoiceExample  # noqa: F401
from apps.api.models.company import Company  # noqa: F401 — register for create_all
from apps.api.models.feature_request import FeatureRequest  # noqa: F401 — register for create_all
from apps.api.models.engagement_attribution import EngagementAttribution  # noqa: F401 — register for create_all
from apps.api.models.beam_identity import BeamIdentityNode  # noqa: F401 — register for create_all
from apps.api.models.waitlist import WaitlistSignup  # noqa: F401 — register for create_all
from apps.api.models.stripe_event import StripeEvent  # noqa: F401 — register for create_all
from apps.api.models.blog_post import BlogPost  # noqa: F401 — register for create_all
from apps.api.models.api_usage import ApiUsageLog  # noqa: F401 — register for create_all
from apps.api.models.crm_connection import CrmConnection  # noqa: F401 — register for create_all
from apps.api.models.changelog_entry import ChangelogEntry  # noqa: F401 — register for create_all
from apps.api.models.outcome import ConversionGoal, CampaignClick, Conversion  # noqa: F401 — register for create_all
from apps.api.models.agent_visit import AgentVisit  # noqa: F401 — register for create_all
from apps.api.models.agent_fetch_event import AgentFetchEvent  # noqa: F401 — register for create_all
from apps.api.models.agent_handoff_link import AgentHandoffLink  # noqa: F401 — register for create_all
from apps.api.models.company_graph import CompanyGraphNode  # noqa: F401 — register for create_all
from apps.api.models.identity_signal import IdentitySignal  # noqa: F401 — register for create_all
from apps.api.models.ad_connection import AdConnection  # noqa: F401 — register for create_all
from apps.api.models.ad_audience_link import AdAudienceLink  # noqa: F401 — register for create_all
from apps.api.models.agent_profile import AgentProfile  # noqa: F401 — register for create_all
from apps.api.models.site_tombstone import SiteTombstone  # noqa: F401 — register for create_all
from apps.api.models.job_change_event import JobChangeEvent  # noqa: F401 — register for create_all
from apps.api.routers import events, visitors, segments, campaigns, exports, sites, auth, api_keys
from apps.api.routers import social_auth, drafts, feed, social_accounts, companies, feature_requests, demo
from apps.api.routers import billing, engagement, waitlist, unsubscribe, webhooks, blog, privacy
from apps.api.routers import known_contacts, costs, ai, dashboard, crm, changelog, click, open_pixel
from apps.api.routers import email_sender_oauth, outcomes, referrals, agents, ads
from apps.api.routers import ingest_health
from apps.api.routers import contacts
from apps.api.routers import hot_contacts
from apps.api.routers import request_logs
from apps.api.routers import agent_profile, agent_gateway, agent_mcp
from apps.api.jobs.scheduler import start_scheduler, stop_scheduler
from apps.api.services.pii_encryption_hooks import register_pii_encryption_hooks
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# Configure structlog once, at import time. Keep the console-friendly output
# (timestamp + level + event) but render exceptions as PLAIN tracebacks with NO
# local variables. structlog's default rich formatter prints every frame's
# locals — which leaked secrets into production logs (e.g. the OpenRouter API
# key sat in a failing frame's `api_key` local and was printed verbatim on every
# draft-generation error). `plain_traceback` never shows locals.
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
        structlog.dev.ConsoleRenderer(
            exception_formatter=structlog.dev.plain_traceback,
        ),
    ],
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Phase 05 (5b): dual-write encrypted PII columns on every ORM insert/update.
register_pii_encryption_hooks()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings.validate_secret_key()
    logger.info("starting_up", env=settings.app_env)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Schema is managed by Alembic now (P3): `alembic upgrade head` runs in
        # the Dockerfile CMD before the app boots. The old per-boot ALTER block
        # (~55 statements) and the events->visitors IP backfill were removed —
        # both redundant: the Alembic baseline already has every column, and the
        # write paths set the data at creation (visitor_aggregator sets
        # ip_address from the latest event; sync.py saves the correct post
        # `source`). create_all stays only as a harmless safety net for
        # fresh/local DBs; it no-ops once tables exist.

    # Start background feed-sync scheduler
    start_scheduler()
    logger.info("scheduler_started")

    yield

    stop_scheduler()
    from apps.api.services.redis_client import close_redis
    await close_redis()
    await engine.dispose()
    logger.info("shut_down")


app = FastAPI(
    title="Beam API",
    version="0.2.0",
    lifespan=lifespan,
)

# Wire up shared slowapi rate limiter
from apps.api.services.rate_limiter import limiter as shared_limiter
app.state.limiter = shared_limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_cors_origins = [
    settings.frontend_url,  # e.g. https://getbeam.fyi
    "http://localhost:3000",
    "http://localhost:3001",
    "https://getbeam.fyi",
    "https://www.getbeam.fyi",
    "https://retarget-agent.vercel.app",
    "https://retarget-agent-git-main-tranthaiwork-droids-projects.vercel.app",
]
# De-duplicate and drop empty strings (settings.frontend_url may be unset)
_cors_origins = [o for o in dict.fromkeys(_cors_origins) if o]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static media (the Beam landing launch video) from the API host. Vercel's
# static CDN won't serve a file this large, so the 7.5MB launch.mp4 lives here and
# is referenced as https://api.getbeam.fyi/static/launch.mp4. check_dir=False so a
# missing dir can never crash API boot — it would just 404 the asset.
app.mount(
    "/static",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), check_dir=False),
    name="static",
)


# ── Open CORS for pixel ingest (runs from any customer domain) ─────
# Starlette middleware order: last add_middleware = outermost = runs first.
# This must be added AFTER CORSMiddleware so it intercepts /ingest requests
# before CORSMiddleware can reject them.
class PixelCORSMiddleware:
    """Allow cross-origin pixel traffic from any customer origin.

    Ingest is credentialed: browsers only store/send the HttpOnly ``_rta_svid``
    cookie when ``Access-Control-Allow-Origin`` mirrors the request Origin
    (not ``*``) and ``Access-Control-Allow-Credentials: true``. Tracker script
    loads stay wildcard — ``<script src>`` does not need credentials.

    Pure ASGI middleware (not BaseHTTPMiddleware) to avoid event-loop conflicts
    with asyncpg when running under pytest / ASGITransport.
    """

    _INGEST_PATH = "/api/v1/events/ingest"
    _PIXEL_PATHS = {_INGEST_PATH, "/pixel/tracker.js"}

    def __init__(self, app):
        self.app = app

    @staticmethod
    def _origin(scope) -> bytes | None:
        for key, value in scope.get("headers", []):
            if key == b"origin":
                return value
        return None

    @classmethod
    def _ingest_cors_headers(cls, scope) -> list[tuple[bytes, bytes]]:
        origin = cls._origin(scope)
        if origin:
            return [
                (b"access-control-allow-origin", origin),
                (b"access-control-allow-credentials", b"true"),
                (b"vary", b"Origin"),
            ]
        # Non-browser clients (no Origin) — wildcard is fine; no cookie jar.
        return [(b"access-control-allow-origin", b"*")]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "") not in self._PIXEL_PATHS:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        credentialed = path == self._INGEST_PATH

        if scope.get("method") == "OPTIONS":
            headers = {
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Max-Age": "86400",
            }
            if credentialed:
                origin = self._origin(scope)
                if origin:
                    headers["Access-Control-Allow-Origin"] = origin.decode("latin-1")
                    headers["Access-Control-Allow-Credentials"] = "true"
                    headers["Vary"] = "Origin"
                else:
                    headers["Access-Control-Allow-Origin"] = "*"
            else:
                headers["Access-Control-Allow-Origin"] = "*"
            response = Response(status_code=200, headers=headers)
            await response(scope, receive, send)
            return

        cors_extra = (
            self._ingest_cors_headers(scope)
            if credentialed
            else [(b"access-control-allow-origin", b"*")]
        )

        _REPLACE = {
            b"access-control-allow-origin",
            b"access-control-allow-credentials",
        }

        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                # Inner CORSMiddleware may have already set ACAO/ACAC; replace
                # so credentialed ingest never ends up with duplicate/conflicting values.
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k not in _REPLACE
                ]
                headers.extend(cors_extra)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cors)


app.add_middleware(PixelCORSMiddleware)


# ── Ingest body-size guard (abuse hardening P1) ────────────────────
class IngestBodySizeLimitMiddleware:
    """Reject oversized POST /ingest bodies BEFORE they are buffered/parsed.

    Pure ASGI middleware (not BaseHTTPMiddleware) for the same reason as
    PixelCORSMiddleware above: BaseHTTPMiddleware's anyio task-group wrapping
    conflicts with asyncpg's event loop under pytest / ASGITransport.

    Two layers:
      1. Content-Length fast path — reject without touching receive() at all.
      2. Running byte count across every http.request message — the only guard
         that holds for chunked transfer-encoding (no Content-Length) or a
         forged/understated Content-Length header.

    The rejection response carries NO request echo and NO user data (AC-9).

    Registered AFTER PixelCORSMiddleware so it is the outermost middleware and
    an oversized body is dropped before any other middleware does work.
    """

    _GUARDED_PATHS = {"/api/v1/events/ingest"}

    def __init__(self, app):
        self.app = app

    @staticmethod
    async def _reject(send) -> None:
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", b"18"),
                (b"access-control-allow-origin", b"*"),
            ],
        })
        await send({"type": "http.response.body", "body": b"payload too large\n"})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "") not in self._GUARDED_PATHS:
            await self.app(scope, receive, send)
            return

        max_bytes = settings.ingest_body_max_bytes

        # Fast path: an honest Content-Length lets us reject without reading a
        # single body byte. A forged/absent one falls through to the counter.
        for key, value in scope.get("headers", []):
            if key == b"content-length":
                try:
                    if int(value) > max_bytes:
                        await self._reject(send)
                        return
                except (ValueError, TypeError):
                    pass  # Malformed header — the running counter still guards.
                break

        state = {"seen": 0, "rejected": False}

        async def counting_receive():
            message = await receive()
            if message["type"] == "http.request":
                state["seen"] += len(message.get("body", b""))
                if state["seen"] > max_bytes:
                    state["rejected"] = True
                    # Stop feeding the app: report an empty, complete body so the
                    # downstream parser fails fast instead of hanging on more_body.
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def guarded_send(message):
            # Once oversized, suppress whatever the app produced and emit 413.
            if state["rejected"]:
                if message["type"] == "http.response.start":
                    await IngestBodySizeLimitMiddleware._reject(send)
                return
            await send(message)

        await self.app(scope, counting_receive, guarded_send)


app.add_middleware(IngestBodySizeLimitMiddleware)


# ── Admin request/response capture (debug observability) ──────────
class RequestResponseLogMiddleware:
    """Capture request + response JSON for DROPPED or FLAGGED requests.

    Pure ASGI middleware for the same reason as the two above: BaseHTTPMiddleware's
    anyio task-group wrapping conflicts with asyncpg's event loop under pytest.

    Registered LAST, so it is the OUTERMOST middleware — it sees the final status
    code every inner layer produced, including the 413 that
    IngestBodySizeLimitMiddleware synthesizes and the CORS rejections. An inner
    position would miss exactly the rejections this exists to explain.

    Hot-path cost when ``request_log_enabled`` is False: one boolean check, then
    straight through. Bodies are only buffered once the flag is on, and only up
    to ``request_log_max_body_bytes``.

    The write is dispatched as a detached task AFTER the response has been fully
    sent, so no client ever waits on a log insert.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not settings.request_log_enabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if request_logger.is_excluded(path):
            await self.app(scope, receive, send)
            return

        max_bytes = settings.request_log_max_body_bytes
        started = time.perf_counter()
        captured = {
            "req": bytearray(),
            "res": bytearray(),
            "status": 500,
            "res_headers": {},
        }

        def _absorb(body: bytes) -> None:
            """Append into the capture buffer, never past the cap + 1 sentinel byte.

            The extra byte is what lets decode_body detect truncation from length
            alone, so nothing else has to track a separate flag.
            """
            if body and len(captured["req"]) <= max_bytes:
                captured["req"].extend(body[: max_bytes + 1 - len(captured["req"])])

        # Pre-buffer the request body BEFORE calling the app.
        #
        # Passively wrapping receive() is not enough: the ingest bot filter returns
        # 204 before anything reads the body, so a wrapped receive() is never
        # invoked and the payload of the very request we most want to explain is
        # lost. Reading it up front is the only way to capture a body the app
        # rejected unread.
        #
        # Bounded on purpose: we stop buffering once past the cap and let the
        # remainder stream through untouched. This middleware is OUTSIDE the
        # body-size guard, so an unbounded pre-read here would buffer a hostile
        # 100MB body before that guard could reject it.
        prebuffered: list[dict] = []
        if scope.get("method") in ("POST", "PUT", "PATCH", "DELETE"):
            total = 0
            while True:
                message = await receive()
                prebuffered.append(message)
                if message["type"] != "http.request":
                    break  # http.disconnect — nothing more is coming
                chunk = message.get("body", b"")
                _absorb(chunk)
                total += len(chunk)
                if not message.get("more_body", False) or total > max_bytes:
                    break

        replay = iter(prebuffered)

        async def capturing_receive():
            # Replay what we pre-read, then fall through to the live stream for
            # anything past the cap.
            message = next(replay, None)
            if message is not None:
                return message
            message = await receive()
            if message["type"] == "http.request":
                _absorb(message.get("body", b""))
            return message

        async def capturing_send(message):
            if message["type"] == "http.response.start":
                captured["status"] = message.get("status", 500)
                captured["res_headers"] = {
                    k.decode("latin-1"): v.decode("latin-1")
                    for k, v in message.get("headers", [])
                }
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if body and len(captured["res"]) <= max_bytes:
                    captured["res"].extend(body[: max_bytes + 1 - len(captured["res"])])
            await send(message)

        try:
            await self.app(scope, capturing_receive, capturing_send)
        finally:
            # `finally`, not the happy path: an unhandled exception propagating
            # out of the app is precisely the case worth capturing, and Starlette
            # will still have sent a 500 through capturing_send.
            try:
                state = scope.get("state") or {}
                reason = request_logger.should_log(
                    captured["status"],
                    path,
                    explicit_reason=state.get("log_reason"),
                )
                if reason:
                    headers = {
                        k.decode("latin-1"): v.decode("latin-1")
                        for k, v in scope.get("headers", [])
                    }
                    query = scope.get("query_string", b"").decode("latin-1")
                    asyncio.ensure_future(
                        request_logger.persist_log(
                            method=scope.get("method", ""),
                            path=path,
                            query_params=(
                                dict(parse_qsl(query, keep_blank_values=True))
                                if query
                                else None
                            ),
                            status_code=captured["status"],
                            duration_ms=(time.perf_counter() - started) * 1000,
                            reason=reason,
                            reason_detail=state.get("log_reason_detail"),
                            site_id=state.get("site_id"),
                            user_id=state.get("log_user_id"),
                            client_ip=(
                                headers.get("cf-connecting-ip")
                                or headers.get("x-forwarded-for", "").split(",")[0].strip()
                                or (scope.get("client") or ("", 0))[0]
                            ),
                            user_agent=headers.get("user-agent"),
                            headers=headers,
                            request_body_raw=bytes(captured["req"]),
                            response_body_raw=bytes(captured["res"]),
                        )
                    )
            except Exception:
                logger.warning("request_log_dispatch_failed", path=path)


app.add_middleware(RequestResponseLogMiddleware)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(events.router, prefix="/api/v1/events", tags=["events"])
app.include_router(sites.router, prefix="/api/v1/sites", tags=["sites"])
app.include_router(known_contacts.router, prefix="/api/v1/sites", tags=["known-contacts"])
app.include_router(ingest_health.router, prefix="/api/v1/sites", tags=["ingest-health"])
# Imported contacts (Phase 4) — distinct surface from known-contacts above:
# creates contactable identities, not a hash-only exclusion list.
#
# ORDER IS LOAD-BEARING: hot_contacts registers the literal
# /{site_id}/contacts/hot, contacts.router registers the parametric
# /{site_id}/contacts/{visitor_id}. FastAPI matches in registration order, so
# the literal route MUST come first — reversed, every /contacts/hot request is
# swallowed as visitor_id="hot" and silently 404s. Covered by
# tests/unit/test_hot_contacts_query.py::test_hot_route_is_not_shadowed_by_visitor_id_route.
app.include_router(hot_contacts.router, prefix="/api/v1/sites", tags=["imported-contacts"])
app.include_router(contacts.router, prefix="/api/v1/sites", tags=["imported-contacts"])
app.include_router(
    request_logs.router, prefix="/api/v1/admin/request-logs", tags=["admin-request-logs"]
)
app.include_router(visitors.router, prefix="/api/v1/visitors", tags=["visitors"])
app.include_router(agents.router, prefix="/api/v1/agents", tags=["agents"])
app.include_router(costs.router, prefix="/api/v1/costs", tags=["costs"])
app.include_router(ai.router, prefix="/api/v1/ai", tags=["ai"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(segments.router, prefix="/api/v1/segments", tags=["segments"])
app.include_router(campaigns.router, prefix="/api/v1/campaigns", tags=["campaigns"])
app.include_router(outcomes.router, prefix="/api/v1/outcomes", tags=["outcomes"])
app.include_router(exports.router, prefix="/api/v1/exports", tags=["exports"])
app.include_router(api_keys.router, prefix="/api/v1/api-keys", tags=["api-keys"])
app.include_router(crm.router, prefix="/api/v1/crm", tags=["crm"])
app.include_router(ads.router, prefix="/api/v1/ads", tags=["ads"])
app.include_router(privacy.router, prefix="/api/v1/privacy", tags=["privacy"])

# ── Agent gateway (agent-gateway Phase 1+2) ─────────────
# Authed CRUD for the customer's agent-facing profile.
app.include_router(
    agent_profile.router, prefix="/api/v1/agent-profile", tags=["agent-profile"]
)
# PUBLIC, unauthenticated, read-only agent surface. Doubly gated by
# settings.agent_gateway_enabled AND AgentProfile.enabled — both default OFF, so
# these routes answer 404 (dormant, not revealed) until an operator enables them.
app.include_router(agent_gateway.router, prefix="/api/v1/agent", tags=["agent-gateway"])
app.include_router(agent_mcp.router, prefix="/api/v1/agent", tags=["agent-mcp"])

# ── EasyEngage routers ──────────────────────────────────
app.include_router(social_auth.router, prefix="/api/v1/social", tags=["social-auth"])
app.include_router(email_sender_oauth.router, prefix="/api/v1/email", tags=["email-sender"])
app.include_router(social_accounts.router, prefix="/api/v1/social", tags=["social-accounts"])
app.include_router(drafts.router, prefix="/api/v1/drafts", tags=["drafts"])
app.include_router(feed.router, prefix="/api/v1/feed", tags=["feed"])
app.include_router(companies.router, prefix="/api/v1/companies", tags=["companies"])
app.include_router(feature_requests.router, prefix="/api/v1/feature-requests", tags=["feature-requests"])
app.include_router(demo.router, prefix="/api/v1/demo", tags=["demo"])
app.include_router(billing.router, prefix="/api/v1/billing", tags=["billing"])
app.include_router(referrals.router, prefix="/api/v1/referrals", tags=["referrals"])
app.include_router(engagement.router, prefix="/api/v1/engagement", tags=["engagement"])
app.include_router(waitlist.router, prefix="/api/v1/waitlist", tags=["waitlist"])
app.include_router(blog.router, prefix="/api/v1/blog", tags=["blog"])
app.include_router(changelog.router, prefix="/api/v1/changelog", tags=["changelog"])
# Email click-tracking redirect (short public path — recipients click it directly).
app.include_router(click.router, prefix="/c", tags=["click"])
# Email open-tracking pixel (short public path — mail clients load it as an image).
app.include_router(open_pixel.router, prefix="/o", tags=["open-pixel"])

# ── Public unsubscribe (CAN-SPAM compliance, no auth) ──
app.include_router(unsubscribe.router, tags=["unsubscribe"])

# ── Provider webhooks (SendGrid bounce → do_not_email; secret-token auth) ──
app.include_router(webhooks.router, tags=["webhooks"])


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Liveness probe — always returns 200 if the process is running."""
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready() -> dict[str, str]:
    """Readiness probe — returns 200 only when the DB is reachable."""
    from fastapi.responses import JSONResponse
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:
        logger.warning("health_ready_db_failed", error=str(exc))
        return JSONResponse(status_code=503, content={"status": "unavailable", "detail": "database unreachable"})


_pixel_js_cache: str | None = None


@app.get("/pixel/tracker.js")
async def serve_pixel() -> Response:
    global _pixel_js_cache
    if _pixel_js_cache is None:
        import pathlib
        pixel_dir = pathlib.Path(__file__).parent.parent / "pixel" / "src"
        # Serve the minified build (kept <5KB gzipped); fall back to source.
        minified = pixel_dir / "tracker.min.js"
        source = pixel_dir / "tracker.js"
        pixel_path = minified if minified.exists() else source
        _pixel_js_cache = pixel_path.read_text() if pixel_path.exists() else "// pixel not found"
    return Response(
        content=_pixel_js_cache,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=3600", "Access-Control-Allow-Origin": "*"},
    )
