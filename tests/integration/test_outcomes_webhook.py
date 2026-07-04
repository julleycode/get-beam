"""Integration tests: outcomes webhook (HMAC-signed server-side conversions).

Requires: PostgreSQL running locally (via docker-compose).
"""

import hashlib
import hmac
import json
import uuid as uuidlib
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Hook Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest_asyncio.fixture
async def hook_setup(test_client, test_db):
    """Owner + site + one js_event goal + rotated webhook secret."""
    from apps.api.models.outcome import ConversionGoal
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"hook-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"hook_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="Hook Site", url="https://h.example.com"))
    goal = ConversionGoal(
        id=uuidlib.uuid4(), site_id=site_id, name="Paid Order",
        goal_type="js_event", match_type="contains", pattern="",
        value_cents=2500, repeatable=True,
    )
    test_db.add(goal)
    await test_db.commit()

    resp = await test_client.post(
        f"/api/v1/outcomes/{site_id}/webhook-secret", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    secret = resp.json()["secret"]
    return {"token": token, "site_id": site_id, "secret": secret, "goal": goal}


async def _post_hook(test_client, site_id: str, secret: str, payload: dict, signature: str | None = "auto"):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if signature == "auto":
        headers["X-Beam-Signature"] = _sign(secret, body)
    elif signature is not None:
        headers["X-Beam-Signature"] = signature
    return await test_client.post(
        f"/api/v1/outcomes/{site_id}/webhook", content=body, headers=headers
    )


async def _conversions(test_db, site_id: str):
    from apps.api.models.outcome import Conversion

    return (
        (await test_db.execute(select(Conversion).where(Conversion.site_id == site_id)))
        .scalars()
        .all()
    )


class TestSecretManagement:
    @pytest.mark.asyncio
    async def test_rotate_returns_plaintext_once_and_stores_hint(
        self, test_client, test_db, hook_setup
    ):
        sid, token = hook_setup["site_id"], hook_setup["token"]

        cfg = (
            await test_client.get(
                f"/api/v1/outcomes/{sid}/webhook-config", headers=_auth(token)
            )
        ).json()
        assert cfg["configured"] is True
        assert cfg["hint"].startswith("...")
        assert cfg["url"].endswith(f"/api/v1/outcomes/{sid}/webhook")

        # Rotate → new secret; old one stops validating.
        old_secret = hook_setup["secret"]
        resp = await test_client.post(
            f"/api/v1/outcomes/{sid}/webhook-secret", headers=_auth(token)
        )
        new_secret = resp.json()["secret"]
        assert new_secret != old_secret

        payload = {"goal": "Paid Order", "email": "x@example.com", "event_id": "r1"}
        resp = await _post_hook(test_client, sid, old_secret, payload)
        assert resp.status_code == 400  # old secret invalid
        resp = await _post_hook(test_client, sid, new_secret, payload)
        assert resp.status_code == 202


class TestWebhookAuth:
    @pytest.mark.asyncio
    async def test_valid_signature_records(self, test_client, test_db, hook_setup):
        sid, secret = hook_setup["site_id"], hook_setup["secret"]
        resp = await _post_hook(
            test_client, sid, secret,
            {"goal": "paid order", "email": "buyer@example.com", "value": 49.99, "event_id": "o-1"},
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["recorded"] is True
        assert body["attributed"] is False

        rows = await _conversions(test_db, sid)
        assert len(rows) == 1
        assert rows[0].source == "webhook"
        assert rows[0].value_cents == 4999
        # Unseen email → minted stable id, same derivation as the click redirect.
        from apps.api.services.pii_crypto import email_hash

        assert rows[0].visitor_id == "ec" + email_hash("buyer@example.com")[:30]

    @pytest.mark.asyncio
    async def test_bad_or_missing_signature_400(self, test_client, hook_setup):
        sid, secret = hook_setup["site_id"], hook_setup["secret"]
        payload = {"goal": "Paid Order", "email": "a@b.com"}

        resp = await _post_hook(test_client, sid, secret, payload, signature="deadbeef")
        assert resp.status_code == 400

        resp = await _post_hook(test_client, sid, secret, payload, signature=None)
        assert resp.status_code == 400

        # Tampered body after signing
        body = json.dumps(payload).encode()
        sig = _sign(secret, body)
        tampered = json.dumps({**payload, "value": 999999}).encode()
        resp = await test_client.post(
            f"/api/v1/outcomes/{sid}/webhook",
            content=tampered,
            headers={"Content-Type": "application/json", "X-Beam-Signature": sig},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_unconfigured_503_unknown_site_404(self, test_client, test_db):
        from apps.api.models.site import Site
        from apps.api.models.user import User

        user = User(email=f"bare-{uuidlib.uuid4().hex[:8]}@test.com", full_name="Bare")
        test_db.add(user)
        await test_db.flush()
        bare_site = f"bare_site_{uuidlib.uuid4().hex[:8]}"
        test_db.add(Site(site_id=bare_site, user_id=user.id, name="Bare", url="https://b.example.com"))
        await test_db.commit()

        resp = await _post_hook(test_client, bare_site, "whatever", {"goal": "g", "email": "a@b.com"})
        assert resp.status_code == 503

        resp = await _post_hook(test_client, "no_such_site", "whatever", {"goal": "g", "email": "a@b.com"})
        assert resp.status_code == 404


class TestWebhookSemantics:
    @pytest.mark.asyncio
    async def test_unknown_goal_404_and_invalid_payload_400(self, test_client, hook_setup):
        sid, secret = hook_setup["site_id"], hook_setup["secret"]
        resp = await _post_hook(test_client, sid, secret, {"goal": "Nope", "email": "a@b.com"})
        assert resp.status_code == 404

        # Neither visitor_id nor valid email
        resp = await _post_hook(test_client, sid, secret, {"goal": "Paid Order"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_event_id_idempotent(self, test_client, test_db, hook_setup):
        sid, secret = hook_setup["site_id"], hook_setup["secret"]
        payload = {"goal": "Paid Order", "email": "twice@example.com", "value": 10, "event_id": "dup-1"}
        first = await _post_hook(test_client, sid, secret, payload)
        second = await _post_hook(test_client, sid, secret, payload)
        assert first.json()["recorded"] is True
        assert second.json()["recorded"] is False
        assert len(await _conversions(test_db, sid)) == 1

    @pytest.mark.asyncio
    async def test_known_email_resolves_and_attributes_via_click_link(
        self, test_client, test_db, hook_setup
    ):
        """Email seen before on the site + a recent campaign click → attributed."""
        from apps.api.models.campaign import Campaign, CampaignTouchpoint
        from apps.api.models.outcome import CampaignClick
        from apps.api.models.visitor_email import VisitorEmail
        from apps.api.services.pii_crypto import email_hash, encrypt_pii

        sid, secret = hook_setup["site_id"], hook_setup["secret"]
        email = "known@example.com"
        visitor = "known-visitor-1"

        test_db.add(
            VisitorEmail(
                site_id=sid, visitor_id=visitor, email=email, source="form",
                email_ciphertext=encrypt_pii(email), email_bidx=email_hash(email),
            )
        )
        campaign = Campaign(
            id=uuidlib.uuid4(), site_id=sid, name="Hook Campaign",
            campaign_type="email", status="active", plan={},
        )
        test_db.add(campaign)
        await test_db.flush()
        tp = CampaignTouchpoint(
            id=uuidlib.uuid4(), campaign_id=campaign.id, visitor_id=visitor,
            channel="email", touchpoint_order=1, status="sent",
            content={}, sent_at=datetime.utcnow() - timedelta(days=2),
        )
        test_db.add(tp)
        await test_db.flush()
        test_db.add(
            CampaignClick(
                id=uuidlib.uuid4(), touchpoint_id=tp.id, campaign_id=campaign.id,
                site_id=sid, visitor_id=visitor,
                clicked_at=datetime.utcnow() - timedelta(hours=3),
            )
        )
        await test_db.commit()

        resp = await _post_hook(
            test_client, sid, secret,
            {"goal": "Paid Order", "email": email, "value": 100, "event_id": "attr-1"},
        )
        assert resp.status_code == 202
        assert resp.json() == {"recorded": True, "attributed": True}

        rows = await _conversions(test_db, sid)
        assert len(rows) == 1
        assert rows[0].visitor_id == visitor  # resolved via blind index, not minted
        assert rows[0].attribution == "campaign"
        assert rows[0].matched_by == "click_link"
        assert rows[0].campaign_id == campaign.id
