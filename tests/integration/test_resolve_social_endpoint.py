"""Integration tests for POST /visitors/{site_id}/{visitor_id}/resolve-social.

Pins endpoint+job wiring (flag gate, identified+email, budget, background job
persistence) with the pipeline itself stubbed. Pipeline logic is unit-tested.

Requires: PostgreSQL running locally (via docker-compose).
"""

import uuid as uuidlib
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Resolve Social Tester"},
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
        pages_visited=[], ip_address="203.0.113.11", intent_score=80.0,
        identity_status="anonymous", enrichment_status="pending",
    )
    defaults.update(overrides)
    return Visitor(**defaults)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def setup(test_client, test_db):
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import IdentifiedVisitor
    from apps.api.models.enrichment import EnrichmentProfile

    email = f"resolvesoc-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"rs_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="RS Site", url="https://rs.example.com"))
    test_db.add(_visitor(site_id, "v-id", identity_status="identified"))
    test_db.add(IdentifiedVisitor(
        site_id=site_id, visitor_id="v-id", email="found@acme.com",
        full_name="Found Person", resolution_provider="manual", confidence_score=1.0,
    ))
    test_db.add(EnrichmentProfile(
        site_id=site_id, visitor_id="v-id", enrichment_completeness=0.3,
        social_context={"deep_research": "OLD", "osint_scan": {"status": "complete"}},
    ))
    test_db.add(_visitor(site_id, "v-noemail", identity_status="identified"))
    await test_db.commit()
    return {"token": token, "site_id": site_id, "user": user}


class TestResolveSocialEndpoint:
    @pytest.mark.asyncio
    async def test_disabled_when_flag_off(self, test_client, setup, monkeypatch):
        monkeypatch.setattr("apps.api.routers.visitors.settings.enable_osint_scan", False)
        resp = await test_client.post(
            f"/api/v1/visitors/{setup['site_id']}/v-id/resolve-social",
            headers=_auth(setup["token"]),
        )
        assert resp.status_code == 200 and resp.json()["status"] == "disabled"

    @pytest.mark.asyncio
    async def test_not_identified(self, test_client, setup, monkeypatch):
        monkeypatch.setattr("apps.api.routers.visitors.settings.enable_osint_scan", True)
        resp = await test_client.post(
            f"/api/v1/visitors/{setup['site_id']}/v-noemail/resolve-social",
            headers=_auth(setup["token"]),
        )
        assert resp.status_code == 200 and resp.json()["status"] == "not_identified"

    @pytest.mark.asyncio
    async def test_budget_blocks(self, test_client, setup, monkeypatch):
        monkeypatch.setattr("apps.api.routers.visitors.settings.enable_osint_scan", True)
        monkeypatch.setattr("apps.api.routers.visitors.settings.osint_scan_daily_budget", 0)
        resp = await test_client.post(
            f"/api/v1/visitors/{setup['site_id']}/v-id/resolve-social",
            headers=_auth(setup["token"]),
        )
        assert resp.status_code == 200 and resp.json()["status"] == "limit_reached"

    @pytest.mark.asyncio
    async def test_started_runs_job_preserves_keys(self, test_client, test_db, setup, monkeypatch):
        from apps.api.models.enrichment import EnrichmentProfile

        monkeypatch.setattr("apps.api.routers.visitors.settings.enable_osint_scan", True)
        monkeypatch.setattr("apps.api.routers.visitors.settings.osint_scan_daily_budget", 50)

        async def fake_resolve(db, *, visitor, identified, profile, run_gemini=True):
            merged = dict(profile.social_context or {})
            merged["social_resolution"] = {
                "status": "complete", "profiles": [
                    {"site_name": "GitHub", "url": "https://github.com/x", "kind": "profile",
                     "confidence": "likely", "source_engine": "maigret", "extra": {}},
                ],
                "stages_run": ["osint_free", "maigret", "rule_base"],
                "paid": {"used": False}, "message": "ok",
            }
            profile.social_context = merged
            await db.commit()
            return {"status": "complete", "profiles": 1, "paid_used": False}

        monkeypatch.setattr("apps.api.routers.visitors_helpers.resolve_social", fake_resolve)

        resp = await test_client.post(
            f"/api/v1/visitors/{setup['site_id']}/v-id/resolve-social",
            headers=_auth(setup["token"]),
        )
        assert resp.status_code == 200 and resp.json()["status"] == "started"

        test_db.expire_all()
        profile = (await test_db.execute(
            select(EnrichmentProfile).where(
                EnrichmentProfile.site_id == setup["site_id"],
                EnrichmentProfile.visitor_id == "v-id",
            )
        )).scalar_one()
        sc = profile.social_context or {}
        assert sc["social_resolution"]["status"] == "complete"
        assert len(sc["social_resolution"]["profiles"]) == 1
        # pre-existing keys preserved through the pipeline write
        assert sc.get("deep_research") == "OLD"
        assert sc.get("osint_scan", {}).get("status") == "complete"
