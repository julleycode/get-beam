"""Integration tests for Phase 03 — Agents read API (/api/v1/agents).

Covers SPEC AC6 (agent traffic is structurally separate from human Visitors —
querying /agents returns only AgentVisit rows and never affects /visitors) and
AC7 (each agent row carries a verification_method), plus multi-tenancy (404 not
403), stats grouping, route-ordering (/stats before the detail catch-all), and
the PVL-added invalid-UUID → 404 fix.

Requires: PostgreSQL + Redis running locally (via infra/docker-compose.yml).
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
        json={"email": email, "password": "testpass123", "full_name": "Agent Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _agent(site_id: str, vendor: str, token: str, **overrides):
    from apps.api.models.agent_visit import AgentVisit

    defaults = dict(
        site_id=site_id,
        vendor=vendor,
        product_or_ua_token=token,
        verification_method="ua-only",
        first_seen_at=datetime(2026, 6, 1),
        last_seen_at=datetime(2026, 6, 1),
        ip_address="203.0.113.9",
        page_paths=["/", "/pricing"],
        visit_count=1,
    )
    defaults.update(overrides)
    return AgentVisit(**defaults)


@pytest_asyncio.fixture
async def agents_setup(test_client, test_db):
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import Visitor

    email = f"agents-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"agent_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(
        Site(site_id=site_id, user_id=user.id, name="Agent Site", url="https://agent.example.com")
    )

    # Three agent visits: two OpenAI, one Perplexity — different verification
    # methods and visit counts so stats grouping is testable.
    test_db.add(_agent(site_id, "openai", "GPTBot",
        verification_method="ip-verified", visit_count=5,
        last_seen_at=datetime(2026, 6, 10)))
    test_db.add(_agent(site_id, "openai", "OAI-SearchBot",
        verification_method="ua-only", visit_count=3,
        last_seen_at=datetime(2026, 6, 12)))
    test_db.add(_agent(site_id, "perplexity", "PerplexityBot",
        verification_method="rdns-verified", visit_count=2,
        last_seen_at=datetime(2026, 6, 8)))

    # A human visitor on the SAME site — proves /agents never leaks Visitor rows
    # and /visitors is unaffected by agent data (AC6).
    # total_pageviews must be > 0: the visitors list filters out "ghost" rows
    # (zero pageviews AND no identity AND no captured email), so a default-zero
    # fixture would be excluded for being a ghost rather than for anything to do
    # with agent data — and this assertion would pass vacuously in reverse.
    test_db.add(Visitor(
        site_id=site_id, visitor_id="human-1",
        first_seen=datetime(2026, 6, 1), last_seen=datetime(2026, 6, 1),
        pages_visited=["/"], total_pageviews=1,
        ip_address="198.51.100.4", intent_score=0.0,
        identity_status="anonymous", enrichment_status="pending",
    ))
    await test_db.commit()
    return {"token": token, "site_id": site_id}


class TestAgentsApi:
    @pytest.mark.asyncio
    async def test_list_agents_only_agent_visits(self, test_client, agents_setup):
        """AC6: /agents returns only AgentVisit rows; hitting /agents does not
        change /visitors list/count results."""
        site_id = agents_setup["site_id"]
        headers = _auth(agents_setup["token"])

        agents_resp = await test_client.get(f"/api/v1/agents/{site_id}", headers=headers)
        assert agents_resp.status_code == 200, agents_resp.text
        agents_body = agents_resp.json()
        # 3 agent rows, none of them the human visitor.
        assert agents_body["total"] == 3
        tokens = {a["product_or_ua_token"] for a in agents_body["agents"]}
        assert tokens == {"GPTBot", "OAI-SearchBot", "PerplexityBot"}
        assert "human-1" not in tokens

        # /visitors is unaffected: still exactly the one human visitor.
        visitors_resp = await test_client.get(f"/api/v1/visitors/{site_id}", headers=headers)
        assert visitors_resp.status_code == 200, visitors_resp.text
        visitors_body = visitors_resp.json()
        assert visitors_body["total"] == 1
        assert visitors_body["visitors"][0]["visitor_id"] == "human-1"

    @pytest.mark.asyncio
    async def test_agent_stats_shape(self, test_client, agents_setup):
        """AC6: /stats grouped-by-vendor counts are correct."""
        site_id = agents_setup["site_id"]
        resp = await test_client.get(
            f"/api/v1/agents/{site_id}/stats", headers=_auth(agents_setup["token"])
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # total_visits = sum(visit_count) = 5 + 3 + 2 = 10
        assert body["total_visits"] == 10
        assert body["distinct_vendors"] == 2
        # by_vendor is a row-count per vendor: 2 openai rows, 1 perplexity row.
        assert body["by_vendor"] == {"openai": 2, "perplexity": 1}

    @pytest.mark.asyncio
    async def test_agent_verification_method_in_response(self, test_client, agents_setup):
        """AC7: list and detail rows carry verification_method in the allowed set."""
        site_id = agents_setup["site_id"]
        headers = _auth(agents_setup["token"])
        allowed = {"ua-only", "ip-verified", "rdns-verified"}

        list_resp = await test_client.get(f"/api/v1/agents/{site_id}", headers=headers)
        assert list_resp.status_code == 200, list_resp.text
        agents = list_resp.json()["agents"]
        assert agents, "expected at least one agent row"
        for a in agents:
            assert a["verification_method"] in allowed

        # Detail row also carries it.
        detail_resp = await test_client.get(
            f"/api/v1/agents/{site_id}/{agents[0]['id']}", headers=headers
        )
        assert detail_resp.status_code == 200, detail_resp.text
        assert detail_resp.json()["verification_method"] in allowed

    @pytest.mark.asyncio
    async def test_agent_vendor_filter(self, test_client, agents_setup):
        site_id = agents_setup["site_id"]
        resp = await test_client.get(
            f"/api/v1/agents/{site_id}?vendor=openai", headers=_auth(agents_setup["token"])
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # total reflects the filter, not all rows.
        assert body["total"] == 2
        assert all(a["vendor"] == "openai" for a in body["agents"])

    @pytest.mark.asyncio
    async def test_agent_verification_method_filter(self, test_client, agents_setup):
        site_id = agents_setup["site_id"]
        resp = await test_client.get(
            f"/api/v1/agents/{site_id}?verification_method=rdns-verified",
            headers=_auth(agents_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 1
        assert body["agents"][0]["product_or_ua_token"] == "PerplexityBot"

    @pytest.mark.asyncio
    async def test_agent_pagination(self, test_client, agents_setup):
        site_id = agents_setup["site_id"]
        headers = _auth(agents_setup["token"])
        resp = await test_client.get(
            f"/api/v1/agents/{site_id}?page=1&page_size=2", headers=headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 3  # total is the full filtered set, not the page
        assert len(body["agents"]) == 2
        assert body["page"] == 1
        assert body["page_size"] == 2
        # Default sort is last_seen_at DESC → first row is the 06-12 OAI-SearchBot.
        assert body["agents"][0]["product_or_ua_token"] == "OAI-SearchBot"

    @pytest.mark.asyncio
    async def test_agent_multi_tenancy_404(self, test_client, agents_setup):
        """AC6 (tenancy): a foreign/nonexistent site_id → 404, never 403."""
        resp = await test_client.get(
            "/api/v1/agents/not_my_site_xyz", headers=_auth(agents_setup["token"])
        )
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_stats_route_registered_before_detail_catchall(self, test_client, agents_setup):
        """/stats resolves to the stats handler, not the /{agent_visit_id}
        detail catch-all (route-ordering sharp edge)."""
        site_id = agents_setup["site_id"]
        resp = await test_client.get(
            f"/api/v1/agents/{site_id}/stats", headers=_auth(agents_setup["token"])
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Stats shape, NOT a detail-row shape (which would carry product_or_ua_token).
        assert "total_visits" in body
        assert "by_vendor" in body
        assert "product_or_ua_token" not in body

    @pytest.mark.asyncio
    async def test_detail_invalid_uuid_returns_404_not_500(self, test_client, agents_setup):
        """PVL-added fix: a malformed (non-UUID) agent_visit_id → 404, not 500."""
        site_id = agents_setup["site_id"]
        resp = await test_client.get(
            f"/api/v1/agents/{site_id}/not-a-uuid", headers=_auth(agents_setup["token"])
        )
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_detail_returns_full_agent(self, test_client, agents_setup):
        site_id = agents_setup["site_id"]
        headers = _auth(agents_setup["token"])
        list_resp = await test_client.get(f"/api/v1/agents/{site_id}", headers=headers)
        agent_id = list_resp.json()["agents"][0]["id"]

        resp = await test_client.get(f"/api/v1/agents/{site_id}/{agent_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Detail carries the extra fields beyond the list projection.
        assert "first_seen_at" in body
        assert "ip_address" in body
        assert "page_paths" in body
        assert "resolved_company_id" in body
