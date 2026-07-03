"""Integration tests for LinkedIn outreach (campaign → phantommm sidecar).

Exercises the new POST/GET .../linkedin-outreach endpoints against a real DB:
guard paths (no touchpoint / not connected / unconfigured) plus the dry-run
happy path with a fake phantommm client (no network, no real LinkedIn).

Requires: PostgreSQL + Redis running locally. Uses test_client / test_db from
conftest.py which auto-create tables.
"""

import uuid as uuidlib

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str, password: str = "testpass123") -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "full_name": "LI Outreach Tester"},
    )
    if resp.status_code != 200:  # already exists → log in
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def li_token(test_client):
    return await _signup(test_client, "li-outreach@test.com")


async def _make_li_campaign(
    test_db,
    *,
    site_id: str,
    user_email: str,
    channel: str = "linkedin",
    with_enrichment: bool = True,
    with_member: bool = True,
) -> dict:
    """Site + segment + member (identified + LinkedIn-enriched) + a campaign
    whose plan carries a LinkedIn (or email) touchpoint."""
    from apps.api.models.campaign import Campaign
    from apps.api.models.enrichment import EnrichmentProfile
    from apps.api.models.segment import Segment, SegmentMember
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import IdentifiedVisitor

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
                name="LI Site",
                url="https://li.example.com",
            )
        )
        await test_db.flush()

    segment = Segment(site_id=site_id, name="LI Segment", visitor_count=1)
    test_db.add(segment)
    await test_db.flush()

    suffix = uuidlib.uuid4().hex[:6]
    vid = f"li-vid-{suffix}"
    if with_member:
        test_db.add_all(
            [
                SegmentMember(segment_id=segment.id, visitor_id=vid, site_id=site_id),
                IdentifiedVisitor(
                    visitor_id=vid,
                    site_id=site_id,
                    email=f"li-{suffix}@test.com",
                    full_name="Li Person",
                    resolution_provider="form_capture",
                ),
            ]
        )
        if with_enrichment:
            test_db.add(
                EnrichmentProfile(
                    visitor_id=vid,
                    site_id=site_id,
                    linkedin_url="https://www.linkedin.com/in/li-person",
                )
            )

    if channel == "linkedin":
        touchpoints = [
            {
                "channel": "linkedin",
                "order": 2,
                "connection_note": "Hi {{first_name}}, saw you at {{company_name}}.",
                "followup_message": "Thanks for connecting {{first_name}}!",
            }
        ]
    else:
        touchpoints = [{"channel": "email", "step": 1, "subject": "x", "body": "y"}]

    campaign = Campaign(
        site_id=site_id,
        segment_id=segment.id,
        name=f"LI Campaign {suffix}",
        campaign_type="social_reply" if channel == "linkedin" else "email",
        status="draft",
        plan={"touchpoints": touchpoints},
    )
    test_db.add(campaign)
    await test_db.commit()
    return {"site_id": site_id, "campaign_id": str(campaign.id), "visitor_id": vid}


async def _connect_linkedin(test_db, user_email: str, connection_id: str = "conn-abc"):
    """Give the user an active LinkedIn SocialAccount with an outreach id."""
    from apps.api.models.social_account import Platform, SocialAccount
    from apps.api.models.user import User

    user = (
        await test_db.execute(select(User).where(User.email == user_email))
    ).scalar_one()
    test_db.add(
        SocialAccount(
            user_id=user.id,
            platform=Platform.linkedin,
            platform_user_id="urn:li:person:test",
            username="Li Tester",
            access_token="tok",
            outreach_connection_id=connection_id,
            is_active=True,
        )
    )
    await test_db.commit()


def _url(setup: dict) -> str:
    return f"/api/v1/campaigns/{setup['site_id']}/{setup['campaign_id']}/linkedin-outreach"


