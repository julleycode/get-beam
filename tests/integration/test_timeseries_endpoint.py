"""Integration test for the per-day KPI timeseries endpoint.

GET /api/v1/sites/{site_id}/timeseries?days=N returns a gap-filled daily series
(visitors → identified → high-intent), bucketed by Visitor.last_seen, matching
the funnel predicates in services.kpi.

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
        json={"email": email, "password": "testpass123", "full_name": "TS Tester"},
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
async def ts_setup(test_client, test_db):
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import Visitor

    email = f"ts-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"ts_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="TS Site", url="https://ts.example.com"))

    # All seen "today" so they fall in any window. One anonymous, one identified
    # low-intent, one identified high-intent (>=40) → visitors 3 / identified 2 /
    # high_intent 1 in today's bucket.
    now = datetime.utcnow()
    common = dict(
        first_seen=now, last_seen=now, pages_visited=[],
        ip_address="203.0.113.7", enrichment_status="pending",
    )
    test_db.add(Visitor(site_id=site_id, visitor_id="t-anon", intent_score=80,
                        identity_status="anonymous", **common))
    test_db.add(Visitor(site_id=site_id, visitor_id="t-id-low", intent_score=10,
                        identity_status="identified", **common))
    test_db.add(Visitor(site_id=site_id, visitor_id="t-id-high", intent_score=80,
                        identity_status="identified", **common))
    await test_db.commit()
    return {"token": token, "site_id": site_id}


class TestTimeseriesEndpoint:
    @pytest.mark.asyncio
    async def test_series_shape_and_today_counts(self, test_client, ts_setup):
        resp = await test_client.get(
            f"/api/v1/sites/{ts_setup['site_id']}/timeseries?days=7",
            headers=_auth(ts_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["window_days"] == 7
        assert len(body["series"]) == 7  # gap-filled continuous window

        today = datetime.utcnow().date().isoformat()
        assert body["series"][-1]["date"] == today
        last = body["series"][-1]
        assert last["visitors"] == 3
        assert last["identified"] == 2  # anonymous high-intent excluded
        assert last["high_intent"] == 1  # only identified AND intent>=40

        # Totals across the window equal today's row (others are quiet → zero).
        assert sum(p["visitors"] for p in body["series"]) == 3

    @pytest.mark.asyncio
    async def test_other_site_is_isolated(self, test_client, ts_setup):
        # A foreign site_id the caller doesn't own → 404, not someone else's data.
        resp = await test_client.get(
            "/api/v1/sites/not-my-site/timeseries?days=7",
            headers=_auth(ts_setup["token"]),
        )
        assert resp.status_code == 404
