"""Integration tests: referral program (claim, activation reward, quota math).

Requires: PostgreSQL running locally (via docker-compose). The activation
service opens its own session against the same test database.
"""

import uuid as uuidlib
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, update

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Ref Tester"},
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
async def referral_pair(test_client, test_db):
    """A referrer (with code) and a fresh referee account."""
    from apps.api.models.user import User

    referrer_email = f"referrer-{uuidlib.uuid4().hex[:8]}@test.com"
    referee_email = f"referee-{uuidlib.uuid4().hex[:8]}@test.com"
    referrer_token = await _signup(test_client, referrer_email)
    referee_token = await _signup(test_client, referee_email)

    resp = await test_client.get("/api/v1/referrals/me", headers=_auth(referrer_token))
    assert resp.status_code == 200, resp.text
    code = resp.json()["code"]

    referrer = (
        await test_db.execute(select(User).where(User.email == referrer_email))
    ).scalar_one()
    referee = (
        await test_db.execute(select(User).where(User.email == referee_email))
    ).scalar_one()
    return {
        "code": code,
        "referrer_token": referrer_token,
        "referee_token": referee_token,
        "referrer_id": referrer.id,
        "referee_id": referee.id,
    }


class TestReferralCode:
    @pytest.mark.asyncio
    async def test_code_is_stable_and_link_contains_it(self, test_client, referral_pair):
        token = referral_pair["referrer_token"]
        first = await test_client.get("/api/v1/referrals/me", headers=_auth(token))
        second = await test_client.get("/api/v1/referrals/me", headers=_auth(token))
        assert first.json()["code"] == second.json()["code"] == referral_pair["code"]
        assert f"?ref={referral_pair['code']}" in first.json()["link"]

    @pytest.mark.asyncio
    async def test_validate_endpoint(self, test_client, referral_pair):
        ok = await test_client.get(
            f"/api/v1/referrals/validate?code={referral_pair['code']}"
        )
        assert ok.json()["valid"] is True
        assert "@" not in (ok.json()["referrer_name"] or "")
        bad = await test_client.get("/api/v1/referrals/validate?code=nope1234")
        assert bad.json() == {"valid": False, "referrer_name": None}


