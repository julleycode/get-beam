"""Dashboard overview aggregate endpoint tests (`/api/v1/dashboard/overview`).

Integration: requires local PostgreSQL (docker-compose) via conftest fixtures.
Verifies the Overview fan-out (sites + per-site stats) collapses into one call.
"""

import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.dependencies import get_current_user
from apps.api.main import app
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.models.visitor import Visitor

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def user_client(test_client: AsyncClient, test_engine) -> AsyncClient:
    """test_client plus a persisted user that owns one site with one visitor."""
    user_id = uuid.uuid4()
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        s.add(User(id=user_id, email="op@getbeam.fyi"))
        s.add(Site(site_id="site_test1", user_id=user_id, name="Test", url="https://t.co"))
        now = datetime.utcnow()  # visitors timestamps are naive UTC
        s.add(
            Visitor(
                site_id="site_test1",
                visitor_id="v_test1",
                first_seen=now,
                last_seen=now,
                identity_status="identified",
            )
        )
        await s.commit()
    app.dependency_overrides[get_current_user] = lambda: User(id=user_id, email="op@getbeam.fyi")
    yield test_client
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_overview_returns_sites_and_stats(user_client: AsyncClient) -> None:
    resp = await user_client.get("/api/v1/dashboard/overview")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Site list returned, and a stats entry keyed by site_id (the N+1 collapsed).
    assert [s["site_id"] for s in data["sites"]] == ["site_test1"]
    assert "site_test1" in data["stats"]

    stats = data["stats"]["site_test1"]
    assert stats["total_visitors"] == 1
    assert stats["identified"] == 1
    # Full VisitorStatsResponse shape (frontend reuses it directly).
    assert "identify_daily_limit" in stats
    assert "eligible_for_resolution" in stats


@pytest.mark.asyncio
async def test_overview_empty_when_no_sites(test_client: AsyncClient) -> None:
    uid = uuid.uuid4()
    app.dependency_overrides[get_current_user] = lambda: User(id=uid, email="empty@getbeam.fyi")
    try:
        resp = await test_client.get("/api/v1/dashboard/overview")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["sites"] == []
        assert body["stats"] == {}
    finally:
        app.dependency_overrides.pop(get_current_user, None)
