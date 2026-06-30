"""Integration test for the API cost summary endpoint (Phase 1 + 2).

GET /api/v1/costs/{site_id}/summary aggregates the unified api_usage_logs ledger
into total spend, per-provider / per-category rollups, and per-day buckets,
scoped to a window (?days=) and to the requesting user's own site.

Requires: PostgreSQL running locally (via docker-compose).
"""

import uuid as uuidlib
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Cost Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _log(site_id, provider, category, success, cost, created_at, units=None):
    from apps.api.models.api_usage import ApiUsageLog

    return ApiUsageLog(
        site_id=site_id,
        visitor_id=f"v-{uuidlib.uuid4().hex[:8]}",
        provider=provider,
        category=category,
        success=success,
        cost_usd=cost,
        units=units,
        response_time_ms=120,
        created_at=created_at,
    )


@pytest_asyncio.fixture
async def cost_setup(test_client, test_db):
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"cost-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()
    user.is_admin = True  # /costs is admin-only (require_admin)

    site_id = f"cost_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(
        Site(site_id=site_id, user_id=user.id, name="Cost Site", url="https://cost.example.com")
    )

    now = datetime.utcnow()
    old = now - timedelta(days=40)  # outside a 30-day window
    test_db.add(_log(site_id, "pdl", "identity", True, 0.01, now))
    test_db.add(_log(site_id, "pdl", "identity", True, 0.01, now))
    test_db.add(_log(site_id, "pdl", "identity", False, 0.0, now))  # failed, $0
    test_db.add(_log(site_id, "rb2b", "identity", True, 0.09, now))
    # Owned (free) identity resolutions — $0, served from Beam's own data.
    test_db.add(_log(site_id, "form_capture", "identity", True, 0.0, now))
    test_db.add(_log(site_id, "svid_reconcile", "identity", True, 0.0, now))
    test_db.add(_log(site_id, "proxycurl", "enrichment", True, 0.01, now))
    test_db.add(_log(site_id, "osint-industries", "osint", True, 1.0, now, units=1))
    test_db.add(_log(site_id, "pdl", "identity", True, 0.01, old))  # excluded at days=30
    await test_db.commit()
    return {"token": token, "site_id": site_id}


class TestCostSummary:
    @pytest.mark.asyncio
    async def test_window_totals(self, test_client, cost_setup):
        resp = await test_client.get(
            f"/api/v1/costs/{cost_setup['site_id']}/summary?days=30",
            headers=_auth(cost_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # 8 in-window calls (incl. 2 owned $0 identity); the 40-day-old pdl row is excluded.
        assert body["total_calls"] == 8
        assert body["success_calls"] == 7
        assert body["failed_calls"] == 1
        assert body["total_usd"] == pytest.approx(1.12, abs=1e-6)  # owned rows are $0

    @pytest.mark.asyncio
    async def test_by_provider_rollup(self, test_client, cost_setup):
        resp = await test_client.get(
            f"/api/v1/costs/{cost_setup['site_id']}/summary?days=30",
            headers=_auth(cost_setup["token"]),
        )
        body = resp.json()
        by_provider = {p["provider"]: p for p in body["by_provider"]}
        assert by_provider["pdl"]["calls"] == 3
        assert by_provider["pdl"]["cost_usd"] == pytest.approx(0.02, abs=1e-6)
        assert by_provider["pdl"]["success_rate"] == pytest.approx(2 / 3, abs=1e-3)
        # Ordered by cost desc → OSINT ($1) is the most expensive provider.
        assert body["by_provider"][0]["provider"] == "osint-industries"

    @pytest.mark.asyncio
    async def test_by_category_rollup(self, test_client, cost_setup):
        resp = await test_client.get(
            f"/api/v1/costs/{cost_setup['site_id']}/summary?days=30",
            headers=_auth(cost_setup["token"]),
        )
        body = resp.json()
        by_cat = {c["category"]: c for c in body["by_category"]}
        assert by_cat["identity"]["calls"] == 6  # 4 paid + 2 owned ($0)
        assert by_cat["identity"]["cost_usd"] == pytest.approx(0.11, abs=1e-6)
        assert by_cat["enrichment"]["cost_usd"] == pytest.approx(0.01, abs=1e-6)
        assert by_cat["osint"]["cost_usd"] == pytest.approx(1.0, abs=1e-6)

    @pytest.mark.asyncio
    async def test_category_filter(self, test_client, cost_setup):
        resp = await test_client.get(
            f"/api/v1/costs/{cost_setup['site_id']}/summary?days=30&category=osint",
            headers=_auth(cost_setup["token"]),
        )
        body = resp.json()
        assert body["total_calls"] == 1
        assert body["total_usd"] == pytest.approx(1.0, abs=1e-6)

    @pytest.mark.asyncio
    async def test_window_includes_old_rows_when_wide(self, test_client, cost_setup):
        resp = await test_client.get(
            f"/api/v1/costs/{cost_setup['site_id']}/summary?days=90",
            headers=_auth(cost_setup["token"]),
        )
        body = resp.json()
        assert body["total_calls"] == 9  # the 40-day-old row is now in range
        assert body["total_usd"] == pytest.approx(1.13, abs=1e-6)

    @pytest.mark.asyncio
    async def test_identity_coverage(self, test_client, cost_setup):
        # Owned-vs-paid scoreboard: 2 owned (form_capture + svid_reconcile) vs
        # 3 paid identity SUCCESSES (pdl×2 + rb2b×1; the failed pdl doesn't count).
        resp = await test_client.get(
            f"/api/v1/costs/{cost_setup['site_id']}/summary?days=30",
            headers=_auth(cost_setup["token"]),
        )
        cov = resp.json()["identity_coverage"]
        assert cov["owned_calls"] == 2
        assert cov["paid_calls"] == 3
        assert cov["coverage_rate"] == pytest.approx(2 / 5, abs=1e-3)

    @pytest.mark.asyncio
    async def test_non_admin_blocked(self, test_client, cost_setup):
        # /costs is admin-only — a normal (non-admin) user is rejected by
        # require_admin before any site logic runs.
        other = await _signup(test_client, f"other-{uuidlib.uuid4().hex[:8]}@test.com")
        resp = await test_client.get(
            f"/api/v1/costs/{cost_setup['site_id']}/summary",
            headers=_auth(other),
        )
        assert resp.status_code == 403, resp.text
