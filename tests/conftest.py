"""Shared test fixtures for the EasyTrack test suite.

Unit tests: no DB, no network — use mocks.
Integration tests: require local PostgreSQL + Redis (via docker-compose).
"""

import os
import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Force test environment before anything imports settings
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://retarget:retarget_dev@localhost:5432/retarget_agent_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")  # Use DB 15 for tests


@pytest_asyncio.fixture
async def test_engine():
    """Create a test database engine (requires local postgres running)."""
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

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Cleanup: drop all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

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
    from apps.api.routers.social_auth import limiter

    test_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    limiter.enabled = False

    import apps.api.routers.demo as demo_mod
    import apps.api.routers.events as events_mod
    import apps.api.routers.visitors as visitors_mod

    orig = {
        "demo": demo_mod.async_session,
        "events": events_mod.async_session,
        "visitors": visitors_mod.async_session,
    }
    demo_mod.async_session = test_session_factory
    events_mod.async_session = test_session_factory
    visitors_mod.async_session = test_session_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    demo_mod.async_session = orig["demo"]
    events_mod.async_session = orig["events"]
    visitors_mod.async_session = orig["visitors"]
    app.dependency_overrides.clear()
    limiter.enabled = True


@pytest_asyncio.fixture
async def auth_token(test_client: AsyncClient) -> str:
    """Get a valid auth token for testing authenticated endpoints.

    Creates a test user if needed and returns a JWT token.
    """
    from apps.api.config import settings
    import jwt
    from datetime import datetime, timedelta

    # Create a simple JWT token for testing
    payload = {
        "sub": "test-user-id",
        "exp": datetime.utcnow() + timedelta(hours=1),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token
