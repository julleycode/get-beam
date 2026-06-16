"""Phase 03 (GDPR/CCPA) integration: DSAR data export endpoint.

Against the test DB (requires local PostgreSQL via docker-compose):
- GET /{site_id}/{visitor_id}/data/export gathers data from every table.
- Site-ownership is enforced (another tenant gets 404).
- A visitor with no data returns a well-formed payload with null sections.
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


@pytest_asyncio.fixture
async def dsar_setup(test_client, test_db):
    """A site owned by a user, with one visitor populated across every table."""
    from apps.api.models.enrichment import EnrichmentProfile
    from apps.api.models.event import Event
    from apps.api.models.segment import Segment, SegmentMember
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import IdentifiedVisitor, ResolutionLog, Visitor
    from apps.api.models.visitor_email import VisitorEmail

    email = f"dsar-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"dsar_site_{uuidlib.uuid4().hex[:8]}"
    vid = f"v_{uuidlib.uuid4().hex[:8]}"
    now = datetime.utcnow()

    test_db.add(Site(site_id=site_id, user_id=user.id, name="DSAR", url="https://d.example.com"))
    test_db.add(Visitor(site_id=site_id, visitor_id=vid, first_seen=now, last_seen=now, intent_score=50.0))
    test_db.add(IdentifiedVisitor(site_id=site_id, visitor_id=vid, email="lead@acme.com", full_name="Lead X"))
    test_db.add(EnrichmentProfile(site_id=site_id, visitor_id=vid, twitter_handle="leadx", company_name="Acme"))
    test_db.add(VisitorEmail(site_id=site_id, visitor_id=vid, email="lead@acme.com", source="form"))
    test_db.add(Event(site_id=site_id, visitor_id=vid, event_type="pageview", url="https://d.example.com/pricing", created_at=now))
    test_db.add(ResolutionLog(site_id=site_id, visitor_id=vid, provider="pdl", success=True, cost_usd=0.05))
    seg = Segment(site_id=site_id, name="Seg")
    test_db.add(seg)
    await test_db.flush()
    test_db.add(SegmentMember(segment_id=seg.id, site_id=site_id, visitor_id=vid))
    await test_db.commit()

    return {"token": token, "site_id": site_id, "visitor_id": vid}


class TestDsarExport:
    @pytest.mark.asyncio
    async def test_export_gathers_all_sections(self, test_client, dsar_setup):
        sid, vid, token = dsar_setup["site_id"], dsar_setup["visitor_id"], dsar_setup["token"]

        resp = await test_client.get(
            f"/api/v1/visitors/{sid}/{vid}/data/export", headers=_auth(token)
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["visitor"] is not None
        assert data["identified"]["email"] == "lead@acme.com"
        assert data["enrichment"]["twitter_handle"] == "leadx"
        assert len(data["emails"]) == 1
        assert len(data["events"]) == 1
        assert len(data["resolution_logs"]) == 1
        assert len(data["segments"]) == 1
        assert isinstance(data["social_posts"], list)
        assert data["events_truncated"] is False
        # Attachment header so the dashboard can offer a file download.
        assert "attachment" in resp.headers.get("content-disposition", "")

    @pytest.mark.asyncio
    async def test_other_tenant_cannot_export(self, test_client, dsar_setup):
        sid, vid = dsar_setup["site_id"], dsar_setup["visitor_id"]
        other = await _signup(test_client, f"other-{uuidlib.uuid4().hex[:8]}@test.com")
        resp = await test_client.get(
            f"/api/v1/visitors/{sid}/{vid}/data/export", headers=_auth(other)
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_unknown_visitor_returns_empty_sections(self, test_client, dsar_setup):
        sid, token = dsar_setup["site_id"], dsar_setup["token"]
        resp = await test_client.get(
            f"/api/v1/visitors/{sid}/nope-{uuidlib.uuid4().hex[:6]}/data/export",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["visitor"] is None
        assert data["identified"] is None
        assert data["emails"] == []
        assert data["events"] == []
