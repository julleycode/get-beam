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

    @pytest.mark.asyncio
    async def test_lapsed_paid_plan_downgrades_to_free(self, test_client, test_db):
        """A paid plan whose billing period ended (no renewal ping) must fall
        back to free — entitlement expiry is enforced off current_period_end."""
        from apps.api.models.user import User

        email = f"gum-lapsed-{uuidlib.uuid4().hex[:8]}@test.com"
        token = await _signup(test_client, email)
        result = await test_db.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        user.plan = "pro"
        user.subscription_status = "cancelled"
        user.current_period_end = datetime.now(timezone.utc) - timedelta(days=7)
        await test_db.commit()

        resp = await test_client.get("/api/v1/billing/status", headers=_auth(token))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["plan"] == "free"
        assert body["monthly_limit"] == 10

    @pytest.mark.asyncio
    async def test_active_paid_plan_within_period_is_honored(
        self, test_client, test_db
    ):
        """A paid plan still inside its billing period keeps its tier + limit."""
        from apps.api.models.user import User

        email = f"gum-active-{uuidlib.uuid4().hex[:8]}@test.com"
        token = await _signup(test_client, email)
        result = await test_db.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        user.plan = "pro"
        user.subscription_status = "active"
        user.current_period_end = datetime.now(timezone.utc) + timedelta(days=20)
        await test_db.commit()

        resp = await test_client.get("/api/v1/billing/status", headers=_auth(token))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["plan"] == "pro"
        assert body["monthly_limit"] == 50

    @pytest.mark.asyncio
    async def test_paid_plan_without_period_end_is_honored(
        self, test_client, test_db
    ):
        """A comp/admin-granted plan has no billing period on record and must not
        be downgraded by the lapse check."""
        from apps.api.models.user import User

        email = f"gum-comp-{uuidlib.uuid4().hex[:8]}@test.com"
        token = await _signup(test_client, email)
        result = await test_db.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        user.plan = "max"
        user.subscription_status = "active"
        user.current_period_end = None
        await test_db.commit()

        resp = await test_client.get("/api/v1/billing/status", headers=_auth(token))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["plan"] == "max"
        assert body["monthly_limit"] is None

    @pytest.mark.asyncio
    async def test_manage_url_deep_links_to_subscription_when_portal_unset(
        self, test_client, test_db, monkeypatch
    ):
        """With no operator portal URL configured, portal/cancel must deep-link to
        the buyer's own Gumroad subscription-manage page (guest buyers can reach
        it via email magic link) instead of the generic library."""
        from apps.api.config import settings
        from apps.api.models.user import User

        email = f"gum-deeplink-{uuidlib.uuid4().hex[:8]}@test.com"
        token = await _signup(test_client, email)
        result = await test_db.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        user.plan = "pro"
        user.subscription_status = "active"
        user.stripe_subscription_id = "gsub_abc123"
        await test_db.commit()

        monkeypatch.setattr(settings, "gumroad_customer_portal_url", "")

        portal = await test_client.post(
            "/api/v1/billing/portal", headers=_auth(token)
        )
        assert portal.status_code == 200, portal.text
        assert portal.json()["portal_url"] == (
            "https://app.gumroad.com/subscriptions/gsub_abc123/manage"
        )


class TestVariantToPlan:
    """Unit coverage for the Lemon Squeezy variant → plan reverse map."""

    def test_empty_variant_resolves_to_free_not_max(self, monkeypatch):
        """Regression: on a Gumroad-only deploy every ls_variant_* setting is
        empty, which used to collapse the map to {"": "max"} and grant free Max
        on a blank variant id."""
        from apps.api.config import settings
        from apps.api.routers.billing import _variant_to_plan

        for attr in (
            "ls_variant_pro_monthly",
            "ls_variant_pro_yearly",
            "ls_variant_max_monthly",
            "ls_variant_max_yearly",
        ):
            monkeypatch.setattr(settings, attr, "")

        assert _variant_to_plan("") == "free"
        assert _variant_to_plan("   ") == "free"
        assert _variant_to_plan("unmapped-id") == "free"

    def test_configured_variant_maps_to_its_plan(self, monkeypatch):
        from apps.api.config import settings
        from apps.api.routers.billing import _variant_to_plan

        monkeypatch.setattr(settings, "ls_variant_pro_monthly", "111")
        monkeypatch.setattr(settings, "ls_variant_max_yearly", "444")

        assert _variant_to_plan("111") == "pro"
        assert _variant_to_plan("444") == "max"
        assert _variant_to_plan("999") == "free"
