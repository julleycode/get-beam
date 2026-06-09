"""Integration tests for the demo identify endpoint.

Covers Phase 1 (identity graphs in demo), Phase 3 (fingerprint pre-matching).
Requires: PostgreSQL running locally (via docker-compose).
"""

import json
import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
)


@pytest_asyncio.fixture
async def test_site(test_db):
    """Create a test site + user and return site_id."""
    from apps.api.models.user import User
    from apps.api.models.site import Site

    result = await test_db.execute(select(User).where(User.email == "demo-test@test.com"))
    user = result.scalar_one_or_none()
    if not user:
        user = User(email="demo-test@test.com", full_name="Demo Tester")
        test_db.add(user)
        await test_db.flush()

    site_id = "demo_test_site"
    result = await test_db.execute(select(Site).where(Site.site_id == site_id))
    if not result.scalar_one_or_none():
        test_db.add(Site(
            site_id=site_id,
            user_id=user.id,
            name="Demo Test Site",
            url="https://demo-test.example.com",
        ))
        await test_db.flush()

    await test_db.commit()
    return site_id


class TestDemoIdentify:
    """POST /api/v1/demo/identify"""

    @pytest.mark.asyncio
    async def test_returns_200(self, test_client):
        resp = await test_client.post(
            "/api/v1/demo/identify",
            content=json.dumps({}),
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_response_has_matched_field(self, test_client):
        resp = await test_client.post(
            "/api/v1/demo/identify",
            content=json.dumps({}),
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        )
        data = resp.json()
        assert "matched" in data

    @pytest.mark.asyncio
    async def test_response_has_providers_tried(self, test_client):
        resp = await test_client.post(
            "/api/v1/demo/identify",
            content=json.dumps({}),
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        )
        data = resp.json()
        assert "providers_tried" in data
        providers = data["providers_tried"]
        assert isinstance(providers, list)
        assert len(providers) >= 1

    @pytest.mark.asyncio
    async def test_response_has_level_when_matched(self, test_client):
        resp = await test_client.post(
            "/api/v1/demo/identify",
            content=json.dumps({}),
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        )
        data = resp.json()
        if data.get("matched"):
            assert "level" in data
            assert data["level"] in ("person", "company", "device")

    @pytest.mark.asyncio
    async def test_accepts_fingerprint_param(self, test_client):
        resp = await test_client.post(
            "/api/v1/demo/identify",
            content=json.dumps({"fingerprint": "fp2_test123abc"}),
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_empty_body_accepted(self, test_client):
        resp = await test_client.post(
            "/api/v1/demo/identify",
            content=json.dumps({}),
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 200


class TestDemoFingerprintPreMatch:
    """Phase 3: fingerprint pre-matching in demo endpoint."""

    @pytest.mark.asyncio
    async def test_fingerprint_match_returns_device_level(self, test_client, test_db, test_site):
        """When a visitor with same fingerprint exists, return device-level match."""
        from apps.api.models.visitor import Visitor

        fp = f"fp2_match_{uuid.uuid4().hex[:8]}"

        test_db.add(Visitor(
            site_id=test_site,
            visitor_id=f"pixel-visitor-{uuid.uuid4().hex[:8]}",
            fingerprint=fp,
            first_seen=datetime(2026, 6, 1),
            last_seen=datetime(2026, 6, 1),
        ))
        await test_db.commit()

        resp = await test_client.post(
            "/api/v1/demo/identify",
            content=json.dumps({"fingerprint": fp}),
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        )
        data = resp.json()

        assert data.get("matched") is True
        assert data.get("fingerprint_matched") is True

    @pytest.mark.asyncio
    async def test_no_match_without_fingerprint(self, test_client, test_db, test_site):
        """Without fingerprint param, no device-level match even if visitors exist."""
        from apps.api.models.visitor import Visitor

        test_db.add(Visitor(
            site_id=test_site,
            visitor_id=f"pixel-no-match-{uuid.uuid4().hex[:8]}",
            fingerprint="fp2_existing_but_not_sent",
            first_seen=datetime(2026, 6, 1),
            last_seen=datetime(2026, 6, 1),
        ))
        await test_db.commit()

        resp = await test_client.post(
            "/api/v1/demo/identify",
            content=json.dumps({}),
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        )
        data = resp.json()

        # May still match via identity graphs (mock), but NOT device-level from fingerprint
        if data.get("matched") and data.get("level") == "device":
            assert data.get("resolution_provider") != "fingerprint" or data.get("fp_matched") is True

    @pytest.mark.asyncio
    async def test_nonexistent_fingerprint_no_device_match(self, test_client):
        """Fingerprint that doesn't exist in DB should not produce device match."""
        resp = await test_client.post(
            "/api/v1/demo/identify",
            content=json.dumps({"fingerprint": "fp2_does_not_exist_in_db"}),
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        )
        data = resp.json()

        if data.get("level") == "device":
            # If device match, it must NOT be from our fake fingerprint
            assert data.get("resolution_provider") != "fingerprint"
