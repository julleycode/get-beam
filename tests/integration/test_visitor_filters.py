"""Integration test for Phase 01 — Visitors filter panel.

GET /visitors/{site_id} gains filters: country, enrichment_status, and
first_seen / last_seen date ranges (upper bound EXCLUSIVE). Plus a
GET /visitors/{site_id}/countries feed for the country dropdown.

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
        json={"email": email, "password": "testpass123", "full_name": "Filter Tester"},
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
        first_seen=datetime(2026, 6, 1),
        last_seen=datetime(2026, 6, 1),
        pages_visited=[],
        ip_address="203.0.113.7",
        intent_score=0.0,
        identity_status="anonymous",
        enrichment_status="pending",
    )
    defaults.update(overrides)
    return Visitor(**defaults)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _ids(payload: dict) -> set[str]:
    return {v["visitor_id"] for v in payload["visitors"]}


@pytest_asyncio.fixture
async def filter_setup(test_client, test_db):
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"filter-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"filter_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(
        Site(site_id=site_id, user_id=user.id, name="Filter Site", url="https://filter.example.com")
    )

    # Four visitors spanning countries, dates, and enrichment status.
    test_db.add(_visitor(site_id, "v-us-enriched",
        country_code="US", first_seen=datetime(2026, 6, 1), last_seen=datetime(2026, 6, 5),
        identity_status="identified", enrichment_status="enriched"))
    test_db.add(_visitor(site_id, "v-vn-mid",
        country_code="VN", first_seen=datetime(2026, 6, 10), last_seen=datetime(2026, 6, 12)))
    test_db.add(_visitor(site_id, "v-us-late",
        country_code="US", first_seen=datetime(2026, 6, 20), last_seen=datetime(2026, 6, 21)))
    test_db.add(_visitor(site_id, "v-nocountry",
        country_code=None, first_seen=datetime(2026, 6, 15), last_seen=datetime(2026, 6, 15)))
    await test_db.commit()
    return {"token": token, "site_id": site_id}


class TestVisitorFilters:
    @pytest.mark.asyncio
    async def test_country_filter(self, test_client, filter_setup):
        resp = await test_client.get(
            f"/api/v1/visitors/{filter_setup['site_id']}?country=US",
            headers=_auth(filter_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert _ids(body) == {"v-us-enriched", "v-us-late"}
        assert body["total"] == 2  # total reflects the filter, not all rows

    @pytest.mark.asyncio
    async def test_enrichment_status_filter_is_the_bugfix(self, test_client, filter_setup):
        # Regression: "enriched" must match via enrichment_status. The old UI sent
        # it as identity_status and matched nothing.
        resp = await test_client.get(
            f"/api/v1/visitors/{filter_setup['site_id']}?enrichment_status=enriched",
            headers=_auth(filter_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert _ids(resp.json()) == {"v-us-enriched"}

    @pytest.mark.asyncio
    async def test_first_seen_range_upper_bound_exclusive(self, test_client, filter_setup):
        # from 2026-06-09, to 2026-06-11 (exclusive) → only the 06-10 visitor.
        resp = await test_client.get(
            f"/api/v1/visitors/{filter_setup['site_id']}"
            "?first_seen_from=2026-06-09&first_seen_to=2026-06-11",
            headers=_auth(filter_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert _ids(resp.json()) == {"v-vn-mid"}

    @pytest.mark.asyncio
    async def test_last_seen_from(self, test_client, filter_setup):
        resp = await test_client.get(
            f"/api/v1/visitors/{filter_setup['site_id']}?last_seen_from=2026-06-13",
            headers=_auth(filter_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        # last_seen >= 06-13 → vn-mid(06-12) out; nocountry(06-15) + us-late(06-21) in.
        assert _ids(resp.json()) == {"v-nocountry", "v-us-late"}

    @pytest.mark.asyncio
    async def test_combined_country_and_date(self, test_client, filter_setup):
        resp = await test_client.get(
            f"/api/v1/visitors/{filter_setup['site_id']}"
            "?country=US&first_seen_from=2026-06-15",
            headers=_auth(filter_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert _ids(resp.json()) == {"v-us-late"}  # us-enriched is 06-01, filtered out

    @pytest.mark.asyncio
    async def test_countries_endpoint(self, test_client, filter_setup):
        resp = await test_client.get(
            f"/api/v1/visitors/{filter_setup['site_id']}/countries",
            headers=_auth(filter_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        counts = {r["country_code"]: r["count"] for r in rows}
        assert counts == {"US": 2, "VN": 1}  # NULL country excluded
        assert rows[0]["country_code"] == "US"  # ordered by count desc
