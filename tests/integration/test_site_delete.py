"""Integration tests for DELETE /api/v1/sites/{site_id} — the destructive
"delete site" cascade.

Covers:
- Owner can delete → 204, the site row AND its child rows (visitors, campaigns,
  segments, events, campaign_touchpoints, ...) are all gone.
- Non-owner / unknown site → 404 (owner-scoped; never leaks site existence), and
  the site + its data survive an unauthorized attempt.

Requires: PostgreSQL running locally (via docker-compose).
"""

import uuid as uuidlib
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select, text

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Delete Tester"},
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
async def site_with_data(test_client, test_db):
    """A site owned by a fresh user, seeded with one child row per site-scoped
    table plus a campaign_touchpoint grandchild (has no site_id of its own)."""
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import Visitor
    from apps.api.models.campaign import Campaign, CampaignTouchpoint
    from apps.api.models.segment import Segment, SegmentMember
    from apps.api.models.event import Event

    email = f"del-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"del_site_{uuidlib.uuid4().hex[:8]}"
    vid = f"v_{uuidlib.uuid4().hex[:8]}"
    now = datetime.utcnow()
    test_db.add(Site(site_id=site_id, user_id=user.id, name="Del Site", url="https://del.example.com"))
    test_db.add(
        Visitor(
            site_id=site_id,
            visitor_id=vid,
            intent_score=50,
            first_seen=now,
            last_seen=now,
        )
    )
    test_db.add(Event(site_id=site_id, visitor_id=vid, event_type="pageview", url="https://del.example.com/"))

    segment = Segment(site_id=site_id, name="Seg")
    test_db.add(segment)
    campaign = Campaign(site_id=site_id, name="Camp", plan={})
    test_db.add(campaign)
    await test_db.flush()  # populate segment.id / campaign.id

    test_db.add(SegmentMember(segment_id=segment.id, visitor_id=vid, site_id=site_id))
    test_db.add(
        CampaignTouchpoint(
            campaign_id=campaign.id,
            visitor_id=vid,
            channel="email",
            touchpoint_order=1,
            content={},
        )
    )
    await test_db.commit()
    return {"token": token, "site_id": site_id, "visitor_id": vid, "campaign_id": campaign.id}


async def _count(db, table: str, where: str, params: dict) -> int:
    r = await db.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"), params)
    return r.scalar() or 0


class TestDeleteSite:
    @pytest.mark.asyncio
    async def test_owner_delete_removes_site_and_children(
        self, test_client, test_db, site_with_data
    ):
        sid = site_with_data["site_id"]
        token = site_with_data["token"]
        cid = site_with_data["campaign_id"]

        # Sanity: data exists before delete.
        assert await _count(test_db, "sites", "site_id = :sid", {"sid": sid}) == 1
        assert await _count(test_db, "visitors", "site_id = :sid", {"sid": sid}) == 1
        assert await _count(test_db, "events", "site_id = :sid", {"sid": sid}) == 1
        assert await _count(test_db, "segments", "site_id = :sid", {"sid": sid}) == 1
        assert await _count(test_db, "campaigns", "site_id = :sid", {"sid": sid}) == 1
        assert (
            await _count(test_db, "campaign_touchpoints", "campaign_id = :cid", {"cid": cid})
            == 1
        )

        resp = await test_client.delete(f"/api/v1/sites/{sid}", headers=_auth(token))
        assert resp.status_code == 204, resp.text
        assert resp.content == b""

        # The endpoint committed on its own session; read through a fresh
        # transaction so we see the committed state.
        await test_db.rollback()

        assert await _count(test_db, "sites", "site_id = :sid", {"sid": sid}) == 0
        assert await _count(test_db, "visitors", "site_id = :sid", {"sid": sid}) == 0
        assert await _count(test_db, "events", "site_id = :sid", {"sid": sid}) == 0
        assert await _count(test_db, "segments", "site_id = :sid", {"sid": sid}) == 0
        assert await _count(test_db, "segment_members", "site_id = :sid", {"sid": sid}) == 0
        assert await _count(test_db, "campaigns", "site_id = :sid", {"sid": sid}) == 0
        assert (
            await _count(test_db, "campaign_touchpoints", "campaign_id = :cid", {"cid": cid})
            == 0
        )

    @pytest.mark.asyncio
    async def test_non_owner_gets_404_and_data_survives(
        self, test_client, test_db, site_with_data
    ):
        sid = site_with_data["site_id"]
        other_token = await _signup(test_client, f"other-{uuidlib.uuid4().hex[:8]}@test.com")

        resp = await test_client.delete(f"/api/v1/sites/{sid}", headers=_auth(other_token))
        assert resp.status_code == 404

        await test_db.rollback()
        # The rightful owner's site + data are untouched.
        assert await _count(test_db, "sites", "site_id = :sid", {"sid": sid}) == 1
        assert await _count(test_db, "visitors", "site_id = :sid", {"sid": sid}) == 1

    @pytest.mark.asyncio
    async def test_unknown_site_gets_404(self, test_client, site_with_data):
        resp = await test_client.delete(
            "/api/v1/sites/does_not_exist", headers=_auth(site_with_data["token"])
        )
        assert resp.status_code == 404
