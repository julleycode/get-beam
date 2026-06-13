"""Integration test for Phase 02 — email/full_name in the visitor LIST.

GET /visitors/{site_id} must surface email + full_name from the identity table
for resolved visitors (so the dashboard can show a real email instead of the
opaque visitor_id), while anonymous visitors keep both fields null.

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
        json={"email": email, "password": "testpass123", "full_name": "List Tester"},
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
async def list_setup(test_client, test_db):
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import IdentifiedVisitor

    email = f"list-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)

    result = await test_db.execute(select(User).where(User.email == email))
    user = result.scalar_one()

    site_id = f"list_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="List Site", url="https://list.example.com"))

    # One identified visitor (has an identity row) + one anonymous (no row).
    test_db.add(_visitor(site_id, "v-known", intent_score=80.0, identity_status="identified"))
    test_db.add(_visitor(site_id, "v-anon", intent_score=20.0))
    test_db.add(
        IdentifiedVisitor(
            site_id=site_id,
            visitor_id="v-known",
            email="jane@acme.com",
            full_name="Jane Doe",
            resolution_provider="manual",
            confidence_score=1.0,
        )
    )
    await test_db.commit()
    return {"token": token, "site_id": site_id}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestVisitorListEmail:
    @pytest.mark.asyncio
    async def test_identified_visitor_carries_email_and_name(self, test_client, list_setup):
        resp = await test_client.get(
            f"/api/v1/visitors/{list_setup['site_id']}",
            headers=_auth(list_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        by_id = {v["visitor_id"]: v for v in resp.json()["visitors"]}

        assert by_id["v-known"]["email"] == "jane@acme.com"
        assert by_id["v-known"]["full_name"] == "Jane Doe"

    @pytest.mark.asyncio
    async def test_anonymous_visitor_has_null_email(self, test_client, list_setup):
        resp = await test_client.get(
            f"/api/v1/visitors/{list_setup['site_id']}",
            headers=_auth(list_setup["token"]),
        )
        by_id = {v["visitor_id"]: v for v in resp.json()["visitors"]}

        assert by_id["v-anon"]["email"] is None
        assert by_id["v-anon"]["full_name"] is None
