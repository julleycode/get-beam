"""Shared test fixtures for the EasyTrack test suite.

Unit tests: no DB, no network — use mocks.
Integration tests: require local PostgreSQL + Redis (via docker-compose).
"""

import os
import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Force test environment before anything imports settings
os.environ.setdefault("APP_ENV", "test")
# Port 5433, matching infra/docker-compose.yml and the config default. Docker
# Postgres deliberately avoids 5432 because a natively-installed Postgres usually
# owns it — pointing tests there hits that instance instead and fails on
# authentication, which reads like a broken test rather than a wrong address.
# Override by exporting DATABASE_URL to run against a different server.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")  # Use DB 15 for tests
# Fernet keys for link/token crypto (unsubscribe + _bid links, BYOK vault).
# Real keys come from the environment in prod; tests just need valid ones.
from cryptography.fernet import Fernet as _Fernet  # noqa: E402

os.environ.setdefault("ENCRYPTION_KEY", _Fernet.generate_key().decode())
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", _Fernet.generate_key().decode())
# Never let a real Gemini key (e.g. from ../../.env) leak into tests — the
# agentic /ai/ask path would silently hit the live API before its fallback.
# Env vars beat dotenv in pydantic-settings, so an empty value forces mocks.
os.environ.setdefault("GEMINI_API_KEY", "")
# Developer .env may set RESOLUTION_RETRY_COOLDOWN_DAYS=0 to disable the
# no-retry lock locally. Tests that assert "recently_attempted" need the
# historical 30-day window, so pin it before Settings loads.
os.environ.setdefault("RESOLUTION_RETRY_COOLDOWN_DAYS", "30")
# Same leak, different shape: a developer who turns the agent flags ON in their
# root .env to exercise the feature locally would flip the DEFAULT every flag
# test measures against. Two tests assert flag-OFF behaviour explicitly
# (ingest drops a GPTBot UA; offers.json keeps the shared-cache header), and
# both go red on that machine while staying green in CI — the worst kind of
# failure, because it looks like the feature broke rather than the environment.
# Pinned to the code default here; a test that needs a flag ON sets it itself
# via monkeypatch, which is unaffected by these values.
for _flag in (
    "AGENT_DETECTION_ENABLED",
    "AGENT_GATEWAY_ENABLED",
    "AGENT_MARKER_ENABLED",
):
    os.environ.setdefault(_flag, "false")
# The geo cross-check is the one new-behaviour flag that defaults ON in code, and
# it makes a SECOND outbound provider call (ipinfo.io). Existing canary tests
# patch only `geoip.httpx`, so leaving it on sends real requests for every
# fixture IP — the canary integration file went from seconds to ~10 minutes of
# DNS/connect timeouts before this line existed. Pinned off; the tests that
# exercise the cross-check enable it themselves via monkeypatch and stub
# `_lookup_second`, which never touches the network.
os.environ.setdefault("GEO_CROSSCHECK_ENABLED", "false")


def _native_enum_names(metadata) -> list[str]:
    """Collect PG native ENUM type names declared anywhere on the metadata.

    Metadata-driven on purpose: `import apps.api.main` registers every model
    before this runs, so new Enum columns are picked up without edits here.
    """
    names: list[str] = []
    for table in metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, sa.Enum) and col.type.name and col.type.name not in names:
                names.append(col.type.name)
    return names


