"""Integration tests for the Gumroad Ping webhook (fallback Merchant of Record).

Gumroad is the live billing provider after Lemon Squeezy rejected Beam's product
category. Unlike LS, Gumroad sends NO HMAC signature: the form-encoded Ping is
authenticated by a secret token in the URL and an optional seller_id.

Covers: token auth, not-configured guard, new-user provisioning + idempotency,
existing-user upgrade, price-fallback tier mapping, and refund revocation.

Requires: PostgreSQL running locally (via docker-compose). Uses test_client and
test_db from conftest.py which auto-create tables.
"""

import uuid as uuidlib

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.integration

_URL = "/api/v1/billing/gumroad/webhook"


def _email() -> str:
    return f"gum-{uuidlib.uuid4().hex[:10]}@test.com"


class TestGumroadWebhook:
    @pytest.mark.asyncio
    async def test_not_configured_returns_503(self, test_client, monkeypatch):
        from apps.api.config import settings

        monkeypatch.setattr(settings, "gumroad_webhook_secret", "")
        resp = await test_client.post(f"{_URL}?token=anything", data={"email": _email()})
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_invalid_token_rejected(self, test_client, monkeypatch):
        from apps.api.config import settings

        monkeypatch.setattr(settings, "gumroad_webhook_secret", "sekret")
        resp = await test_client.post(f"{_URL}?token=wrong", data={"email": _email()})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_sale_provisions_new_user_and_is_idempotent(
        self, test_client, test_db, monkeypatch
    ):
        from apps.api.config import settings
        from apps.api.models.user import User

        monkeypatch.setattr(settings, "gumroad_webhook_secret", "sekret")
        email = _email()
        payload = {
            "seller_id": "seller_1",
            "email": email,
            "subscription_id": "gum_sub_1",
            "recurrence": "monthly",
            "variants[Tier]": "Pro",
            "price": "1900",
            "sale_timestamp": "2099-01-01T00:00:00Z",
        }

        for _ in range(2):  # redelivery is idempotent (absolute state)
            ok = await test_client.post(f"{_URL}?token=sekret", data=payload)
            assert ok.status_code == 200
            assert ok.json() == {"received": True}

        result = await test_db.execute(select(User).where(User.email == email))
        users = result.scalars().all()
        assert len(users) == 1  # not duplicated on redelivery
        user = users[0]
        assert user.plan == "pro"
        assert user.subscription_status == "active"
        assert user.stripe_subscription_id == "gum_sub_1"
        assert user.current_period_end is not None

    @pytest.mark.asyncio
    async def test_sale_upgrades_existing_user(self, test_client, test_db, monkeypatch):
        from apps.api.config import settings
        from apps.api.models.user import User

        monkeypatch.setattr(settings, "gumroad_webhook_secret", "sekret")
        email = _email()
        existing = User(email=email, plan="free")
        test_db.add(existing)
        await test_db.commit()

        resp = await test_client.post(
            f"{_URL}?token=sekret",
            data={
                "email": email.upper(),  # case-insensitive match
                "subscription_id": "gum_sub_2",
                "recurrence": "yearly",
                "variants[Tier]": "Max",
                "price": "46800",
            },
        )
        assert resp.status_code == 200

        await test_db.refresh(existing)
        assert existing.plan == "max"
        assert existing.subscription_status == "active"
        assert existing.stripe_subscription_id == "gum_sub_2"

    @pytest.mark.asyncio
    async def test_tier_mapping_falls_back_to_price(
        self, test_client, test_db, monkeypatch
    ):
        from apps.api.config import settings
        from apps.api.models.user import User

        monkeypatch.setattr(settings, "gumroad_webhook_secret", "sekret")
        email = _email()
        # No variants[Tier] key — must resolve "max" from the $49.00 price.
        resp = await test_client.post(
            f"{_URL}?token=sekret",
            data={"email": email, "subscription_id": "gum_sub_3", "price": "4900"},
        )
        assert resp.status_code == 200

        result = await test_db.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        assert user.plan == "max"

    @pytest.mark.asyncio
    async def test_refund_revokes_plan(self, test_client, test_db, monkeypatch):
        from apps.api.config import settings
        from apps.api.models.user import User

        monkeypatch.setattr(settings, "gumroad_webhook_secret", "sekret")
        email = _email()
        paid = User(
            email=email,
            plan="pro",
            subscription_status="active",
            stripe_subscription_id="gum_sub_4",
        )
        test_db.add(paid)
        await test_db.commit()

        resp = await test_client.post(
            f"{_URL}?token=sekret",
            data={"subscription_id": "gum_sub_4", "refunded": "true"},
        )
        assert resp.status_code == 200

        await test_db.refresh(paid)
        assert paid.plan == "free"
        assert paid.subscription_status == "refunded"

    @pytest.mark.asyncio
    async def test_unmapped_tier_is_noop(self, test_client, test_db, monkeypatch):
        from apps.api.config import settings
        from apps.api.models.user import User

        monkeypatch.setattr(settings, "gumroad_webhook_secret", "sekret")
        email = _email()
        resp = await test_client.post(
            f"{_URL}?token=sekret",
            data={"email": email, "price": "100", "variants[Tier]": "Mystery"},
        )
        assert resp.status_code == 200  # acknowledged, but no entitlement granted

        result = await test_db.execute(select(User).where(User.email == email))
        assert result.scalar_one_or_none() is None  # no user created for an unknown tier
