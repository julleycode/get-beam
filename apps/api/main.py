from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

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
from apps.api.routers import events, visitors, segments, campaigns, exports, sites, auth, api_keys
from apps.api.routers import social_auth, drafts, feed, social_accounts, companies, feature_requests, demo
from apps.api.routers import billing, engagement, waitlist, unsubscribe, webhooks, blog
from apps.api.jobs.scheduler import start_scheduler, stop_scheduler
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings.validate_secret_key()
    logger.info("starting_up", env=settings.app_env)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add missing columns to existing tables (safe to re-run)
        for stmt in [
            "ALTER TABLE resolution_logs ADD COLUMN IF NOT EXISTS cost_usd FLOAT NOT NULL DEFAULT 0",
            "ALTER TABLE resolution_logs ADD COLUMN IF NOT EXISTS response_time_ms INTEGER",
            "ALTER TABLE visitors ADD COLUMN IF NOT EXISTS segmented BOOLEAN DEFAULT FALSE",
            "ALTER TABLE segment_members ADD COLUMN IF NOT EXISTS assigned_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS campaign_type VARCHAR(20) DEFAULT 'email'",
            "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS platform VARCHAR(20)",
            # EasyEngage: User model new columns
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS clerk_user_id VARCHAR(255) UNIQUE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS tone_preference VARCHAR(50) DEFAULT 'casual'",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(200)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL",
            # Pre-merge tables: add updated_at inherited from Base
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS event_id VARCHAR(64)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_events_event_id ON events (event_id)",
            "ALTER TABLE sites ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "ALTER TABLE visitors ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "ALTER TABLE identified_visitors ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "ALTER TABLE segments ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "ALTER TABLE enrichment_profiles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "ALTER TABLE user_api_keys ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "ALTER TABLE campaign_touchpoints ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "ALTER TABLE resolution_logs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            # Phase 1A: IP address on visitors for identity resolution
            "ALTER TABLE visitors ADD COLUMN IF NOT EXISTS ip_address VARCHAR(45)",
            "ALTER TABLE visitors ADD COLUMN IF NOT EXISTS company_domain VARCHAR(253)",
            # Phase 2A: New event columns for bot filtering and tracking accuracy
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS user_agent VARCHAR(500) DEFAULT ''",
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS page_title VARCHAR(500) DEFAULT ''",
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS page_path VARCHAR(2000) DEFAULT ''",
            # Enrichment: add facebook_url column
            "ALTER TABLE enrichment_profiles ADD COLUMN IF NOT EXISTS facebook_url VARCHAR(500)",
            # Feed: track post source (visitors / following / my_posts)
            "ALTER TABLE posts ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'following'",
            # Fix source: user's own tweets should be 'my_posts', not default 'following'
            """UPDATE posts SET source = 'my_posts'
               WHERE source = 'following'
                 AND author_username = (
                     SELECT sa.username FROM social_accounts sa
                     WHERE sa.id = posts.social_account_id
                 )""",
            # Phase: browser fingerprint for cross-session identification
            "ALTER TABLE visitors ADD COLUMN IF NOT EXISTS fingerprint VARCHAR(50)",
            # Phase 2: expand fingerprint column for 128-bit v2 fingerprints
            "ALTER TABLE visitors ALTER COLUMN fingerprint TYPE VARCHAR(64)",
            # Phase: visitor_emails table (created by create_all, but ensure index exists)
            # The table itself is created by Base.metadata.create_all above;
            # these are safety-net additions for pre-existing deployments.
            # Billing: new columns on users
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS plan VARCHAR(20) NOT NULL DEFAULT 'free'",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(50)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS current_period_end TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_identified_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS billing_cycle_reset_at TIMESTAMP WITH TIME ZONE",
            # Social Intelligence: new columns on enrichment_profiles
            "ALTER TABLE enrichment_profiles ADD COLUMN IF NOT EXISTS social_context JSONB",
            "ALTER TABLE enrichment_profiles ADD COLUMN IF NOT EXISTS social_context_updated_at TIMESTAMP WITH TIME ZONE",
            # Auto-draft: new columns on drafts
            "ALTER TABLE drafts ADD COLUMN IF NOT EXISTS auto_generated BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE drafts ADD COLUMN IF NOT EXISTS visitor_id VARCHAR(100)",
            "ALTER TABLE drafts ADD COLUMN IF NOT EXISTS context_summary VARCHAR(500)",
            # Feature requests: admin note for status management
            "ALTER TABLE feature_requests ADD COLUMN IF NOT EXISTS admin_note TEXT",
            # Waitlist: one-use invite tokens (consumed at signup)
            "ALTER TABLE waitlist_signups ADD COLUMN IF NOT EXISTS used_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE waitlist_signups ADD COLUMN IF NOT EXISTS used_by_clerk_user_id VARCHAR(255)",
            # Blog: scheduled publishing
            "ALTER TABLE blog_posts ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMP WITH TIME ZONE",
        ]:
            try:
                await conn.execute(__import__("sqlalchemy").text(stmt))
            except Exception as e:
                logger.debug("migration_skipped", stmt=stmt[:60], reason=str(e))
        # Backfill IP addresses on existing visitors from their latest event
        try:
            await conn.execute(__import__("sqlalchemy").text("""
                UPDATE visitors v SET ip_address = sub.ip
                FROM (
                    SELECT DISTINCT ON (visitor_id, site_id) visitor_id, site_id, ip_address AS ip
                    FROM events
                    WHERE ip_address != '' AND ip_address IS NOT NULL
                    ORDER BY visitor_id, site_id, created_at DESC
                ) sub
                WHERE v.visitor_id = sub.visitor_id AND v.site_id = sub.site_id
                  AND v.ip_address IS NULL
            """))
        except Exception as e:
            logger.debug("ip_backfill_skipped", reason=str(e))

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
app.include_router(visitors.router, prefix="/api/v1/visitors", tags=["visitors"])
app.include_router(segments.router, prefix="/api/v1/segments", tags=["segments"])
app.include_router(campaigns.router, prefix="/api/v1/campaigns", tags=["campaigns"])
app.include_router(exports.router, prefix="/api/v1/exports", tags=["exports"])
app.include_router(api_keys.router, prefix="/api/v1/api-keys", tags=["api-keys"])

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
        pixel_path = pathlib.Path(__file__).parent.parent / "pixel" / "src" / "tracker.js"
        _pixel_js_cache = pixel_path.read_text() if pixel_path.exists() else "// pixel not found"
    return Response(
        content=_pixel_js_cache,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=3600", "Access-Control-Allow-Origin": "*"},
    )
