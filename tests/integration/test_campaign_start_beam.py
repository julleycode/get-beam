"""Integration tests for the one-click campaign launch ("Start beam"),
admin test-send, open/click tracking, and the campaign stats endpoint.

Requires: PostgreSQL + Redis running locally (via docker-compose).
Uses test_client and test_db from conftest.py which auto-create tables.
"""

import uuid as uuidlib

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration

_BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"


async def _signup(test_client, email: str, password: str = "testpass123") -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "full_name": "Start Beam Tester"},
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
    return await _signup(test_client, "startbeam-user@test.com")


async def _make_campaign(
    test_db, *, site_id: str, user_email: str, campaign_type: str = "email",
    status: str = "draft", with_member: bool = True,
) -> dict:
    """Site + segment + one emailable member + campaign in the given status."""
    from apps.api.models.campaign import Campaign
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
                name="Start Beam Site",
                url="https://startbeam.example.com",
            )
        )
        await test_db.flush()

    segment = Segment(site_id=site_id, name="Beamers", visitor_count=1)
    test_db.add(segment)
    await test_db.flush()

    suffix = uuidlib.uuid4().hex[:6]
    vid = f"beam-vid-{suffix}"
    if with_member:
        test_db.add_all(
            [
                SegmentMember(segment_id=segment.id, visitor_id=vid, site_id=site_id),
                IdentifiedVisitor(
                    visitor_id=vid,
                    site_id=site_id,
                    email=f"beam-{suffix}@test.com",
                    full_name="Beam Person",
                    resolution_provider="form_capture",
                ),
            ]
        )

    campaign = Campaign(
        site_id=site_id,
        segment_id=segment.id,
        name=f"Start Beam {campaign_type} {suffix}",
        campaign_type=campaign_type,
        status=status,
        plan={
            "touchpoints": [
                {
                    "channel": "email",
                    "step": 1,
                    "subject": "Hi {{first_name}}",
                    "body": "Hello {{first_name}}, see https://startbeam.example.com/pricing today.",
                }
            ]
            if campaign_type == "email"
            else [{"channel": "social_reply", "step": 1, "message": "hey"}]
        },
    )
    test_db.add(campaign)
    await test_db.commit()
    return {"site_id": site_id, "campaign_id": str(campaign.id), "visitor_id": vid}


def _mock_sender(monkeypatch, sent: list):
    async def fake_send(self, to_email, subject, body_html, **kwargs):
        sent.append({"to": to_email, "subject": subject, "body": body_html})
        return {"id": "fake", "status": 202}

    from apps.api.services.email_sender import EmailSender

    monkeypatch.setattr(EmailSender, "send", fake_send)


