"""Integration tests for previously-untested critical paths.

Covers the test-gap items from the 2026-06-10 review backlog:
- Lemon Squeezy webhook (HMAC signature, plan sync, idempotent redelivery)
- Unsubscribe flow (signed token → do_not_email, case-insensitive)
- Campaign email send guardrails (suppression skip + per-recipient idempotency)
- Feature-requests admin gating (plain users get 403)
- Invite consume (one-use semantics)

Requires: PostgreSQL + Redis running locally (via docker-compose).
Uses test_client and test_db from conftest.py which auto-create tables.
"""

import uuid as uuidlib

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str, password: str = "testpass123") -> str:
    """Create a legacy-auth user and return a Bearer token."""
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "full_name": "Backlog Tester"},
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
    return await _signup(test_client, "backlog-user@test.com")


@pytest_asyncio.fixture
async def admin_token(test_client, test_db):
    from apps.api.models.user import User

    token = await _signup(test_client, "backlog-admin@test.com")
    result = await test_db.execute(
        select(User).where(User.email == "backlog-admin@test.com")
    )
    user = result.scalar_one()
    user.is_admin = True
    await test_db.commit()
    return token


class TestLemonSqueezyWebhook:
    @pytest.mark.asyncio
    async def test_subscription_created_sets_plan_and_is_idempotent(
        self, test_client, test_db, monkeypatch
    ):
        import hashlib
        import hmac
        import json

        from apps.api.config import settings
        from apps.api.models.user import User

        await _signup(test_client, "ls-billing@test.com")
        result = await test_db.execute(
            select(User).where(User.email == "ls-billing@test.com")
        )
        user = result.scalar_one()

        secret = "ls_test_secret"
        monkeypatch.setattr(settings, "lemonsqueezy_webhook_secret", secret)
        monkeypatch.setattr(settings, "ls_variant_pro_monthly", "12345")

        body = json.dumps(
            {
                "meta": {
                    "event_name": "subscription_created",
                    "custom_data": {"user_id": str(user.id)},
                },
                "data": {
                    "id": "sub_999",
                    "attributes": {
                        "status": "active",
                        "variant_id": 12345,
                        "customer_id": 555,
                        "renews_at": "2099-01-01T00:00:00.000000Z",
                    },
                },
            }
        ).encode()
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers = {"X-Event-Name": "subscription_created"}

        # Wrong signature is rejected.
        bad = await test_client.post(
            "/api/v1/billing/webhook",
            content=body,
            headers={**headers, "X-Signature": "deadbeef"},
        )
        assert bad.status_code == 400

        # Valid signature succeeds; redelivery is idempotent (same end state).
        for _ in range(2):
            ok = await test_client.post(
                "/api/v1/billing/webhook",
                content=body,
                headers={**headers, "X-Signature": sig},
            )
            assert ok.status_code == 200
            assert ok.json() == {"received": True}

        await test_db.refresh(user)
        assert user.plan == "pro"
        assert user.subscription_status == "active"
        assert user.stripe_subscription_id == "sub_999"
        assert user.stripe_customer_id == "555"


class TestUnsubscribeFlow:
    @pytest.mark.asyncio
    async def test_signed_token_sets_do_not_email_case_insensitive(
        self, test_client, test_db
    ):
        from apps.api.models.visitor import IdentifiedVisitor
        from apps.api.services.link_decorator import generate_unsubscribe_token

        # Stored mixed-case (as providers used to return); token is lowercase.
        email_mixed = "Unsub.Target@Test.COM"
        visitor_id = f"unsub-{uuidlib.uuid4().hex[:8]}"
        test_db.add(
            IdentifiedVisitor(
                visitor_id=visitor_id,
                site_id="backlog_site_unsub",
                email=email_mixed,
                resolution_provider="test",
            )
        )
        await test_db.commit()

        token = generate_unsubscribe_token(email_mixed.lower())
        resp = await test_client.get(f"/unsubscribe?t={token}")
        assert resp.status_code == 200

        row = await test_db.execute(
            select(IdentifiedVisitor).where(
                IdentifiedVisitor.visitor_id == visitor_id
            )
        )
        iv = row.scalar_one()
        await test_db.refresh(iv)
        assert iv.do_not_email is True

    @pytest.mark.asyncio
    async def test_forged_token_is_noop_200(self, test_client):
        resp = await test_client.get("/unsubscribe?t=forged-garbage")
        assert resp.status_code == 200  # generic page, no enumeration