@pytest_asyncio.fixture
async def test_engine():
    """Create a test database engine (requires local postgres running).

    Setup and teardown are enum-safe: `drop_all` leaves PG native ENUM types
    behind, so a second pytest process would hit duplicate-type errors. We
    drop tables first, then the types (CASCADE on a type while stale tables
    still reference it would silently drop their columns).
    """
    from apps.api.config import settings

    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=5,
    )

    # Create all tables
    from apps.api.models.database import Base
    # Import ALL models to register them (avoids relationship resolution errors)
    from apps.api.models.event import Event  # noqa: F401
    from apps.api.models.visitor import Visitor  # noqa: F401
    from apps.api.models.site import Site  # noqa: F401
    from apps.api.models.company import Company  # noqa: F401
    from apps.api.models.user import User  # noqa: F401
    from apps.api.models.api_key import UserApiKey  # noqa: F401
    from apps.api.models.social_account import SocialAccount  # noqa: F401
    from apps.api.models.post import Post  # noqa: F401
    from apps.api.models.message import Message  # noqa: F401
    from apps.api.models.campaign import Campaign  # noqa: F401
    from apps.api.models.draft import Draft  # noqa: F401
    from apps.api.models.enrichment import EnrichmentProfile  # noqa: F401
    from apps.api.models.segment import Segment  # noqa: F401
    from apps.api.models.voice_example import VoiceExample  # noqa: F401
    from apps.api.models.beam_identity import BeamIdentityNode  # noqa: F401
    from apps.api.models.visitor_email import VisitorEmail  # noqa: F401
    from apps.api.models.suppression import SuppressionEntry  # noqa: F401
    from apps.api.models.email_sender_account import EmailSenderAccount  # noqa: F401
    # Importing the app registers EVERY model on Base.metadata (waitlist,
    # feature requests, stripe_events, ...). Without this, table creation
    # depends on which test imported apps.api.main first — the explicit list
    # above goes stale silently (stripe_events was missing).
    import apps.api.main  # noqa: F401

    enum_names = _native_enum_names(Base.metadata)

    async with engine.begin() as conn:
        # Clear residue from any prior crashed/incomplete run: tables first,
        # then the native enum types they referenced.
        await conn.run_sync(Base.metadata.drop_all)
        for name in enum_names:
            await conn.execute(sa.text(f'DROP TYPE IF EXISTS "{name}" CASCADE'))
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Cleanup: drop all tables, then the enum types they left behind
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        for name in enum_names:
            await conn.execute(sa.text(f'DROP TYPE IF EXISTS "{name}" CASCADE'))

    await engine.dispose()


@pytest_asyncio.fixture
async def test_db(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional test DB session that rolls back after each test."""
    session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        yield session
        # Rollback any uncommitted changes
        await session.rollback()


@pytest_asyncio.fixture
async def test_client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP test client with DB + rate-limit isolation.

    - Overrides get_db so endpoints use the test engine (same event loop)
    - Patches async_session in modules that import it directly
    - Disables slowapi rate limiter
    """
    from apps.api.main import app
    from apps.api.models.database import get_db
    from apps.api.services.rate_limiter import limiter

    test_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    limiter.enabled = False

    # The /demo budget is a raw Redis daily counter (demo:budget:{day}) on the
    # real test Redis — it survives across pytest runs, so after ~50 demo
    # requests in one day every /demo endpoint starts 429ing ("Demo limit
    # reached"). Reset it here; fail open like _enforce_demo_budget does.
    try:
        from redis.asyncio import Redis

        from apps.api.config import settings as _settings

        _r = Redis.from_url(_settings.redis_url)
        try:
            _keys = await _r.keys("demo:budget:*")
            if _keys:
                await _r.delete(*_keys)
        finally:
            await _r.aclose()
    except Exception:
        pass

    import apps.api.routers.demo as demo_mod
    import apps.api.routers.events as events_mod
    # The visitors background jobs (which use async_session directly) live in
    # visitors_helpers since the Phase 15 split — patch there, not in visitors.
    import apps.api.routers.visitors_helpers as visitors_helpers_mod

    orig = {
        "demo": demo_mod.async_session,
        "events": events_mod.async_session,
        "visitors_helpers": visitors_helpers_mod.async_session,
    }
    demo_mod.async_session = test_session_factory
    events_mod.async_session = test_session_factory
    visitors_helpers_mod.async_session = test_session_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    demo_mod.async_session = orig["demo"]
    events_mod.async_session = orig["events"]
    visitors_helpers_mod.async_session = orig["visitors_helpers"]
    app.dependency_overrides.clear()
    limiter.enabled = True
