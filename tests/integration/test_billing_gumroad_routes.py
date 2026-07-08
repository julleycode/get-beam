"""Integration tests for Gumroad checkout and subscription-management routes."""

from urllib.parse import parse_qs, urlparse
import uuid as uuidlib

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str, password: str = "testpass123") -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "full_name": "Gumroad Tester"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestGumroadBillingRoutes:
    @pytest.mark.asyncio
    async def test_checkout_returns_configured_gumroad_url(
        self, test_client, monkeypatch
    ):
        from apps.api.config import settings

        email = f"gum-checkout-{uuidlib.uuid4().hex[:8]}@test.com"
        token = await _signup(test_client, email)
        monkeypatch.setattr(
            settings,
            "gumroad_checkout_pro_monthly_url",
            "https://gumroad.com/l/rlkwnz?wanted=true&option=pro-tier&recurrence=monthly",
        )

        resp = await test_client.post(
            "/api/v1/billing/checkout",
            json={"plan": "pro", "interval": "monthly"},
            headers=_auth(token),
        )

        assert resp.status_code == 200, resp.text
        checkout_url = resp.json()["checkout_url"]
        parsed = urlparse(checkout_url)
        query = parse_qs(parsed.query)
        assert parsed.netloc == "gumroad.com"
        assert parsed.path == "/l/rlkwnz"
        assert query["wanted"] == ["true"]
        assert query["option"] == ["pro-tier"]
        assert query["recurrence"] == ["monthly"]
        assert query["email"] == [email]

    @pytest.mark.asyncio
    async def test_checkout_requires_configured_product(self, test_client, monkeypatch):
        from apps.api.config import settings

        token = await _signup(
            test_client, f"gum-missing-{uuidlib.uuid4().hex[:8]}@test.com"
        )
        monkeypatch.setattr(settings, "gumroad_checkout_max_yearly_url", "")
        monkeypatch.setattr(settings, "gumroad_product_permalink", "")

        resp = await test_client.post(
            "/api/v1/billing/checkout",
            json={"plan": "max", "interval": "yearly"},
            headers=_auth(token),
        )

        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_portal_and_cancel_redirect_to_gumroad(
        self, test_client, test_db, monkeypatch
    ):
        from apps.api.config import settings
        from apps.api.models.user import User

        email = f"gum-portal-{uuidlib.uuid4().hex[:8]}@test.com"
        token = await _signup(test_client, email)
        result = await test_db.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        user.plan = "pro"
        user.subscription_status = "active"
        user.stripe_subscription_id = "gum_sub_route_test"
        await test_db.commit()

        monkeypatch.setattr(
            settings,
            "gumroad_customer_portal_url",
            "https://gumroad.com/library",
        )

        portal = await test_client.post(
            "/api/v1/billing/portal",
            headers=_auth(token),
        )
        assert portal.status_code == 200, portal.text
        assert portal.json()["portal_url"] == "https://gumroad.com/library"

        cancel = await test_client.post(
            "/api/v1/billing/cancel",
            json={"reason": "switching providers"},
            headers=_auth(token),
        )
        assert cancel.status_code == 200, cancel.text
        payload = cancel.json()
        assert payload["subscription_status"] == "active"
        assert payload["portal_url"] == "https://gumroad.com/library"
        assert "Gumroad" in payload["message"]