class TestLinkedInOutreachGuards:
    @pytest.mark.asyncio
    async def test_email_campaign_has_no_linkedin_touchpoint_400(
        self, test_client, test_db, li_token
    ):
        setup = await _make_li_campaign(
            test_db, site_id="li_site_email", user_email="li-outreach@test.com",
            channel="email",
        )
        resp = await test_client.post(
            _url(setup), headers=_auth(li_token), json={"dry_run": True}
        )
        assert resp.status_code == 400, resp.text
        assert "LinkedIn touchpoint" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_not_connected_400(self, test_client, test_db, li_token):
        setup = await _make_li_campaign(
            test_db, site_id="li_site_noconn", user_email="li-outreach@test.com",
        )
        resp = await test_client.post(
            _url(setup), headers=_auth(li_token), json={"dry_run": True}
        )
        assert resp.status_code == 400, resp.text
        assert "Connect your LinkedIn session" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_connected_but_phantommm_unconfigured_503(
        self, test_client, test_db, li_token, monkeypatch
    ):
        # Ensure settings look unconfigured so PhantommmClient() raises.
        from apps.api.services import phantommm_client as pc

        monkeypatch.setattr(pc.settings, "phantommm_base_url", None, raising=False)
        monkeypatch.setattr(pc.settings, "phantommm_api_key", None, raising=False)

        setup = await _make_li_campaign(
            test_db, site_id="li_site_503", user_email="li-outreach@test.com",
        )
        await _connect_linkedin(test_db, "li-outreach@test.com")
        resp = await test_client.post(
            _url(setup), headers=_auth(li_token), json={"dry_run": True}
        )
        assert resp.status_code == 503, resp.text

    @pytest.mark.asyncio
    async def test_connected_but_no_enriched_linkedin_url_400(
        self, test_client, test_db, li_token, monkeypatch
    ):
        import apps.api.routers.campaigns as camp

        class _Fake:
            def __init__(self):
                pass

        monkeypatch.setattr(camp, "PhantommmClient", _Fake)
        setup = await _make_li_campaign(
            test_db, site_id="li_site_nourl", user_email="li-outreach@test.com",
            with_enrichment=False,
        )
        await _connect_linkedin(test_db, "li-outreach@test.com")
        resp = await test_client.post(
            _url(setup), headers=_auth(li_token), json={"dry_run": True}
        )
        assert resp.status_code == 400, resp.text
        assert "LinkedIn profile" in resp.json()["detail"]


class TestLinkedInOutreachHappyPath:
    @pytest.mark.asyncio
    async def test_dry_run_returns_job_and_converts_note(
        self, test_client, test_db, li_token, monkeypatch
    ):
        import apps.api.routers.campaigns as camp

        calls: dict = {}

        class _FakeClient:
            def __init__(self):
                pass

            async def start_outreach(self, **kw):
                calls["start"] = kw
                return {"jobId": "job-123", "dryRun": kw["dry_run"]}

            async def get_outreach_job(self, job_id):
                calls["job"] = job_id
                return {
                    "status": "done",
                    "done": 1,
                    "total": 1,
                    "sent": 0,
                    "results": [{"url": "x", "status": "would_connect"}],
                }

        monkeypatch.setattr(camp, "PhantommmClient", _FakeClient)

        setup = await _make_li_campaign(
            test_db, site_id="li_site_ok", user_email="li-outreach@test.com",
        )
        await _connect_linkedin(test_db, "li-outreach@test.com")

        resp = await test_client.post(
            _url(setup), headers=_auth(li_token), json={"dry_run": True, "limit": 20}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["job_id"] == "job-123"
        assert body["dry_run"] is True
        assert body["total_targets"] == 1
        assert body["audience_skipped_no_linkedin"] == 0

        # Beam {{first_name}} → phantommm #firstName#; unsupported {{company_name}}
        # never leaks a raw mustache token.
        note = calls["start"]["note"]
        assert "#firstName#" in note
        assert "{{" not in note and "}}" not in note
        assert calls["start"]["connection_id"] == "conn-abc"
        assert calls["start"]["dry_run"] is True

        # Job status endpoint proxies phantommm.
        job_resp = await test_client.get(
            f"{_url(setup)}/job-123", headers=_auth(li_token)
        )
        assert job_resp.status_code == 200, job_resp.text
        jb = job_resp.json()
        assert jb["status"] == "done"
        assert jb["total"] == 1
        assert calls["job"] == "job-123"

    @pytest.mark.asyncio
    async def test_requires_auth(self, test_client, test_db, li_token):
        setup = await _make_li_campaign(
            test_db, site_id="li_site_auth", user_email="li-outreach@test.com",
        )
        resp = await test_client.post(_url(setup), json={"dry_run": True})
        assert resp.status_code in (401, 403), resp.text