class TestStartBeam:
    @pytest.mark.asyncio
    async def test_start_draft_email_campaign_approves_activates_sends(
        self, test_client, test_db, user_token, monkeypatch
    ):
        setup = await _make_campaign(
            test_db, site_id="startbeam_site_a", user_email="startbeam-user@test.com"
        )
        sent: list = []
        _mock_sender(monkeypatch, sent)

        url = f"/api/v1/campaigns/{setup['site_id']}/{setup['campaign_id']}/start"
        resp = await test_client.post(url, headers=_auth(user_token))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Full unthrottled send auto-completes (same rule as legacy /send)
        assert body["status"] == "completed"
        assert body["summary"]["sent"] == 1
        assert len(sent) == 1

        from apps.api.models.campaign import Campaign, CampaignTouchpoint

        campaign = (
            await test_db.execute(
                select(Campaign).where(Campaign.id == setup["campaign_id"])
            )
        ).scalar_one()
        assert campaign.approved_at is not None
        assert campaign.started_at is not None

        tp = (
            await test_db.execute(
                select(CampaignTouchpoint).where(
                    CampaignTouchpoint.campaign_id == campaign.id
                )
            )
        ).scalar_one()
        assert tp.status == "sent"
        assert tp.sent_at is not None
        # Email body carries the open pixel + the _tp click param
        assert f"/o/{tp.id}" in sent[0]["body"]
        assert f"_tp={tp.id}" in sent[0]["body"]

    @pytest.mark.asyncio
    async def test_start_social_campaign_activates_without_sending(
        self, test_client, test_db, user_token, monkeypatch
    ):
        setup = await _make_campaign(
            test_db,
            site_id="startbeam_site_b",
            user_email="startbeam-user@test.com",
            campaign_type="social_reply",
        )
        sent: list = []
        _mock_sender(monkeypatch, sent)

        url = f"/api/v1/campaigns/{setup['site_id']}/{setup['campaign_id']}/start"
        resp = await test_client.post(url, headers=_auth(user_token))
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "active"
        assert resp.json()["summary"]["sent"] == 0
        assert sent == []

    @pytest.mark.asyncio
    async def test_start_completed_campaign_is_409(
        self, test_client, test_db, user_token
    ):
        setup = await _make_campaign(
            test_db,
            site_id="startbeam_site_c",
            user_email="startbeam-user@test.com",
            status="completed",
        )
        url = f"/api/v1/campaigns/{setup['site_id']}/{setup['campaign_id']}/start"
        resp = await test_client.post(url, headers=_auth(user_token))
        assert resp.status_code == 409


