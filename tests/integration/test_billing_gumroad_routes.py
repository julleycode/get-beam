"""Integration tests for Gumroad-first billing routes."""

from datetime import datetime, timedelta, timezone
import uuid as uuidlib
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str, password: str = "testpass123") -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "full_name": "Billing Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestGumroadBillingRoutes:
    @pytest.mark.asyncio
    async def test_checkout_uses_configured_gumroad_url(
        self, test_client, test_db, monkeypatch
    ):
        from apps.api.config import settings
        from apps.api.models.user import User

        email = f"gum-checkout-{uuidlib.uuid4().hex[:8]}@test.com"
        token = await _signup(test_client, email)
        monkeypatch.setattr(
            settings,
            "gumroad_checkout_pro_monthly_url",
            "https://beam.gumroad.com/l/pro-monthly",
        )

        resp = await test_client.post(
            "/api/v1/billing/checkout",
            json={"plan": "pro", "interval": "monthly"},
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
        checkout_url = resp.json()["checkout_url"]
        parsed = urlparse(checkout_url)
        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
            "https://beam.gumroad.com/l/pro-monthly"
        )
        assert parse_qs(parsed.query)["wanted"] == ["true"]
        assert parse_qs(parsed.query)["email"] == [email]

        result = await test_db.execute(select(User).where(User.email == email))
        assert result.scalar_one().plan == "free"

    @pytest.mark.asyncio
    async def test_portal_and_cancel_use_gumroad_management_url(
        self, test_client, test_db, monkeypatch
    ):
        from apps.api.config import settings
        from apps.api.models.user import User

        email = f"gum-manage-{uuidlib.uuid4().hex[:8]}@test.com"
        token = await _signup(test_client, email)
        result = await test_db.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        user.plan = "pro"
        user.subscription_status = "active"
        user.stripe_subscription_id = "gum_sub_test"
        await test_db.commit()

        monkeypatch.setattr(
            settings,
            "gumroad_customer_portal_url",
            "https://customers.gumroad.com/subscriptions",
        )

        portal = await test_client.post(
            "/api/v1/billing/portal",
            headers=_auth(token),
        )
        assert portal.status_code == 200, portal.text
        assert portal.json()["portal_url"] == "https://customers.gumroad.com/subscriptions"

        cancel = await test_client.post(
            "/api/v1/billing/cancel",
            json={},
            headers=_auth(token),
        )
        assert cancel.status_code == 200, cancel.text
        body = cancel.json()
        assert body["portal_url"] == "https://customers.gumroad.com/subscriptions"
        assert body["subscription_status"] == "active"

    @pytest.mark.asyncio
    async def test_status_applies_lazy_monthly_reset(self, test_client, test_db):
        from apps.api.models.user import User

        email = f"gum-status-{uuidlib.uuid4().hex[:8]}@test.com"
        token = await _signup(test_client, email)
        result = await test_db.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        user.monthly_identified_count = 10
        user.billing_cycle_reset_at = datetime.now(timezone.utc) - timedelta(days=40)
        await test_db.commit()

        resp = await test_client.get(
            "/api/v1/billing/status",
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["monthly_identified_count"] == 0

        await test_db.refresh(user)
        assert user.monthly_identified_count == 0
