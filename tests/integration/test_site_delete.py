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


class TestSiteIdReclaim:
    """Tombstone-based site_id reuse (AC1) and its tenant isolation (AC5/AC8).

    Requires PostgreSQL + Redis (docker compose -f infra/docker-compose.yml
    up -d postgres redis), same as the rest of this module.
    """

    @staticmethod
    async def _create(test_client, token: str, url: str, name: str = "Reclaim Site"):
        return await test_client.post(
            "/api/v1/sites/",
            json={"name": name, "url": url},
            headers=_auth(token),
        )

    @pytest.mark.asyncio
    async def test_delete_then_recreate_same_domain_reuses_site_id(
        self, test_client, test_db
    ):
        token = await _signup(test_client, f"reuse-{uuidlib.uuid4().hex[:8]}@test.com")
        url = f"https://reuse-{uuidlib.uuid4().hex[:8]}.example.com"

        created = await self._create(test_client, token, url)
        assert created.status_code == 200, created.text
        original_id = created.json()["site_id"]

        # Pixel works before the delete.
        assert (await self._ingest(test_client, original_id)) == 204

        resp = await test_client.delete(
            f"/api/v1/sites/{original_id}", headers=_auth(token)
        )
        assert resp.status_code == 204

        recreated = await self._create(test_client, token, url, name="Re-added")
        assert recreated.status_code == 200, recreated.text
        assert recreated.json()["site_id"] == original_id

        # The ALREADY-INSTALLED snippet (original id) works again, unedited.
        assert (await self._ingest(test_client, original_id)) == 204

        # The tombstone was consumed.
        await test_db.rollback()
        assert (
            await _count(
                test_db,
                "site_tombstones",
                "site_id = :sid",
                {"sid": original_id},
            )
            == 0
        )

    @staticmethod
    async def _ingest(test_client, site_id: str) -> int:
        import json as _json

        payload = {
            "site_id": site_id,
            "visitor_id": f"v_{uuidlib.uuid4().hex[:8]}",
            "events": [
                {
                    "type": "pageview",
                    "event_id": uuidlib.uuid4().hex,
                    "url": "https://example.com/",
                    "ts": "2026-05-27T00:00:00",
                }
            ],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=_json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )
        return resp.status_code

    @pytest.mark.asyncio
    async def test_recreate_outside_reclaim_window_gets_fresh_id(
        self, test_client, test_db
    ):
        from datetime import timedelta, timezone

        from apps.api.config import settings

        token = await _signup(test_client, f"stale-{uuidlib.uuid4().hex[:8]}@test.com")
        url = f"https://stale-{uuidlib.uuid4().hex[:8]}.example.com"

        created = await self._create(test_client, token, url)
        original_id = created.json()["site_id"]
        assert (
            await test_client.delete(
                f"/api/v1/sites/{original_id}", headers=_auth(token)
            )
        ).status_code == 204

        # Backdate the tombstone past the reclaim window.
        await test_db.rollback()
        stale = datetime.now(timezone.utc) - timedelta(
            days=settings.site_id_reclaim_window_days + 1
        )
        await test_db.execute(
            text(
                "UPDATE site_tombstones SET deleted_at = :ts WHERE site_id = :sid"
            ),
            {"ts": stale, "sid": original_id},
        )
        await test_db.commit()

        recreated = await self._create(test_client, token, url)
        assert recreated.status_code == 200, recreated.text
        assert recreated.json()["site_id"] != original_id

    @pytest.mark.asyncio
    async def test_foreign_tombstone_not_reused(self, test_client, test_db):
        """AC5/AC8 — user B never adopts user A's deleted id."""
        token_a = await _signup(test_client, f"a-{uuidlib.uuid4().hex[:8]}@test.com")
        token_b = await _signup(test_client, f"b-{uuidlib.uuid4().hex[:8]}@test.com")
        url = f"https://shared-{uuidlib.uuid4().hex[:8]}.example.com"

        created_a = await self._create(test_client, token_a, url)
        id_a = created_a.json()["site_id"]
        assert (
            await test_client.delete(f"/api/v1/sites/{id_a}", headers=_auth(token_a))
        ).status_code == 204

        created_b = await self._create(test_client, token_b, url)
        assert created_b.status_code == 200, created_b.text
        assert created_b.json()["site_id"] != id_a

        # A's tombstone is untouched (not consumed by B's create).
        await test_db.rollback()
        assert (
            await _count(
                test_db, "site_tombstones", "site_id = :sid", {"sid": id_a}
            )
            == 1
        )

        # And B still cannot address A's old id.
        assert (
            await test_client.delete(f"/api/v1/sites/{id_a}", headers=_auth(token_b))
        ).status_code == 404
