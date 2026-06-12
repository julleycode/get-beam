"""Integration tests for the daily resolution budget gate.

Covers the budget-counting bug fixed in the beta-feedback batch:
- Budget counts DISTINCT visitors attempted today, not ResolutionLog rows
  (each visitor writes one row per provider tried, 2-8 rows).
- Per-site Site.daily_resolution_budget is respected, with the settings
  default (50) as fallback.
- check_identify_budget (success meter) uses the same per-site limit.
- Billing plan-limit pins: unknown plan falls back to the free limit;
  missing user is denied.

Requires: PostgreSQL running locally (via docker-compose).
"""

import uuid as uuidlib
from datetime import datetime

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def budget_site(test_db):
    """Create a user + site (default daily budget 50) and return the Site."""
    from apps.api.models.site import Site
    from apps.api.models.user import User

    user = User(email=f"budget-{uuidlib.uuid4().hex[:8]}@test.com", full_name="Budget Tester")
    test_db.add(user)
    await test_db.flush()

    site = Site(
        site_id=f"budget_site_{uuidlib.uuid4().hex[:8]}",
        user_id=user.id,
        name="Budget Test Site",
        url="https://budget-test.example.com",
    )
    test_db.add(site)
    await test_db.commit()
    return site


def _log(site_id: str, visitor_id: str, provider: str):
    from apps.api.models.visitor import ResolutionLog

    return ResolutionLog(
        site_id=site_id,
        visitor_id=visitor_id,
        provider=provider,
        success=False,
        cost_usd=0.01,
    )


class TestResolutionAttemptCounting:
    @pytest.mark.asyncio
    async def test_counts_distinct_visitors_not_rows(self, test_db, budget_site):
        """6 provider rows across 2 visitors must count as 2 attempts, not 6."""
        from apps.api.services.usage_limits import get_resolution_attempts_today

        for provider in ("leadpipe", "capturify", "pdl_ip_enrich"):
            test_db.add(_log(budget_site.site_id, "visitor-a", provider))
            test_db.add(_log(budget_site.site_id, "visitor-b", provider))
        await test_db.commit()

        used = await get_resolution_attempts_today(test_db, budget_site.site_id)
        assert used == 2

    @pytest.mark.asyncio
    async def test_budget_allows_under_per_site_limit(self, test_db, budget_site):
        from apps.api.services.usage_limits import check_resolution_attempt_budget

        test_db.add(_log(budget_site.site_id, "visitor-a", "leadpipe"))
        await test_db.commit()

        # Default site budget is 50 — one attempt leaves plenty of room.
        assert await check_resolution_attempt_budget(test_db, budget_site.site_id) is True

    @pytest.mark.asyncio
    async def test_budget_blocks_at_per_site_limit(self, test_db, budget_site):
        """Site.daily_resolution_budget=1 blocks the second visitor."""
        from apps.api.services.usage_limits import check_resolution_attempt_budget

        budget_site.daily_resolution_budget = 1
        # 3 rows, but all for ONE visitor — exactly at the limit of 1.
        for provider in ("leadpipe", "capturify", "pdl_ip_enrich"):
            test_db.add(_log(budget_site.site_id, "visitor-a", provider))
        await test_db.commit()

        assert await check_resolution_attempt_budget(test_db, budget_site.site_id) is False

    @pytest.mark.asyncio
    async def test_unknown_site_falls_back_to_settings_default(self, test_db):
        from apps.api.config import settings
        from apps.api.services.usage_limits import get_site_daily_budget

        budget = await get_site_daily_budget(test_db, "no-such-site")
        assert budget == settings.default_daily_resolution_budget

    @pytest.mark.asyncio
    async def test_resolver_method_delegates_to_shared_gate(self, test_db, budget_site):
        """IdentityResolver.check_daily_budget uses the same per-site meter."""
        from apps.api.services.identity_resolver import IdentityResolver

        budget_site.daily_resolution_budget = 1
        test_db.add(_log(budget_site.site_id, "visitor-a", "leadpipe"))
        await test_db.commit()

        resolver = IdentityResolver(test_db, redis_client=object())
        assert await resolver.check_daily_budget(budget_site.site_id) is False


class TestIdentifyBudgetPerSite:
    @pytest.mark.asyncio
    async def test_check_identify_budget_uses_site_limit(self, test_db, budget_site):
        """Success meter (IdentifiedVisitor count) compares against the
        per-site budget, not the global default."""
        from apps.api.models.visitor import IdentifiedVisitor
        from apps.api.services.usage_limits import check_identify_budget
        from sqlalchemy import select
        from apps.api.models.user import User

        budget_site.daily_resolution_budget = 1
        test_db.add(
            IdentifiedVisitor(
                visitor_id="visitor-a",
                site_id=budget_site.site_id,
                email="a@example.com",
                resolved_at=datetime.utcnow(),
            )
        )
        await test_db.commit()

        result = await test_db.execute(select(User).where(User.id == budget_site.user_id))
        user = result.scalar_one()

        budget = await check_identify_budget(test_db, budget_site.site_id, user.id)
        assert budget["limit"] == 1
        assert budget["used"] == 1
        assert budget["allowed"] is False


class TestBillingPlanPins:
    def test_unknown_plan_falls_back_to_free_limit(self):
        from apps.api.services.billing import get_plan_limits

        assert get_plan_limits("unknown-plan") == 10

    @pytest.mark.asyncio
    async def test_missing_user_is_denied(self, test_db):
        from apps.api.services.billing import check_usage_allowed

        assert await check_usage_allowed(test_db, uuidlib.uuid4()) is False
