"""Cleanup endpoint integration: DELETE /{site_id}/cleanup-test.

Regression for the orphan-enrichment gap (2026-07-02): deleting test visitors
used to remove only Visitor + Event rows, leaving IdentifiedVisitor,
EnrichmentProfile and VisitorEmail rows behind as orphans no page can render.
Now the satellite rows must go with the visitor — and non-test visitors must
be untouched.

Against the test DB (requires local PostgreSQL via docker-compose).
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
        json={"email": email, "password": "testpass123", "full_name": "P"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _add_full_visitor(test_db, site_id: str, vid: str, now: datetime) -> None:
    """One visitor populated across Visitor + satellite tables."""
    from apps.api.models.enrichment import EnrichmentProfile
    from apps.api.models.event import Event
    from apps.api.models.visitor import IdentifiedVisitor, Visitor
    from apps.api.models.visitor_email import VisitorEmail

    test_db.add(Visitor(site_id=site_id, visitor_id=vid, first_seen=now, last_seen=now, intent_score=50.0))
    test_db.add(IdentifiedVisitor(site_id=site_id, visitor_id=vid, email=f"{vid}@acme.com", full_name="Lead X"))
    test_db.add(EnrichmentProfile(site_id=site_id, visitor_id=vid, twitter_handle="leadx", company_name="Acme"))
    test_db.add(VisitorEmail(site_id=site_id, visitor_id=vid, email=f"{vid}@acme.com", source="form"))
    test_db.add(Event(site_id=site_id, visitor_id=vid, event_type="pageview", url="https://c.example.com/", created_at=now))


@pytest_asyncio.fixture
async def cleanup_setup(test_client, test_db):
    """A site with one test-pattern visitor and one real visitor, both fully populated."""
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"cln-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"cln_site_{uuidlib.uuid4().hex[:8]}"
    test_vid = f"test-{uuidlib.uuid4().hex[:8]}"      # matches the "test%" cleanup pattern
    real_vid = f"v_{uuidlib.uuid4().hex[:8]}"          # must survive
    now = datetime.utcnow()

    test_db.add(Site(site_id=site_id, user_id=user.id, name="Cln", url="https://c.example.com"))
    _add_full_visitor(test_db, site_id, test_vid, now)
    _add_full_visitor(test_db, site_id, real_vid, now)
    await test_db.commit()

    return {"token": token, "site_id": site_id, "test_vid": test_vid, "real_vid": real_vid}


async def _count(test_db, model, site_id: str, vid: str) -> int:
    rows = (await test_db.execute(
        select(model).where(model.site_id == site_id, model.visitor_id == vid)
    )).scalars().all()
    return len(rows)


class TestCleanupTestVisitors:
    @pytest.mark.asyncio
    async def test_satellite_rows_deleted_with_visitor(self, test_client, test_db, cleanup_setup):
        from apps.api.models.enrichment import EnrichmentProfile
        from apps.api.models.event import Event
        from apps.api.models.visitor import IdentifiedVisitor, Visitor
        from apps.api.models.visitor_email import VisitorEmail

        sid = cleanup_setup["site_id"]
        test_vid = cleanup_setup["test_vid"]
        real_vid = cleanup_setup["real_vid"]

        resp = await test_client.delete(
            f"/api/v1/visitors/{sid}/cleanup-test", headers=_auth(cleanup_setup["token"])
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "cleaned"
        assert body["visitors_deleted"] == 1
        assert body["events_deleted"] == 1

        # Test visitor: gone from EVERY table — no orphans left behind.
        for model in (Visitor, Event, IdentifiedVisitor, EnrichmentProfile, VisitorEmail):
            assert await _count(test_db, model, sid, test_vid) == 0, model.__name__

        # Real visitor: fully intact.
        for model in (Visitor, Event, IdentifiedVisitor, EnrichmentProfile, VisitorEmail):
            assert await _count(test_db, model, sid, real_vid) == 1, model.__name__

    @pytest.mark.asyncio
    async def test_clean_site_reports_zero(self, test_client, test_db, cleanup_setup):
        # Second run right after the first: nothing left matching the patterns.
        token = cleanup_setup["token"]
        sid = cleanup_setup["site_id"]
        await test_client.delete(f"/api/v1/visitors/{sid}/cleanup-test", headers=_auth(token))
        resp = await test_client.delete(f"/api/v1/visitors/{sid}/cleanup-test", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json() == {"status": "clean", "visitors_deleted": 0, "events_deleted": 0}
