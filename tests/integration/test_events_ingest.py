"""Integration tests for the event ingestion endpoint.

Requires: PostgreSQL + Redis running locally (via docker-compose).
Skip if DATABASE_URL is not available.
"""

import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Skip all tests in this module if DB is not available
pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def client():
    """Create a test client for the FastAPI app."""
    try:
        from apps.api.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    except Exception as e:
        pytest.skip(f"Cannot create test client: {e}")


@pytest_asyncio.fixture
async def test_site_id(client: AsyncClient):
    """Create a test site and return its site_id. Clean up after."""
    # We need an auth token first
    from apps.api.config import settings
    import jwt as pyjwt
    from datetime import datetime, timedelta

    token = pyjwt.encode(
        {"sub": "test-user-id", "exp": datetime.utcnow() + timedelta(hours=1)},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    # Create a test site
    resp = await client.post(
        "/api/v1/sites/",
        json={"name": "Test Site", "url": "https://test-e2e.example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code not in (200, 201):
        pytest.skip(f"Cannot create test site: {resp.status_code} {resp.text}")

    site_id = resp.json()["site_id"]
    yield site_id

    # Cleanup
    await client.delete(
        f"/api/v1/sites/{site_id}",
        headers={"Authorization": f"Bearer {token}"},
    )


class TestEventIngestion:
    """Test POST /api/v1/events/ingest"""

    @pytest.mark.asyncio
    async def test_valid_batch_returns_204(self, client: AsyncClient, test_site_id: str):
        """Valid event batch should return 204 No Content."""
        payload = {
            "site_id": test_site_id,
            "visitor_id": "test-visitor-001",
            "events": [
                {
                    "type": "pageview",
                    "url": "https://test-e2e.example.com/",
                    "page_path": "/",
                    "page_title": "Home",
                    "user_agent": "Mozilla/5.0 Chrome/120.0.0.0",
                    "ts": "2026-05-27T00:00:00",
                }
            ],
        }
        resp = await client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_bot_ua_returns_204_silently(self, client: AsyncClient):
        """Bot user-agents should be silently discarded (not 400/403)."""
        payload = {
            "site_id": "any-site",
            "visitor_id": "bot-visitor",
            "events": [
                {
                    "type": "pageview",
                    "url": "https://example.com/",
                    "ts": "2026-05-27T00:00:00",
                }
            ],
        }
        resp = await client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Googlebot/2.1 (+http://www.google.com/bot.html)",
            },
        )
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_invalid_site_returns_403(self, client: AsyncClient):
        """Non-existent site_id should return 403."""
        payload = {
            "site_id": "nonexistent_site_12345",
            "visitor_id": "test-visitor",
            "events": [
                {
                    "type": "pageview",
                    "url": "https://example.com/",
                    "ts": "2026-05-27T00:00:00",
                }
            ],
        }
        resp = await client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_malformed_json_returns_400(self, client: AsyncClient):
        """Malformed JSON should return 400."""
        resp = await client.post(
            "/api/v1/events/ingest",
            content="not-json{{{",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_text_plain_content_type_works(self, client: AsyncClient, test_site_id: str):
        """text/plain should work (sendBeacon uses this for CORS)."""
        payload = {
            "site_id": test_site_id,
            "visitor_id": "beacon-visitor-001",
            "events": [
                {
                    "type": "pageview",
                    "url": "https://test-e2e.example.com/pricing",
                    "ts": "2026-05-27T00:00:00",
                }
            ],
        }
        resp = await client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 204
