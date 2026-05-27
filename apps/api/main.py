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
from apps.api.models.social_account import SocialAccount  # noqa: F401
from apps.api.models.post import Post  # noqa: F401
from apps.api.models.message import Message  # noqa: F401
from apps.api.models.draft import Draft  # noqa: F401
from apps.api.models.voice_example import VoiceExample  # noqa: F401
from apps.api.routers import events, visitors, segments, campaigns, exports, sites, auth, api_keys
from apps.api.routers import social_auth, drafts, feed, social_accounts
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
            # Pre-merge tables: add updated_at inherited from Base
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "ALTER TABLE sites ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "ALTER TABLE visitors ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "ALTER TABLE identified_visitors ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "ALTER TABLE segments ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "ALTER TABLE enrichment_profiles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "ALTER TABLE user_api_keys ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "ALTER TABLE campaign_touchpoints ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            # Phase 1A: IP address on visitors for identity resolution
            "ALTER TABLE visitors ADD COLUMN IF NOT EXISTS ip_address VARCHAR(45)",
            "ALTER TABLE visitors ADD COLUMN IF NOT EXISTS company_domain VARCHAR(253)",
            # Phase 2A: New event columns for bot filtering and tracking accuracy
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS user_agent VARCHAR(500) DEFAULT ''",
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS page_title VARCHAR(500) DEFAULT ''",
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS page_path VARCHAR(2000) DEFAULT ''",
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
    title="ReTargetAgent API",
    version="0.2.0",
    lifespan=lifespan,
)

# Wire up slowapi rate limiter from social_auth router
app.state.limiter = social_auth.limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_cors_origins = [
    settings.frontend_url,  # e.g. https://retarget-agent.vercel.app
    "http://localhost:3000",
    "http://localhost:3001",
]
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
from starlette.middleware.base import BaseHTTPMiddleware

class PixelCORSMiddleware(BaseHTTPMiddleware):
    """Allow cross-origin requests to /api/v1/events/ingest from any origin.

    The tracking pixel is embedded on customer websites, so it must be able
    to POST events from any domain.  CORSMiddleware only allows the dashboard
    origin, so we intercept the pixel path here and short-circuit.
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/api/v1/events/ingest", "/pixel/tracker.js"):
            if request.method == "OPTIONS":
                return Response(
                    status_code=200,
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "POST, OPTIONS",
                        "Access-Control-Allow-Headers": "Content-Type",
                        "Access-Control-Max-Age": "86400",
                    },
                )
            response = await call_next(request)
            response.headers["Access-Control-Allow-Origin"] = "*"
            return response
        return await call_next(request)


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


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}


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
