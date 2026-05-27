"""Integration tests for the event ingestion endpoint.

Requires: PostgreSQL + Redis running locally (via docker-compose).
Uses test_client and test_db from conftest.py which auto-create tables.
"""

import json

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def test_site_id(test_db):
    """Create a test site using ORM and return its site_id."""
    from apps.api.models.user import User
    from apps.api.models.site import Site

    # Ensure test user
    result = await test_db.execute(select(User).where(User.email == "test-ingest@test.com"))
    user = result.scalar_one_or_none()
    if not user:
        user = User(email="test-ingest@test.com", full_name="Test User")
        test_db.add(user)
        await test_db.flush()

    site_id = "test_site_ingest"
    result = await test_db.execute(select(Site).where(Site.site_id == site_id))
    if not result.scalar_one_or_none():
        test_db.add(Site(site_id=site_id, user_id=user.id, name="Test Site", url="https://test-ingest.example.com"))
        await test_db.flush()

    await test_db.commit()
    return site_id


class TestEventIngestion:
    """Test POST /api/v1/events/ingest"""

    @pytest.mark.asyncio
    async def test_valid_batch_returns_204(self, test_client, test_site_id):
        """Valid event batch should return 204 No Content."""
        payload = {
            "site_id": test_site_id,
            "visitor_id": "test-visitor-001",
            "events": [
                {
                    "type": "pageview",
                    "url": "https://test-ingest.example.com/",
                    "page_path": "/",
                    "page_title": "Home",
                    "user_agent": "Mozilla/5.0 Chrome/120.0.0.0",
                    "ts": "2026-05-27T00:00:00",
                }
            ],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_bot_ua_returns_204_silently(self, test_client, test_site_id):
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
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Googlebot/2.1 (+http://www.google.com/bot.html)",
            },
        )
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_invalid_site_returns_403(self, test_client, test_site_id):
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
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_malformed_json_returns_400(self, test_client, test_site_id):
        """Malformed JSON should return 400."""
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content="not-json{{{",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_text_plain_content_type_works(self, test_client, test_site_id):
        """text/plain should work (sendBeacon uses this for CORS)."""
        payload = {
            "site_id": test_site_id,
            "visitor_id": "beacon-visitor-001",
            "events": [
                {
                    "type": "pageview",
                    "url": "https://test-ingest.example.com/pricing",
                    "ts": "2026-05-27T00:00:00",
                }
            ],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 204