class TestTestSend:
    @pytest.mark.asyncio
    async def test_test_send_delivers_prefixed_preview_without_touching_campaign(
        self, test_client, test_db, user_token, monkeypatch
    ):
        setup = await _make_campaign(
            test_db, site_id="startbeam_site_d", user_email="startbeam-user@test.com"
        )
        sent: list = []
        _mock_sender(monkeypatch, sent)

        url = f"/api/v1/campaigns/{setup['site_id']}/{setup['campaign_id']}/test-send"
        resp = await test_client.post(
            url, headers=_auth(user_token), json={"email": "admin@test.com"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["sent"] is True
        assert len(sent) == 1
        assert sent[0]["to"] == "admin@test.com"
        assert sent[0]["subject"].startswith("[TEST] ")
        # Sample personalization, not a real recipient
        assert "Alex" in sent[0]["subject"] or "Alex" in sent[0]["body"]

        from apps.api.models.campaign import Campaign, CampaignTouchpoint

        campaign = (
            await test_db.execute(
                select(Campaign).where(Campaign.id == setup["campaign_id"])
            )
        ).scalar_one()
        assert campaign.status == "draft"  # untouched
        tp_count = (
            await test_db.execute(
                select(CampaignTouchpoint).where(
                    CampaignTouchpoint.campaign_id == campaign.id
                )
            )
        ).scalars().all()
        assert tp_count == []  # no touchpoint rows for test sends

    @pytest.mark.asyncio
    async def test_test_send_rejects_invalid_email(
        self, test_client, test_db, user_token
    ):
        setup = await _make_campaign(
            test_db, site_id="startbeam_site_e", user_email="startbeam-user@test.com"
        )
        url = f"/api/v1/campaigns/{setup['site_id']}/{setup['campaign_id']}/test-send"
        resp = await test_client.post(
            url, headers=_auth(user_token), json={"email": "not-an-email"}
        )
        assert resp.status_code == 422


class TestOpenClickTrackingAndStats:
    @pytest.mark.asyncio
    async def test_open_pixel_click_event_and_stats(
        self, test_client, test_db, user_token, monkeypatch
    ):
        import json

        setup = await _make_campaign(
            test_db, site_id="startbeam_site_f", user_email="startbeam-user@test.com"
        )
        sent: list = []
        _mock_sender(monkeypatch, sent)

        start_url = f"/api/v1/campaigns/{setup['site_id']}/{setup['campaign_id']}/start"
        resp = await test_client.post(start_url, headers=_auth(user_token))
        assert resp.status_code == 200, resp.text

        from apps.api.models.campaign import CampaignTouchpoint

        tp = (
            await test_db.execute(
                select(CampaignTouchpoint).where(
                    CampaignTouchpoint.campaign_id == setup["campaign_id"]
                )
            )
        ).scalar_one()
        assert tp.opened_at is None and tp.clicked_at is None

        # Stats before any engagement
        stats_url = f"/api/v1/campaigns/{setup['site_id']}/{setup['campaign_id']}/stats"
        stats = (await test_client.get(stats_url, headers=_auth(user_token))).json()
        assert stats["sent"] == 1
        assert stats["opened"] == 0 and stats["clicked"] == 0
        assert stats["returned_visitors"] == []

        # 1) Open: mail client loads the pixel
        gif = await test_client.get(f"/o/{tp.id}")
        assert gif.status_code == 200
        assert gif.headers["content-type"] == "image/gif"
        # Bogus id still returns the GIF (no existence oracle)
        bogus = await test_client.get(f"/o/{uuidlib.uuid4()}")
        assert bogus.status_code == 200
        not_uuid = await test_client.get("/o/definitely-not-a-uuid")
        assert not_uuid.status_code == 200

        # 2) Click + return visit: recipient lands on the site with _tp in the
        # URL and the pixel reports a pageview AFTER sent_at.
        payload = {
            "site_id": setup["site_id"],
            "visitor_id": setup["visitor_id"],
            "events": [
                {
                    "type": "pageview",
                    "url": f"https://startbeam.example.com/pricing?_bid=x&_tp={tp.id}",
                    "page_path": "/pricing",
                    "user_agent": _BROWSER_UA,
                    "ts": "2030-01-01T00:00:00",
                }
            ],
        }
        ingest = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        )
        assert ingest.status_code == 204

        stats = (await test_client.get(stats_url, headers=_auth(user_token))).json()
        assert stats["opened"] == 1  # pixel load stamped opened_at
        assert stats["clicked"] == 1  # _tp on the landing URL stamped clicked_at
        assert stats["open_rate"] == 1.0 and stats["click_rate"] == 1.0
        returned = stats["returned_visitors"]
        assert len(returned) == 1
        assert returned[0]["visitor_id"] == setup["visitor_id"]
        assert returned[0]["full_name"] == "Beam Person"
        assert returned[0]["pageviews_after"] == 1
        assert returned[0]["clicked_at"] is not None

    @pytest.mark.asyncio
    async def test_foreign_site_tp_is_not_stamped(
        self, test_client, test_db, user_token, monkeypatch
    ):
        """A _tp belonging to site A must not be stampable via site B's events."""
        import json

        setup_a = await _make_campaign(
            test_db, site_id="startbeam_site_g", user_email="startbeam-user@test.com"
        )
        setup_b = await _make_campaign(
            test_db, site_id="startbeam_site_h", user_email="startbeam-user@test.com"
        )
        sent: list = []
        _mock_sender(monkeypatch, sent)

        start_url = (
            f"/api/v1/campaigns/{setup_a['site_id']}/{setup_a['campaign_id']}/start"
        )
        assert (
            await test_client.post(start_url, headers=_auth(user_token))
        ).status_code == 200

        from apps.api.models.campaign import CampaignTouchpoint

        tp = (
            await test_db.execute(
                select(CampaignTouchpoint).where(
                    CampaignTouchpoint.campaign_id == setup_a["campaign_id"]
                )
            )
        ).scalar_one()

        # Site B's pixel reports a URL carrying site A's _tp
        payload = {
            "site_id": setup_b["site_id"],
            "visitor_id": "some-other-visitor",
            "events": [
                {
                    "type": "pageview",
                    "url": f"https://other.example.com/?_tp={tp.id}",
                    "page_path": "/",
                    "user_agent": _BROWSER_UA,
                    "ts": "2030-01-01T00:00:00",
                }
            ],
        }
        ingest = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        )
        assert ingest.status_code == 204

        await test_db.refresh(tp)
        assert tp.clicked_at is None and tp.opened_at is None
