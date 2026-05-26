from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from apps.api.config import settings
from apps.api.models.database import engine, Base
from apps.api.models.api_key import UserApiKey  # noqa: F401 — register for create_all
from apps.api.models.event import Event as EventModel  # noqa: F401 — register for create_all
from apps.api.routers import events, visitors, segments, campaigns, exports, sites, auth, api_keys

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("starting_up", env=settings.app_env)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add missing columns to existing tables (safe to re-run)
        for stmt in [
            "ALTER TABLE resolution_logs ADD COLUMN IF NOT EXISTS cost_usd FLOAT NOT NULL DEFAULT 0",
            "ALTER TABLE resolution_logs ADD COLUMN IF NOT EXISTS response_time_ms INTEGER",
            "ALTER TABLE visitors ADD COLUMN IF NOT EXISTS segmented BOOLEAN DEFAULT FALSE",
            "ALTER TABLE segment_members ADD COLUMN IF NOT EXISTS assigned_at TIMESTAMP DEFAULT NOW()",
        ]:
            try:
                await conn.execute(__import__("sqlalchemy").text(stmt))
            except Exception:
                pass
    yield
    await engine.dispose()
    logger.info("shut_down")


app = FastAPI(
    title="ReTargetAgent API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(events.router, prefix="/api/v1/events", tags=["events"])
app.include_router(sites.router, prefix="/api/v1/sites", tags=["sites"])
app.include_router(visitors.router, prefix="/api/v1/visitors", tags=["visitors"])
app.include_router(segments.router, prefix="/api/v1/segments", tags=["segments"])
app.include_router(campaigns.router, prefix="/api/v1/campaigns", tags=["campaigns"])
app.include_router(exports.router, prefix="/api/v1/exports", tags=["exports"])
app.include_router(api_keys.router, prefix="/api/v1/api-keys", tags=["api-keys"])


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}


@app.get("/pixel/tracker.js")
async def serve_pixel() -> Response:
    import pathlib
    pixel_path = pathlib.Path(__file__).parent.parent / "pixel" / "src" / "tracker.js"
    if pixel_path.exists():
        content = pixel_path.read_text()
    else:
        content = "// pixel not found"
    return Response(
        content=content,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=3600", "Access-Control-Allow-Origin": "*"},
    )