class TestClaim:
    @pytest.mark.asyncio
    async def test_claim_links_and_is_idempotent(self, test_client, test_db, referral_pair):
        from apps.api.models.user import User

        resp = await test_client.post(
            "/api/v1/referrals/claim",
            json={"code": referral_pair["code"]},
            headers=_auth(referral_pair["referee_token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"claimed": True}

        # Retry (page refresh after signup) — idempotent.
        again = await test_client.post(
            "/api/v1/referrals/claim",
            json={"code": referral_pair["code"]},
            headers=_auth(referral_pair["referee_token"]),
        )
        assert again.status_code == 200

        referee = (
            await test_db.execute(
                select(User).where(User.id == referral_pair["referee_id"])
            )
        ).scalar_one()
        assert referee.referred_by_user_id == referral_pair["referrer_id"]
        assert referee.referral_activated_at is None  # reward waits for real events

    @pytest.mark.asyncio
    async def test_self_referral_rejected(self, test_client, referral_pair):
        resp = await test_client.post(
            "/api/v1/referrals/claim",
            json={"code": referral_pair["code"]},
            headers=_auth(referral_pair["referrer_token"]),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_stale_account_rejected(self, test_client, test_db, referral_pair):
        from apps.api.models.user import User

        await test_db.execute(
            update(User)
            .where(User.id == referral_pair["referee_id"])
            .values(created_at=datetime.now(timezone.utc) - timedelta(days=30))
        )
        await test_db.commit()
        resp = await test_client.post(
            "/api/v1/referrals/claim",
            json={"code": referral_pair["code"]},
            headers=_auth(referral_pair["referee_token"]),
        )
        assert resp.status_code == 404


class TestActivation:
    async def _claim_and_seed_events(self, test_client, test_db, referral_pair):
        from apps.api.models.event import Event
        from apps.api.models.site import Site

        resp = await test_client.post(
            "/api/v1/referrals/claim",
            json={"code": referral_pair["code"]},
            headers=_auth(referral_pair["referee_token"]),
        )
        assert resp.status_code == 200

        site_id = f"ref_site_{uuidlib.uuid4().hex[:8]}"
        test_db.add(
            Site(
                site_id=site_id,
                user_id=referral_pair["referee_id"],
                name="Referee Site",
                url="https://r.example.com",
            )
        )
        test_db.add(
            Event(site_id=site_id, visitor_id="rv-1", event_type="pageview")
        )
        await test_db.commit()

    @pytest.mark.asyncio
    async def test_activation_awards_both_sides_exactly_once(
        self, test_client, test_db, referral_pair
    ):
        from apps.api.models.user import User
        from apps.api.services.referral_activation import activate_pending_referrals

        await self._claim_and_seed_events(test_client, test_db, referral_pair)

        first_run = await activate_pending_referrals()
        assert first_run >= 1
        second_run = await activate_pending_referrals()  # must not double-pay

        referrer = (
            await test_db.execute(
                select(User).where(User.id == referral_pair["referrer_id"])
            )
        ).scalar_one()
        referee = (
            await test_db.execute(
                select(User).where(User.id == referral_pair["referee_id"])
            )
        ).scalar_one()
        assert referrer.bonus_monthly_quota == 10  # +10 once, not +20
        assert referee.bonus_monthly_quota == 10
        assert referee.referral_activated_at is not None
        assert second_run == 0 or referrer.bonus_monthly_quota == 10

    @pytest.mark.asyncio
    async def test_no_events_no_reward(self, test_client, test_db, referral_pair):
        from apps.api.models.user import User
        from apps.api.services.referral_activation import activate_pending_referrals

        resp = await test_client.post(
            "/api/v1/referrals/claim",
            json={"code": referral_pair["code"]},
            headers=_auth(referral_pair["referee_token"]),
        )
        assert resp.status_code == 200

        await activate_pending_referrals()
        referee = (
            await test_db.execute(
                select(User).where(User.id == referral_pair["referee_id"])
            )
        ).scalar_one()
        assert referee.referral_activated_at is None
        assert referee.bonus_monthly_quota == 0

    @pytest.mark.asyncio
    async def test_bonus_is_capped(self, test_client, test_db, referral_pair):
        from apps.api.models.user import User
        from apps.api.services.referral_activation import activate_pending_referrals

        await self._claim_and_seed_events(test_client, test_db, referral_pair)
        await test_db.execute(
            update(User)
            .where(User.id == referral_pair["referrer_id"])
            .values(bonus_monthly_quota=45)
        )
        await test_db.commit()

        await activate_pending_referrals()
        referrer = (
            await test_db.execute(
                select(User).where(User.id == referral_pair["referrer_id"])
            )
        ).scalar_one()
        assert referrer.bonus_monthly_quota == 50  # LEAST(45+10, 50)


class TestQuotaMath:
    @pytest.mark.asyncio
    async def test_check_usage_allowed_honors_bonus(self, test_db, referral_pair):
        from apps.api.models.user import User
        from apps.api.services.billing import check_usage_allowed

        # Free plan (limit 10), already at 15 identified — only the +10 bonus
        # keeps them under the effective limit of 20.
        await test_db.execute(
            update(User)
            .where(User.id == referral_pair["referrer_id"])
            .values(
                plan="free",
                monthly_identified_count=15,
                bonus_monthly_quota=10,
                billing_cycle_reset_at=datetime.now(timezone.utc),
            )
        )
        await test_db.commit()
        assert await check_usage_allowed(test_db, referral_pair["referrer_id"]) is True

        await test_db.execute(
            update(User)
            .where(User.id == referral_pair["referrer_id"])
            .values(monthly_identified_count=20)
        )
        await test_db.commit()
        assert await check_usage_allowed(test_db, referral_pair["referrer_id"]) is False

    @pytest.mark.asyncio
    async def test_billing_status_reflects_effective_limit(
        self, test_client, test_db, referral_pair
    ):
        from apps.api.models.user import User

        await test_db.execute(
            update(User)
            .where(User.id == referral_pair["referrer_id"])
            .values(plan="free", bonus_monthly_quota=20)
        )
        await test_db.commit()

        resp = await test_client.get(
            "/api/v1/billing/status", headers=_auth(referral_pair["referrer_token"])
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["monthly_limit"] == 30  # free 10 + bonus 20
        assert body["bonus_monthly_quota"] == 20