class TestCampaignSendGuardrails:
    @pytest_asyncio.fixture
    async def campaign_setup(self, test_db, user_token):
        from apps.api.models.campaign import Campaign, CampaignTouchpoint
        from apps.api.models.segment import Segment, SegmentMember
        from apps.api.models.site import Site
        from apps.api.models.user import User
        from apps.api.models.visitor import IdentifiedVisitor

        result = await test_db.execute(
            select(User).where(User.email == "backlog-user@test.com")
        )
        user = result.scalar_one()

        site_id = "backlog_site_send"
        if not (
            await test_db.execute(select(Site).where(Site.site_id == site_id))
        ).scalar_one_or_none():
            test_db.add(
                Site(
                    site_id=site_id,
                    user_id=user.id,
                    name="Send Test Site",
                    url="https://send.example.com",
                )
            )
            await test_db.flush()

        segment = Segment(site_id=site_id, name="Senders", visitor_count=2)
        test_db.add(segment)
        await test_db.flush()

        suffix = uuidlib.uuid4().hex[:6]
        ok_vid, suppressed_vid = f"send-ok-{suffix}", f"send-no-{suffix}"
        test_db.add_all(
            [
                SegmentMember(segment_id=segment.id, visitor_id=ok_vid, site_id=site_id),
                SegmentMember(segment_id=segment.id, visitor_id=suppressed_vid, site_id=site_id),
                IdentifiedVisitor(
                    visitor_id=ok_vid,
                    site_id=site_id,
                    email=f"ok-{suffix}@test.com",
                    full_name="Okay Person",
                    resolution_provider="form_capture",
                ),
                IdentifiedVisitor(
                    visitor_id=suppressed_vid,
                    site_id=site_id,
                    email=f"no-{suffix}@test.com",
                    do_not_email=True,
                    resolution_provider="form_capture",
                ),
            ]
        )
        campaign = Campaign(
            site_id=site_id,
            segment_id=segment.id,
            name="Backlog Send Test",
            status="active",
            plan={
                "touchpoints": [
                    {
                        "channel": "email",
                        "step": 1,
                        "subject": "Hi {{first_name}}",
                        "body": "Hello {{first_name}}, checking in.",
                    }
                ]
            },
        )
        test_db.add(campaign)
        await test_db.commit()
        return {"site_id": site_id, "campaign_id": str(campaign.id)}

    @pytest.mark.asyncio
    async def test_send_skips_suppressed_and_is_idempotent(
        self, test_client, test_db, user_token, campaign_setup, monkeypatch
    ):
        sent_to: list[str] = []

        async def fake_send(self, to_email, subject, body_html, **kwargs):
            sent_to.append(to_email)
            return {"id": "fake", "status": 202}

        from apps.api.services.email_sender import EmailSender

        monkeypatch.setattr(EmailSender, "send", fake_send)

        url = f"/api/v1/campaigns/{campaign_setup['site_id']}/{campaign_setup['campaign_id']}/send"
        first = await test_client.post(url, headers=_auth(user_token))
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["status"] == "completed"  # full unthrottled send completes
        summary = body["summary"]
        assert summary["sent"] == 1
        assert summary["skipped_suppressed"] == 1
        assert len(sent_to) == 1 and sent_to[0].startswith("ok-")

        # Campaign auto-completes after a full, unthrottled send; flip it
        # back to active to exercise per-recipient idempotency on re-send.
        from apps.api.models.campaign import Campaign

        row = await test_db.execute(
            select(Campaign).where(Campaign.id == campaign_setup["campaign_id"])
        )
        campaign = row.scalar_one()
        campaign.status = "active"
        await test_db.commit()

        second = await test_client.post(url, headers=_auth(user_token))
        assert second.status_code == 200, second.text
        summary2 = second.json()["summary"]
        assert summary2["sent"] == 0
        assert summary2["skipped_already_sent"] == 1
        assert len(sent_to) == 1  # no second email


class TestFeatureRequestAdminGating:
    @pytest.mark.asyncio
    async def test_plain_user_gets_403(self, test_client, user_token):
        resp = await test_client.get(
            "/api/v1/feature-requests", headers=_auth(user_token)
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_gets_200(self, test_client, admin_token):
        resp = await test_client.get(
            "/api/v1/feature-requests", headers=_auth(admin_token)
        )
        assert resp.status_code == 200


class TestInviteConsume:
    @pytest.mark.asyncio
    async def test_invite_is_one_use(self, test_client, test_db, user_token):
        from datetime import datetime, timezone

        from apps.api.models.waitlist import WaitlistSignup

        token_value = f"inv-{uuidlib.uuid4().hex}"
        test_db.add(
            WaitlistSignup(
                email=f"invitee-{uuidlib.uuid4().hex[:6]}@test.com",
                status="approved",
                invite_token=token_value,
                approved_at=datetime.now(timezone.utc),
            )
        )
        await test_db.commit()

        valid = await test_client.get(
            f"/api/v1/waitlist/validate-invite?token={token_value}"
        )
        assert valid.status_code == 200 and valid.json()["valid"] is True

        consume = await test_client.post(
            "/api/v1/waitlist/consume-invite",
            json={"token": token_value},
            headers=_auth(user_token),
        )
        assert consume.status_code == 200 and consume.json()["consumed"] is True

        # Same user re-consume: idempotent OK
        again = await test_client.post(
            "/api/v1/waitlist/consume-invite",
            json={"token": token_value},
            headers=_auth(user_token),
        )
        assert again.status_code == 200

        # Token no longer validates for signup
        revalid = await test_client.get(
            f"/api/v1/waitlist/validate-invite?token={token_value}"
        )
        assert revalid.json()["valid"] is False
