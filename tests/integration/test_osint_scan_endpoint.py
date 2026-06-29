"""Integration tests for POST /visitors/{site_id}/{visitor_id}/osint-scan.

Pins the endpoint wiring — feature-flag gate, identified+email requirement,
daily budget gate, and the background job's read-modify-write of
social_context['osint_scan'] (which MUST preserve an existing deep_research).
The scanner engines themselves are stubbed (covered by the unit suite).

Requires: PostgreSQL running locally (via docker-compose).
"""

import uuid as uuidlib
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration

FAKE_BLOB = {
    "status": "complete",
    "scanned_at": "2026-06-14T00:00:00+00:00",
    "engines": ["user-scanner", "holehe"],
    "accounts": [
        {"site_name": "Etsy", "category": "shopping", "url": "https://etsy.com",
         "kind": "profile", "confidence": "confirmed", "source_engine": "user-scanner",
         "extra": {"username": "jdoe"}},
    ],
    "summary": {"registered_count": 1, "profile_count": 1, "checked": 5,
                "total": 200, "partial": False, "skipped_categories": ["adult"]},
    "message": "Found 1 profile(s) with details and 1 site registration(s).",
}


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "OSINT Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _visitor(site_id, visitor_id, **overrides):
    from apps.api.models.visitor import Visitor

    defaults = dict(
        site_id=site_id, visitor_id=visitor_id,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        pages_visited=[], ip_address="203.0.113.9", intent_score=80.0,
        identity_status="anonymous", enrichment_status="pending",
    )
    defaults.update(overrides)
    return Visitor(**defaults)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def osint_setup(test_client, test_db):
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import IdentifiedVisitor
    from apps.api.models.enrichment import EnrichmentProfile

    email = f"osint-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"osint_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="OSINT Site", url="https://o.example.com"))

    # v-id: identified + email + a profile carrying existing deep_research
    test_db.add(_visitor(site_id, "v-id", identity_status="identified"))
    test_db.add(IdentifiedVisitor(
        site_id=site_id, visitor_id="v-id", email="found@acme.com",
        full_name="Found Person", resolution_provider="manual", confidence_score=1.0,
    ))
    test_db.add(EnrichmentProfile(
        site_id=site_id, visitor_id="v-id", enrichment_completeness=0.3,
        social_context={"deep_research": "EXISTING RESEARCH", "researched_at": "2026-01-01"},
    ))
    # v-anon: identified status but NO IdentifiedVisitor row → "not_identified"
    test_db.add(_visitor(site_id, "v-noemail", identity_status="identified"))
    await test_db.commit()
    return {"token": token, "site_id": site_id, "user": user}


class TestOsintScanEndpoint:
    @pytest.mark.asyncio
    async def test_disabled_when_flag_off(self, test_client, osint_setup, monkeypatch):
        monkeypatch.setattr("apps.api.routers.visitors.settings.enable_osint_scan", False)
        resp = await test_client.post(
            f"/api/v1/visitors/{osint_setup['site_id']}/v-id/osint-scan",
            headers=_auth(osint_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "disabled"

    @pytest.mark.asyncio
    async def test_not_identified_without_email(self, test_client, osint_setup, monkeypatch):
        monkeypatch.setattr("apps.api.routers.visitors.settings.enable_osint_scan", True)
        resp = await test_client.post(
            f"/api/v1/visitors/{osint_setup['site_id']}/v-noemail/osint-scan",
            headers=_auth(osint_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "not_identified"

    @pytest.mark.asyncio
    async def test_unknown_visitor_404(self, test_client, osint_setup, monkeypatch):
        monkeypatch.setattr("apps.api.routers.visitors.settings.enable_osint_scan", True)
        resp = await test_client.post(
            f"/api/v1/visitors/{osint_setup['site_id']}/nope/osint-scan",
            headers=_auth(osint_setup["token"]),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_budget_limit_blocks(self, test_client, osint_setup, monkeypatch):
        monkeypatch.setattr("apps.api.routers.visitors.settings.enable_osint_scan", True)
        monkeypatch.setattr("apps.api.routers.visitors.settings.osint_scan_daily_budget", 0)
        resp = await test_client.post(
            f"/api/v1/visitors/{osint_setup['site_id']}/v-id/osint-scan",
            headers=_auth(osint_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "limit_reached"

    @pytest.mark.asyncio
    async def test_started_runs_job_and_preserves_deep_research(
        self, test_client, test_db, osint_setup, monkeypatch
    ):
        from apps.api.models.enrichment import EnrichmentProfile

        monkeypatch.setattr("apps.api.routers.visitors.settings.enable_osint_scan", True)
        monkeypatch.setattr("apps.api.routers.visitors.settings.osint_scan_daily_budget", 50)

        async def fake_scan(email):
            return FAKE_BLOB

        monkeypatch.setattr("apps.api.routers.visitors_helpers.run_osint_scan", fake_scan)

        resp = await test_client.post(
            f"/api/v1/visitors/{osint_setup['site_id']}/v-id/osint-scan",
            headers=_auth(osint_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "started"

        # Background job ran during the ASGI request. Re-read fresh.
        test_db.expire_all()
        profile = (
            await test_db.execute(
                select(EnrichmentProfile).where(
                    EnrichmentProfile.site_id == osint_setup["site_id"],
                    EnrichmentProfile.visitor_id == "v-id",
                )
            )
        ).scalar_one()
        sc = profile.social_context or {}
        # OSINT results written...
        assert sc.get("osint_scan", {}).get("status") == "complete"
        assert sc["osint_scan"]["summary"]["profile_count"] == 1
        # ...AND the pre-existing deep_research was preserved (not clobbered).
        assert sc.get("deep_research") == "EXISTING RESEARCH"
