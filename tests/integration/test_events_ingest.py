"""Integration tests for the event ingestion endpoint.

Requires: PostgreSQL + Redis running locally (via docker-compose).
Uses test_client and test_db from conftest.py which auto-create tables.
"""

import json

import pytest
import pytest_asyncio
from sqlalchemy import select

# Realistic browser UA to avoid bot filter (is_bot returns True for empty UA)
_BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

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
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_deleted_site_403_expires_svid_cookie(self, test_client, test_site_id):
        """A deleted/unknown site returns 403 AND expires the durable HttpOnly
        _rta_svid_<site> cookie (only the server can clear an HttpOnly cookie),
        so a returning visitor's browser drops it. The pixel clears its own
        client cookies when it reads the 403."""
        site_id = "nonexistent_site_99999"
        payload = {
            "site_id": site_id,
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
            headers={"Content-Type": "text/plain", "User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 403
        set_cookies = resp.headers.get_list("set-cookie")
        svid = [c for c in set_cookies if "_rta_svid_nonexistent_site_99999" in c]
        assert svid, f"expected svid expiry Set-Cookie, got {set_cookies}"
        # Expired: Starlette delete_cookie emits Max-Age=0 + the 1970 epoch expiry.
        assert "Max-Age=0" in svid[0] or "01 Jan 1970" in svid[0], svid[0]

    @pytest.mark.asyncio
    async def test_malformed_json_returns_400(self, test_client, test_site_id):
        """Malformed JSON should return 400."""
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content="not-json{{{",
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
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


class TestEmailCaptureSource:
    """P4: a captured email is stored with the pixel-provided source label so we
    can tell a newsletter signup from a checkout from a login."""

    @staticmethod
    def _patch_validate(monkeypatch):
        async def _ok(_email):
            return (True, "")
        monkeypatch.setattr("apps.api.services.email_validator.validate_email", _ok)

    @pytest.mark.asyncio
    async def test_source_label_stored(self, test_client, test_site_id, test_db, monkeypatch):
        from apps.api.models.visitor_email import VisitorEmail

        self._patch_validate(monkeypatch)
        resp = await test_client.post(
            "/api/v1/events/ingest",
            json={
                "site_id": test_site_id,
                "visitor_id": "cap-src-001",
                "events": [{
                    "type": "form_email_capture",
                    "email": "Buyer@Shop.com",
                    "source": "newsletter",
                    "ts": "2026-06-30T00:00:00",
                }],
            },
            headers={"User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 204, resp.text
        row = (
            await test_db.execute(
                select(VisitorEmail).where(VisitorEmail.visitor_id == "cap-src-001")
            )
        ).scalar_one()
        assert row.email == "buyer@shop.com"  # normalized to lowercase
        assert row.source == "newsletter"

    @pytest.mark.asyncio
    async def test_source_defaults_to_form(self, test_client, test_site_id, test_db, monkeypatch):
        from apps.api.models.visitor_email import VisitorEmail

        self._patch_validate(monkeypatch)
        resp = await test_client.post(
            "/api/v1/events/ingest",
            json={
                "site_id": test_site_id,
                "visitor_id": "cap-src-002",
                "events": [{
                    "type": "form_email_capture",
                    "email": "x@shop.com",
                    "ts": "2026-06-30T00:00:00",
                }],
            },
            headers={"User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 204, resp.text
        row = (
            await test_db.execute(
                select(VisitorEmail).where(VisitorEmail.visitor_id == "cap-src-002")
            )
        ).scalar_one()
        assert row.source == "form"
