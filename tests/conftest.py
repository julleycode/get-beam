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
os.environ.setdefault("MOCK_EXTERNAL_APIS", "true")
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
async def test_client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP test client for the FastAPI app."""
    from apps.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


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
