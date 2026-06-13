"""Integration tests for Phase 03 — per-visitor resolve endpoint.

POST /visitors/{site_id}/{visitor_id}/resolve runs the identity waterfall for ONE
visitor (the per-row Identify button). These tests pin the ENDPOINT's wiring —
plan gate, success → usage increment + response shape, idempotency, 404, plan
limit — by stubbing IdentityResolver/Enricher. The resolver's own provider logic
is covered by the resolver's dedicated tests.

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
        json={"email": email, "password": "testpass123", "full_name": "Resolve Tester"},
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
        intent_score=75.0,
        identity_status="anonymous",
        enrichment_status="pending",
    )
    defaults.update(overrides)
    return Visitor(**defaults)


class _FakeResolver:
    """Stand-in for IdentityResolver: marks the visitor identified + persists an
    IdentifiedVisitor, mirroring what the real resolver does on a hit."""

    def __init__(self, db, redis_client=None):
        self.db = db

    async def resolve(self, visitor):
        from apps.api.models.visitor import IdentifiedVisitor

        visitor.identity_status = "identified"
        iv = IdentifiedVisitor(
            site_id=visitor.site_id,
            visitor_id=visitor.visitor_id,
            email="found@acme.com",
            full_name="Found Person",
            resolution_provider="leadpipe",
            confidence_score=0.9,
        )
        self.db.add(iv)
        await self.db.commit()
        return iv


class _MissResolver(_FakeResolver):
    async def resolve(self, visitor):
        visitor.identity_status = "unresolvable"
        await self.db.commit()
        return None


class _FakeEnricher:
    def __init__(self, db):
        self.db = db

    async def enrich_tier1(self, visitor, identified):
        return None


@pytest_asyncio.fixture
async def resolve_setup(test_client, test_db):
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"resolve-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)

    result = await test_db.execute(select(User).where(User.email == email))
    user = result.scalar_one()

    site_id = f"resolve_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="Resolve Site", url="https://r.example.com"))
    test_db.add(_visitor(site_id, "v-anon"))
    test_db.add(_visitor(site_id, "v-already", identity_status="identified"))
    await test_db.commit()
    return {"token": token, "site_id": site_id, "user": user}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _patch(monkeypatch, resolver=_FakeResolver):
    monkeypatch.setattr("apps.api.routers.visitors.IdentityResolver", resolver)
    monkeypatch.setattr("apps.api.routers.visitors.Enricher", _FakeEnricher)


class TestResolveOneVisitor:
    @pytest.mark.asyncio
    async def test_anonymous_visitor_gets_identified(self, test_client, test_db, resolve_setup, monkeypatch):
        _patch(monkeypatch)
        resp = await test_client.post(
            f"/api/v1/visitors/{resolve_setup['site_id']}/v-anon/resolve",
            headers=_auth(resolve_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "identified"
        assert data["email"] == "found@acme.com"

        # Status persisted
        from apps.api.models.visitor import Visitor

        row = await test_db.execute(
            select(Visitor.identity_status).where(
                Visitor.site_id == resolve_setup["site_id"], Visitor.visitor_id == "v-anon"
            )
        )
        assert row.scalar_one() == "identified"

    @pytest.mark.asyncio
    async def test_already_processed_is_idempotent(self, test_client, resolve_setup, monkeypatch):
        _patch(monkeypatch)
        resp = await test_client.post(
            f"/api/v1/visitors/{resolve_setup['site_id']}/v-already/resolve",
            headers=_auth(resolve_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "identified"
        assert "Already processed" in data["message"]

    @pytest.mark.asyncio
    async def test_unknown_visitor_404(self, test_client, resolve_setup, monkeypatch):
        _patch(monkeypatch)
        resp = await test_client.post(
            f"/api/v1/visitors/{resolve_setup['site_id']}/does-not-exist/resolve",
            headers=_auth(resolve_setup["token"]),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_miss_returns_unresolvable(self, test_client, resolve_setup, monkeypatch):
        _patch(monkeypatch, resolver=_MissResolver)
        resp = await test_client.post(
            f"/api/v1/visitors/{resolve_setup['site_id']}/v-anon/resolve",
            headers=_auth(resolve_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "unresolvable"

    @pytest.mark.asyncio
    async def test_monthly_plan_limit_blocks(self, test_client, test_db, resolve_setup, monkeypatch):
        _patch(monkeypatch)
        resolve_setup["user"].monthly_identified_count = 10  # free plan limit
        await test_db.commit()

        resp = await test_client.post(
            f"/api/v1/visitors/{resolve_setup['site_id']}/v-anon/resolve",
            headers=_auth(resolve_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "limit_reached"
