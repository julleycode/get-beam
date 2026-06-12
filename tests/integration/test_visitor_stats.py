"""Integration tests for visitor stats + resolution observability fields.

Covers the beta-feedback additions:
- GET /visitors/{site_id}/stats: enriched_unsegmented (segmentation-trigger
  count), eligible_for_resolution, and the daily identify quota trio.
- GET /visitors/{site_id}/{visitor_id}: last_resolution_attempt,
  resolution_providers_tried, resolution_skip_reason.

Requires: PostgreSQL running locally (via docker-compose).
"""

import uuid as uuidlib
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Stats Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _visitor(site_id: str, visitor_id: str, **overrides):
    from apps.api.models.visitor import Visitor

    defaults = dict(
        site_id=site_id,
        visitor_id=visitor_id,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        pages_visited=[],
        ip_address="203.0.113.7",
        intent_score=0.0,
        identity_status="anonymous",
        enrichment_status="pending",
    )
    defaults.update(overrides)
    return Visitor(**defaults)


@pytest_asyncio.fixture
async def stats_setup(test_client, test_db):
    """User (via signup), their site, and a spread of visitors."""
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"stats-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)

    result = await test_db.execute(select(User).where(User.email == email))
    user = result.scalar_one()

    site_id = f"stats_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="Stats Site", url="https://stats.example.com"))

    test_db.add(_visitor(site_id, "v-eligible", intent_score=75.0))
    test_db.add(_visitor(site_id, "v-low-intent", intent_score=10.0))
    test_db.add(_visitor(site_id, "v-no-ip", intent_score=55.0, ip_address=None))
    test_db.add(
        _visitor(
            site_id, "v-enriched-new",
            intent_score=80.0, identity_status="identified",
            enrichment_status="enriched", segmented=False,
        )
    )
    test_db.add(
        _visitor(
            site_id, "v-enriched-old",
            intent_score=85.0, identity_status="identified",
            enrichment_status="enriched", segmented=True,
        )
    )
    await test_db.commit()

    return {"token": token, "site_id": site_id, "user": user}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestVisitorStats:
    @pytest.mark.asyncio
    async def test_stats_new_fields(self, test_client, stats_setup):
        resp = await test_client.get(
            f"/api/v1/visitors/{stats_setup['site_id']}/stats",
            headers=_auth(stats_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["total_visitors"] == 5
        # enriched_unsegmented excludes the segmented=True visitor
        assert data["enriched"] == 2
        assert data["enriched_unsegmented"] == 1
        # anonymous + intent >= 40: v-eligible and v-no-ip
        assert data["eligible_for_resolution"] == 2
        # quota trio (free tier, site default budget 50, nothing used)
        assert data["identify_used_today"] == 0
        assert data["identify_daily_limit"] == 50
        assert data["identify_is_byok"] is False


class TestResolutionSkipReason:
    @pytest.mark.asyncio
    async def test_below_intent_threshold(self, test_client, stats_setup):
        resp = await test_client.get(
            f"/api/v1/visitors/{stats_setup['site_id']}/v-low-intent",
            headers=_auth(stats_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["resolution_skip_reason"] == "below_intent_threshold"

    @pytest.mark.asyncio
    async def test_no_ip_address(self, test_client, stats_setup):
        resp = await test_client.get(
            f"/api/v1/visitors/{stats_setup['site_id']}/v-no-ip",
            headers=_auth(stats_setup["token"]),
        )
        assert resp.json()["resolution_skip_reason"] == "no_ip_address"

    @pytest.mark.asyncio
    async def test_eligible_with_no_attempts_is_awaiting_next_run(
        self, test_client, stats_setup
    ):
        """The prod-bug state: eligible, never attempted → awaiting_next_run."""
        resp = await test_client.get(
            f"/api/v1/visitors/{stats_setup['site_id']}/v-eligible",
            headers=_auth(stats_setup["token"]),
        )
        data = resp.json()
        assert data["resolution_skip_reason"] == "awaiting_next_run"
        assert data["last_resolution_attempt"] is None
        assert data["resolution_providers_tried"] is None

    @pytest.mark.asyncio
    async def test_recent_attempt_surfaces_logs_and_reason(
        self, test_client, test_db, stats_setup
    ):
        from apps.api.models.visitor import ResolutionLog

        for provider in ("leadpipe", "pdl_ip_enrich"):
            test_db.add(
                ResolutionLog(
                    site_id=stats_setup["site_id"],
                    visitor_id="v-eligible",
                    provider=provider,
                    success=False,
                    cost_usd=0.01,
                )
            )
        await test_db.commit()

        resp = await test_client.get(
            f"/api/v1/visitors/{stats_setup['site_id']}/v-eligible",
            headers=_auth(stats_setup["token"]),
        )
        data = resp.json()
        assert data["resolution_skip_reason"] == "recently_attempted"
        assert data["last_resolution_attempt"] is not None
        assert set(data["resolution_providers_tried"]) == {"leadpipe", "pdl_ip_enrich"}

    @pytest.mark.asyncio
    async def test_monthly_plan_limit_reached(self, test_client, test_db, stats_setup):
        stats_setup["user"].monthly_identified_count = 10  # free plan limit
        await test_db.commit()

        resp = await test_client.get(
            f"/api/v1/visitors/{stats_setup['site_id']}/v-eligible",
            headers=_auth(stats_setup["token"]),
        )
        assert resp.json()["resolution_skip_reason"] == "monthly_plan_limit_reached"

    @pytest.mark.asyncio
    async def test_identified_visitor_has_no_skip_reason(
        self, test_client, stats_setup
    ):
        resp = await test_client.get(
            f"/api/v1/visitors/{stats_setup['site_id']}/v-enriched-new",
            headers=_auth(stats_setup["token"]),
        )
        assert resp.json()["resolution_skip_reason"] is None
