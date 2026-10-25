"""Integration — POST /visitors/{site_id}/{visitor_id}/web-research (P2-G7).

Real Postgres + real route wiring (auth, tenant gate, commit). TinyFish
search/fetch are patched to deterministic results; MOCK_EXTERNAL_APIS=true so
the Gemini step uses `_mock_extract` (no live call).

Requires: PostgreSQL running locally (docker-compose, localhost:5433).
NEVER run against .env's DATABASE_URL (Supabase PROD) — pin a localhost DSN.
"""
import uuid as uuidlib
from datetime import datetime

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Web Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _mk_user_site(test_client, test_db, label: str):
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"{label}-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()
    site_id = f"{label}_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="Web Site", url="https://w.example.com"))
    await test_db.commit()
    return token, site_id


@pytest.fixture
def tinyfish_on(monkeypatch):
    from apps.api.services import tinyfish_reader as tr

    monkeypatch.setattr(tr.settings, "tinyfish_enrichment_enabled", True)
    monkeypatch.setattr(tr.settings, "mock_external_apis", True)

    async def search(query, **kw):
        return [{"url": "https://www.linkedin.com/in/ava", "title": "Ava Chen - Example Labs", "snippet": ""}]

    async def fetch(urls, **kw):
        return [{"url": u, "text": "Ava Chen, Example Labs"} for u in urls], []

    async def no_cache(key):
        return None

    async def claim():
        return True

    monkeypatch.setattr(tr.tinyfish_client, "search", search)
    monkeypatch.setattr(tr.tinyfish_client, "fetch", fetch)
    monkeypatch.setattr(tr, "_cache_get", no_cache)
    monkeypatch.setattr(tr, "_claim_cap", claim)


async def _seed_identified(test_db, site_id: str, visitor_id: str):
    from apps.api.models.enrichment import EnrichmentProfile
    from apps.api.models.visitor import IdentifiedVisitor, Visitor

    now = datetime.utcnow()
    test_db.add(Visitor(site_id=site_id, visitor_id=visitor_id, first_seen=now, last_seen=now,
                        pages_visited=[], ip_address="203.0.113.9", intent_score=50.0,
                        identity_status="identified", enrichment_status="pending"))
    test_db.add(IdentifiedVisitor(site_id=site_id, visitor_id=visitor_id, email="ava@examplelabs.com",
                                  full_name="Ava Chen", resolution_provider="form_capture",
                                  confidence_score=0.9))
    test_db.add(EnrichmentProfile(site_id=site_id, visitor_id=visitor_id, company_name="Example Labs"))
    await test_db.commit()


@pytest.mark.asyncio
async def test_web_research_updates_and_persists(test_client, test_db, tinyfish_on):
    from apps.api.models.enrichment import EnrichmentProfile

    token, site_id = await _mk_user_site(test_client, test_db, "web")
    await _seed_identified(test_db, site_id, "v-web")
    resp = await test_client.post(
        f"/api/v1/visitors/{site_id}/v-web/web-research",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "updated"
    assert "job_title" in body["filled"]
    test_db.expire_all()
    prof = (await test_db.execute(select(EnrichmentProfile).where(
        EnrichmentProfile.site_id == site_id, EnrichmentProfile.visitor_id == "v-web"))).scalar_one()
    assert prof.job_title == "Head of Growth"
    assert prof.social_context["web"]["sources"] == ["https://www.linkedin.com/in/ava"]


@pytest.mark.asyncio
async def test_web_research_foreign_user_404(test_client, test_db, tinyfish_on):
    _token, site_id = await _mk_user_site(test_client, test_db, "owner")
    await _seed_identified(test_db, site_id, "v-web2")
    other_token, _ = await _mk_user_site(test_client, test_db, "intruder")
    resp = await test_client.post(
        f"/api/v1/visitors/{site_id}/v-web2/web-research",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 404
