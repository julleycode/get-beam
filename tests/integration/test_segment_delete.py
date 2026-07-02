"""Tests for DELETE /api/v1/segments/{site_id}/{segment_id}.

Deleting a segment must remove its member rows (FK cascade) but keep any
campaigns that were generated from it, unlinking them (segment_id -> NULL)
instead of failing on the FK.

Requires: PostgreSQL + Redis running locally (via docker-compose).
"""

import uuid as uuidlib
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str, password: str = "testpass123") -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "full_name": "Segment Delete Tester"},
    )
    if resp.status_code != 200:  # already exists from a previous run (400)
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def user_token(test_client):
    return await _signup(test_client, "segment-delete-user@test.com")


async def _seed_segment(test_db, *, site_id: str, user_email: str, with_campaign: bool):
    from apps.api.models.campaign import Campaign
    from apps.api.models.segment import Segment, SegmentMember
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import Visitor

    user = (
        await test_db.execute(select(User).where(User.email == user_email))
    ).scalar_one()

    if not (
        await test_db.execute(select(Site).where(Site.site_id == site_id))
    ).scalar_one_or_none():
        test_db.add(
            Site(
                site_id=site_id,
                user_id=user.id,
                name="Segment Delete Site",
                url="https://segmentdelete.example.com",
            )
        )
        await test_db.flush()

    segment = Segment(site_id=site_id, name="Doomed segment", visitor_count=1)
    test_db.add(segment)
    await test_db.flush()

    vid = f"sd-vid-{uuidlib.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    test_db.add_all(
        [
            SegmentMember(segment_id=segment.id, visitor_id=vid, site_id=site_id),
            Visitor(
                site_id=site_id,
                visitor_id=vid,
                first_seen=now,
                last_seen=now,
            ),
        ]
    )

    campaign = None
    if with_campaign:
        campaign = Campaign(
            site_id=site_id,
            segment_id=segment.id,
            name="Campaign from doomed segment",
            status="draft",
            plan={"touchpoints": []},
        )
        test_db.add(campaign)

    await test_db.commit()
    return segment, campaign


@pytest.mark.asyncio
async def test_delete_segment_cascades_members_and_unlinks_campaign(
    test_client, test_db, user_token
):
    from apps.api.models.campaign import Campaign
    from apps.api.models.segment import Segment, SegmentMember

    site_id = f"site-sd-{uuidlib.uuid4().hex[:6]}"
    segment, campaign = await _seed_segment(
        test_db,
        site_id=site_id,
        user_email="segment-delete-user@test.com",
        with_campaign=True,
    )
    # Capture ids as plain values: touching ORM attributes after expire_all()
    # triggers a sync refresh -> MissingGreenlet under asyncpg.
    segment_id, campaign_id = segment.id, campaign.id

    resp = await test_client.delete(
        f"/api/v1/segments/{site_id}/{segment_id}", headers=_auth(user_token)
    )
    assert resp.status_code == 204, resp.text

    test_db.expire_all()
    assert (
        await test_db.execute(select(Segment).where(Segment.id == segment_id))
    ).scalar_one_or_none() is None
    assert (
        await test_db.execute(
            select(SegmentMember).where(SegmentMember.segment_id == segment_id)
        )
    ).scalar_one_or_none() is None

    # Campaign survives, unlinked.
    surviving = (
        await test_db.execute(select(Campaign).where(Campaign.id == campaign_id))
    ).scalar_one()
    assert surviving.segment_id is None


@pytest.mark.asyncio
async def test_delete_segment_unknown_id_404(test_client, test_db, user_token):
    site_id = f"site-sd-{uuidlib.uuid4().hex[:6]}"
    await _seed_segment(
        test_db,
        site_id=site_id,
        user_email="segment-delete-user@test.com",
        with_campaign=False,
    )

    resp = await test_client.delete(
        f"/api/v1/segments/{site_id}/{uuidlib.uuid4()}", headers=_auth(user_token)
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_segment_other_users_site_blocked(test_client, test_db, user_token):
    """A different user must not be able to delete segments on a site they
    don't own (verify_site_access should reject before any delete happens)."""
    from apps.api.models.segment import Segment

    site_id = f"site-sd-{uuidlib.uuid4().hex[:6]}"
    segment, _ = await _seed_segment(
        test_db,
        site_id=site_id,
        user_email="segment-delete-user@test.com",
        with_campaign=False,
    )
    segment_id = segment.id

    intruder_token = await _signup(test_client, "segment-delete-intruder@test.com")
    resp = await test_client.delete(
        f"/api/v1/segments/{site_id}/{segment_id}", headers=_auth(intruder_token)
    )
    assert resp.status_code in (403, 404)

    test_db.expire_all()
    assert (
        await test_db.execute(select(Segment).where(Segment.id == segment_id))
    ).scalar_one_or_none() is not None
