"""Integration tests for Handoff Detection H5 — server-side AI-fetch beacon.

Requires: PostgreSQL + Redis running locally (via infra/docker-compose.yml).
Run on a DISPOSABLE Postgres only — NEVER against a shared dev DB (KG-4).

Covers:
- AC-H5-1: a valid on-demand beacon POST writes exactly one agent_visit
  (upsert) + one agent_fetch_event against a real DB.
- AC-H5-7: a /pricing-overview/{token} beacon lands the decoded mint-time on
  the fetch event's created_at.
- AC-H5-8 (HIGHEST PRIORITY, non-vacuous tripwire): the same real POST that
  writes agent rows creates ZERO Visitor / IdentifiedVisitor rows — the beacon
  path never touches the identity/emailable surface.
"""

import uuid as uuidlib
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select

pytestmark = pytest.mark.integration


def _mint_token(secs: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    n, out = secs, ""
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return "p" + (out or "0")


@pytest_asyncio.fixture
async def beacon_setup(test_client, test_db, monkeypatch):
    """A real Site + the H5 flag/secret enabled on the shared settings singleton."""
    from apps.api.config import settings
    from apps.api.models.site import Site
    from apps.api.models.user import User

    # Reuse the signup helper shape used by the other agents integration test.
    email = f"beacon-{uuidlib.uuid4().hex[:8]}@test.com"
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Beacon Tester"},
    )
    assert resp.status_code == 200, resp.text
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"beacon_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(
        Site(site_id=site_id, user_id=user.id, name="Beacon Site", url="https://beacon.example.com")
    )
    await test_db.commit()

    monkeypatch.setattr(settings, "agent_fetch_beacon_enabled", True)
    monkeypatch.setattr(settings, "beam_fetch_beacon_secret", "integration-secret")
    return {"site_id": site_id}


async def _count(db, model, **filters) -> int:
    q = select(func.count()).select_from(model)
    for k, v in filters.items():
        q = q.where(getattr(model, k) == v)
    return (await db.execute(q)).scalar_one()


class TestFetchBeaconIntegration:
    @pytest.mark.asyncio
    async def test_on_demand_writes_both_rows(self, test_client, test_db, beacon_setup):
        """AC-H5-1: a valid on-demand POST writes one agent_visit + one agent_fetch_event."""
        from apps.api.models.agent_fetch_event import AgentFetchEvent
        from apps.api.models.agent_visit import AgentVisit

        site_id = beacon_setup["site_id"]
        r = await test_client.post(
            "/api/v1/agents/fetch-beacon",
            headers={"X-Beam-Fetch-Secret": "integration-secret"},
            json={
                "site_id": site_id,
                "user_agent": "Mozilla/5.0 (compatible; ChatGPT-User/1.0)",
                "path": "/pricing",
                "token": None,
            },
        )
        assert r.status_code == 202, r.text

        assert await _count(test_db, AgentVisit, site_id=site_id) == 1
        assert await _count(test_db, AgentFetchEvent, site_id=site_id) == 1

        fe = (
            await test_db.execute(select(AgentFetchEvent).where(AgentFetchEvent.site_id == site_id))
        ).scalar_one()
        assert fe.vendor == "openai"
        assert fe.tier == "on-demand"
        assert fe.raw_ua_token == "chatgpt-user"

    @pytest.mark.asyncio
    async def test_token_mint_ts_lands_on_created_at(self, test_client, test_db, beacon_setup):
        """AC-H5-7: a tokenized-probe beacon lands the decoded mint-time on created_at."""
        from apps.api.models.agent_fetch_event import AgentFetchEvent

        site_id = beacon_setup["site_id"]
        secs = 1_700_000_000
        token = _mint_token(secs)
        r = await test_client.post(
            "/api/v1/agents/fetch-beacon",
            headers={"X-Beam-Fetch-Secret": "integration-secret"},
            json={
                "site_id": site_id,
                "user_agent": "Perplexity-User/1.0",
                "path": f"/pricing-overview/{token}",
                "token": token,
            },
        )
        assert r.status_code == 202, r.text

        fe = (
            await test_db.execute(select(AgentFetchEvent).where(AgentFetchEvent.site_id == site_id))
        ).scalar_one()
        got = fe.created_at
        if got.tzinfo is None:
            got = got.replace(tzinfo=timezone.utc)
        assert got == datetime.fromtimestamp(secs, tz=timezone.utc)

    @pytest.mark.asyncio
    async def test_tripwire_zero_identity_rows(self, test_client, test_db, beacon_setup):
        """AC-H5-8 (non-vacuous): the SAME real POST that writes agent rows creates
        ZERO Visitor / IdentifiedVisitor rows — the beacon never touches identity."""
        from apps.api.models.agent_fetch_event import AgentFetchEvent
        from apps.api.models.agent_visit import AgentVisit
        from apps.api.models.visitor import IdentifiedVisitor, Visitor

        site_id = beacon_setup["site_id"]
        r = await test_client.post(
            "/api/v1/agents/fetch-beacon",
            headers={"X-Beam-Fetch-Secret": "integration-secret"},
            json={
                "site_id": site_id,
                "user_agent": "Claude-User/1.0",
                "path": "/pricing",
                "token": None,
            },
        )
        assert r.status_code == 202, r.text

        # Non-vacuous: the write path DID fire (agent rows exist) ...
        assert await _count(test_db, AgentVisit, site_id=site_id) == 1
        assert await _count(test_db, AgentFetchEvent, site_id=site_id) == 1
        # ... yet ZERO identity rows were created for this (or any) site.
        assert await _count(test_db, Visitor, site_id=site_id) == 0
        assert await _count(test_db, IdentifiedVisitor) == 0
