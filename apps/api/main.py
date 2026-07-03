import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from apps.api.config import settings
from apps.api.models.database import engine, Base
from apps.api.models.api_key import UserApiKey  # noqa: F401 — register for create_all
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
from apps.api.routers import events, visitors, segments, campaigns, exports, sites, auth, api_keys
from apps.api.routers import social_auth, drafts, feed, social_accounts, companies, feature_requests, demo
from apps.api.routers import billing, engagement, waitlist, unsubscribe, webhooks, blog, privacy
from apps.api.routers import known_contacts, costs, ai, dashboard, crm, changelog, click, open_pixel
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
    """Allow cross-origin requests to /api/v1/events/ingest from any origin.

    Pure ASGI middleware (not BaseHTTPMiddleware) to avoid event-loop conflicts
    with asyncpg when running under pytest / ASGITransport.
    """

    _PIXEL_PATHS = {"/api/v1/events/ingest", "/pixel/tracker.js"}

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "") not in self._PIXEL_PATHS:
            await self.app(scope, receive, send)
            return

        if scope.get("method") == "OPTIONS":
            response = Response(
                status_code=200,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Access-Control-Max-Age": "86400",
                },
            )
            await response(scope, receive, send)
            return

        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"access-control-allow-origin", b"*"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cors)


app.add_middleware(PixelCORSMiddleware)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(events.router, prefix="/api/v1/events", tags=["events"])
app.include_router(sites.router, prefix="/api/v1/sites", tags=["sites"])
app.include_router(known_contacts.router, prefix="/api/v1/sites", tags=["known-contacts"])
app.include_router(visitors.router, prefix="/api/v1/visitors", tags=["visitors"])
app.include_router(costs.router, prefix="/api/v1/costs", tags=["costs"])
app.include_router(ai.router, prefix="/api/v1/ai", tags=["ai"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(segments.router, prefix="/api/v1/segments", tags=["segments"])
app.include_router(campaigns.router, prefix="/api/v1/campaigns", tags=["campaigns"])
app.include_router(exports.router, prefix="/api/v1/exports", tags=["exports"])
app.include_router(api_keys.router, prefix="/api/v1/api-keys", tags=["api-keys"])
app.include_router(crm.router, prefix="/api/v1/crm", tags=["crm"])
app.include_router(privacy.router, prefix="/api/v1/privacy", tags=["privacy"])

# ── EasyEngage routers ──────────────────────────────────
app.include_router(social_auth.router, prefix="/api/v1/social", tags=["social-auth"])
app.include_router(social_accounts.router, prefix="/api/v1/social", tags=["social-accounts"])
app.include_router(drafts.router, prefix="/api/v1/drafts", tags=["drafts"])
app.include_router(feed.router, prefix="/api/v1/feed", tags=["feed"])
app.include_router(companies.router, prefix="/api/v1/companies", tags=["companies"])
app.include_router(feature_requests.router, prefix="/api/v1/feature-requests", tags=["feature-requests"])
app.include_router(demo.router, prefix="/api/v1/demo", tags=["demo"])
app.include_router(billing.router, prefix="/api/v1/billing", tags=["billing"])
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
