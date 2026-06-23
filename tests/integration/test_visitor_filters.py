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
    from apps.api.models.visitor import IdentifiedVisitor

    email = f"filter-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"filter_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(
        Site(site_id=site_id, user_id=user.id, name="Filter Site", url="https://filter.example.com")
    )

    # Four visitors spanning countries, dates, enrichment status, and session
    # counts (total_sessions: 1 = new, >1 = returning).
    test_db.add(_visitor(site_id, "v-us-enriched",
        country_code="US", first_seen=datetime(2026, 6, 1), last_seen=datetime(2026, 6, 5),
        identity_status="identified", enrichment_status="enriched", total_sessions=1))
    test_db.add(_visitor(site_id, "v-vn-mid",
        country_code="VN", first_seen=datetime(2026, 6, 10), last_seen=datetime(2026, 6, 12),
        total_sessions=3))
    test_db.add(_visitor(site_id, "v-us-late",
        country_code="US", first_seen=datetime(2026, 6, 20), last_seen=datetime(2026, 6, 21),
        total_sessions=2))
    test_db.add(_visitor(site_id, "v-nocountry",
        country_code=None, first_seen=datetime(2026, 6, 15), last_seen=datetime(2026, 6, 15),
        total_sessions=1))
    # v-us-enriched has an identified email so known-contacts matching has a target.
    test_db.add(IdentifiedVisitor(
        site_id=site_id, visitor_id="v-us-enriched", email="jane@acme.com",
        full_name="Jane Doe", resolution_provider="manual", confidence_score=1.0,
    ))
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
    async def test_visitor_type_new(self, test_client, filter_setup):
        resp = await test_client.get(
            f"/api/v1/visitors/{filter_setup['site_id']}?visitor_type=new",
            headers=_auth(filter_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        # total_sessions <= 1
        assert _ids(resp.json()) == {"v-us-enriched", "v-nocountry"}

    @pytest.mark.asyncio
    async def test_visitor_type_returning(self, test_client, filter_setup):
        resp = await test_client.get(
            f"/api/v1/visitors/{filter_setup['site_id']}?visitor_type=returning",
            headers=_auth(filter_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        # total_sessions > 1
        assert _ids(resp.json()) == {"v-vn-mid", "v-us-late"}

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

    @pytest.mark.asyncio
    async def test_countries_faceted_by_visitor_type(self, test_client, filter_setup):
        # Faceted counts honour the other active filters. Returning (2+ sessions):
        # v-vn-mid (VN, 3) + v-us-late (US, 2). v-us-enriched & v-nocountry are new.
        resp = await test_client.get(
            f"/api/v1/visitors/{filter_setup['site_id']}/countries"
            "?visitor_type=returning",
            headers=_auth(filter_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        counts = {r["country_code"]: r["count"] for r in resp.json()}
        assert counts == {"US": 1, "VN": 1}

    @pytest.mark.asyncio
    async def test_countries_faceted_by_date(self, test_client, filter_setup):
        # first_seen >= 06-15 → v-nocountry(NULL, excluded) + v-us-late(US). VN &
        # the early US visitor drop out, so the dropdown should show only US (1).
        resp = await test_client.get(
            f"/api/v1/visitors/{filter_setup['site_id']}/countries"
            "?first_seen_from=2026-06-15",
            headers=_auth(filter_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        counts = {r["country_code"]: r["count"] for r in resp.json()}
        assert counts == {"US": 1}

    @pytest.mark.asyncio
    async def test_countries_facet_ignores_its_own_country(self, test_client, filter_setup):
        # A facet must not constrain its own counts — passing country=US must NOT
        # collapse the dropdown to {US}; every country still shows.
        resp = await test_client.get(
            f"/api/v1/visitors/{filter_setup['site_id']}/countries?country=US",
            headers=_auth(filter_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        counts = {r["country_code"]: r["count"] for r in resp.json()}
        assert counts == {"US": 2, "VN": 1}


@pytest_asyncio.fixture
async def known_uploaded(test_client, filter_setup):
    """Upload a known-contacts CSV (header + 2 emails). jane@acme.com matches the
    identified visitor v-us-enriched; bob@other.com matches no visitor."""
    resp = await test_client.post(
        f"/api/v1/sites/{filter_setup['site_id']}/known-contacts/upload",
        files={"file": ("known.csv", b"email\njane@acme.com\nBOB@other.com\n", "text/csv")},
        headers=_auth(filter_setup["token"]),
    )
    assert resp.status_code == 200, resp.text
    return {**filter_setup, "upload": resp.json()}


class TestKnownContacts:
    @pytest.mark.asyncio
    async def test_upload_parses_and_dedupes(self, test_client, known_uploaded):
        # Header row "email" isn't an address; 2 real emails ingested.
        assert known_uploaded["upload"] == {
            "inserted": 2, "skipped": 0, "total": 2, "truncated": False,
        }

    @pytest.mark.asyncio
    async def test_reupload_skips_duplicates(self, test_client, known_uploaded):
        # Re-uploading the same list inserts nothing (case-insensitive match).
        resp = await test_client.post(
            f"/api/v1/sites/{known_uploaded['site_id']}/known-contacts/upload",
            files={"file": ("known.csv", b"jane@acme.com\nbob@other.com\n", "text/csv")},
            headers=_auth(known_uploaded["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["inserted"] == 0
        assert resp.json()["skipped"] == 2

    @pytest.mark.asyncio
    async def test_known_badge_on_list(self, test_client, known_uploaded):
        resp = await test_client.get(
            f"/api/v1/visitors/{known_uploaded['site_id']}",
            headers=_auth(known_uploaded["token"]),
        )
        assert resp.status_code == 200, resp.text
        by_id = {v["visitor_id"]: v for v in resp.json()["visitors"]}
        assert by_id["v-us-enriched"]["is_known"] is True
        assert by_id["v-us-enriched"]["known_source"] == "csv"
        assert by_id["v-vn-mid"]["is_known"] is False

    @pytest.mark.asyncio
    async def test_known_filter_true(self, test_client, known_uploaded):
        resp = await test_client.get(
            f"/api/v1/visitors/{known_uploaded['site_id']}?known=true",
            headers=_auth(known_uploaded["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert _ids(resp.json()) == {"v-us-enriched"}

    @pytest.mark.asyncio
    async def test_known_filter_false_excludes_known(self, test_client, known_uploaded):
        resp = await test_client.get(
            f"/api/v1/visitors/{known_uploaded['site_id']}?known=false",
            headers=_auth(known_uploaded["token"]),
        )
        assert resp.status_code == 200, resp.text
        # Everyone except the matched visitor (anonymous/no-email count as not known).
        assert _ids(resp.json()) == {"v-vn-mid", "v-us-late", "v-nocountry"}

    @pytest.mark.asyncio
    async def test_count_and_clear(self, test_client, known_uploaded):
        sid, token = known_uploaded["site_id"], known_uploaded["token"]
        count = await test_client.get(
            f"/api/v1/sites/{sid}/known-contacts/count", headers=_auth(token)
        )
        assert count.json()["count"] == 2

        cleared = await test_client.request(
            "DELETE", f"/api/v1/sites/{sid}/known-contacts", headers=_auth(token)
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["deleted"] == 2

        after = await test_client.get(
            f"/api/v1/sites/{sid}/known-contacts/count", headers=_auth(token)
        )
        assert after.json()["count"] == 0
