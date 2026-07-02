"""Regression test for POST /api/v1/campaigns/{site_id}/create/{segment_id}.

The endpoint used to read identity fields (email, full_name) and enrichment
fields (job_title, linkedin_url, ...) directly off Visitor, which has none of
those columns -> AttributeError -> unhandled 500 -> CORS stripped -> the
dashboard showed "Network error: unable to reach API (Failed to fetch)".
It now builds profiles via build_visitor_profiles (Visitor + IdentifiedVisitor
+ EnrichmentProfile), same as the auto-segmentation path.

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
        json={"email": email, "password": password, "full_name": "Create Campaign Tester"},
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
    return await _signup(test_client, "create-campaign-user@test.com")


async def _seed_segment_with_enriched_member(test_db, *, site_id: str, user_email: str):
    """Site + segment + one member with Visitor, IdentifiedVisitor and
    EnrichmentProfile rows — the shape that used to crash the endpoint."""
    from apps.api.models.enrichment import EnrichmentProfile
    from apps.api.models.segment import Segment, SegmentMember
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import IdentifiedVisitor, Visitor

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
                name="Create Campaign Site",
                url="https://createcampaign.example.com",
            )
        )
        await test_db.flush()

    segment = Segment(site_id=site_id, name="Enriched folks", visitor_count=1)
    test_db.add(segment)
    await test_db.flush()

    vid = f"cc-vid-{uuidlib.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    test_db.add_all(
        [
            SegmentMember(segment_id=segment.id, visitor_id=vid, site_id=site_id),
            Visitor(
                site_id=site_id,
                visitor_id=vid,
                first_seen=now,
                last_seen=now,
                intent_score=80.0,
                identity_status="identified",
                enrichment_status="enriched",
            ),
            IdentifiedVisitor(
                visitor_id=vid,
                site_id=site_id,
                email="jane@example.com",
                full_name="Jane Doe",
                resolution_provider="form_capture",
            ),
            EnrichmentProfile(
                visitor_id=vid,
                site_id=site_id,
                job_title="Head of Growth",
                company_name="ExampleCo",
                linkedin_url="https://linkedin.com/in/janedoe",
            ),
        ]
    )
    await test_db.commit()
    return segment, vid


@pytest.mark.asyncio
async def test_create_campaign_from_segment_builds_real_profiles(
    test_client, test_db, user_token, monkeypatch
):
    site_id = f"site-cc-{uuidlib.uuid4().hex[:6]}"
    segment, vid = await _seed_segment_with_enriched_member(
        test_db, site_id=site_id, user_email="create-campaign-user@test.com"
    )

    captured: dict = {}

    async def fake_plan_campaign(db, segment, visitor_profiles, connected_accounts=None):
        from apps.api.models.campaign import Campaign

        captured["profiles"] = visitor_profiles
        campaign = Campaign(
            site_id=segment.site_id,
            segment_id=segment.id,
            name="Fake planned campaign",
            status="draft",
            plan={"touchpoints": []},
        )
        db.add(campaign)
        await db.commit()
        return campaign

    # Patch where it's used (imported into the router module's namespace).
    monkeypatch.setattr(
        "apps.api.routers.campaigns.plan_campaign", fake_plan_campaign
    )

    resp = await test_client.post(
        f"/api/v1/campaigns/{site_id}/create/{segment.id}",
        headers=_auth(user_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "draft"
    assert body["segment_id"] == str(segment.id)

    # The regression: profiles must carry identity + enrichment fields pulled
    # from IdentifiedVisitor/EnrichmentProfile (Visitor has no such columns).
    profiles = captured["profiles"]
    assert len(profiles) == 1
    profile = profiles[0]
    assert profile["visitor_id"] == vid
    assert profile["email"] == "jane@example.com"
    assert profile["full_name"] == "Jane Doe"
    assert profile["job_title"] == "Head of Growth"
    assert profile["company_name"] == "ExampleCo"
    assert profile["linkedin_url"] == "https://linkedin.com/in/janedoe"


@pytest.mark.asyncio
async def test_create_campaign_ignores_other_sites_visitors(
    test_client, test_db, user_token, monkeypatch
):
    """Visitor rows from another site with the same visitor_id must not leak in."""
    from apps.api.models.visitor import Visitor

    site_id = f"site-cc-{uuidlib.uuid4().hex[:6]}"
    segment, vid = await _seed_segment_with_enriched_member(
        test_db, site_id=site_id, user_email="create-campaign-user@test.com"
    )

    # Same visitor_id on a DIFFERENT site — must be filtered out.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    test_db.add(
        Visitor(
            site_id=f"other-{uuidlib.uuid4().hex[:6]}",
            visitor_id=vid,
            first_seen=now,
            last_seen=now,
        )
    )
    await test_db.commit()

    captured: dict = {}

    async def fake_plan_campaign(db, segment, visitor_profiles, connected_accounts=None):
        from apps.api.models.campaign import Campaign

        captured["profiles"] = visitor_profiles
        campaign = Campaign(
            site_id=segment.site_id,
            segment_id=segment.id,
            name="Fake planned campaign",
            status="draft",
            plan={"touchpoints": []},
        )
        db.add(campaign)
        await db.commit()
        return campaign

    monkeypatch.setattr(
        "apps.api.routers.campaigns.plan_campaign", fake_plan_campaign
    )

    resp = await test_client.post(
        f"/api/v1/campaigns/{site_id}/create/{segment.id}",
        headers=_auth(user_token),
    )
    assert resp.status_code == 200, resp.text
    assert len(captured["profiles"]) == 1
