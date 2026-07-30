"""WS1 — AI Evaluation Timeline endpoint integration tests.

Covers the new ``GET /api/v1/visitors/{site_id}/{visitor_id}/agent-timeline``
route (agent-native-revenue WS1). Read-only join over
``agent_handoff_links`` ⋈ ``agent_fetch_events``, tenant-scoped exactly like
``get_visitor_detail``.

Gates (from the plan's Validate Contract, all Fully-Automated):
- AC-WS1-1: chronological ASC order + field shape for a seeded handoff sequence.
- AC-WS1-1 (tenant isolation): foreign site_id → 404 (never 403); foreign
  visitor_id under the caller's own site → 200 + empty list (never 403, never
  cross-site rows).
- AC-WS1-1 (empty state): valid visitor, zero handoff rows → 200 + entries: [].

Requires: PostgreSQL running locally (via docker-compose), same as the sibling
``test_visitor_resolve_endpoint.py``.
"""

import uuid as uuidlib
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Timeline Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _seed_handoff(
    test_db, *, site_id: str, visitor_id: str, page: str, vendor: str,
    confidence: str, created_at: datetime,
):
    """Insert one fetch event + its handoff link, both dated ``created_at``."""
    from apps.api.models.agent_fetch_event import AgentFetchEvent
    from apps.api.models.agent_handoff_link import AgentHandoffLink

    fetch = AgentFetchEvent(
        site_id=site_id,
        vendor=vendor,
        raw_ua_token="gptbot",
        tier="on-demand",
        page_path=page,
        created_at=created_at,
    )
    test_db.add(fetch)
    await test_db.flush()  # populate fetch.id for the link FK-by-value

    test_db.add(
        AgentHandoffLink(
            site_id=site_id,
            visitor_id=visitor_id,
            agent_fetch_event_id=fetch.id,
            confidence=confidence,
            delta_seconds=90,
            matched_page=page,
            created_at=created_at,
        )
    )
    await test_db.commit()


@pytest_asyncio.fixture
async def timeline_setup(test_client, test_db):
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"timeline-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)

    result = await test_db.execute(select(User).where(User.email == email))
    user = result.scalar_one()

    site_id = f"timeline_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="Timeline Site", url="https://t.example.com"))
    await test_db.commit()
    return {"token": token, "site_id": site_id, "user": user}


class TestAgentTimeline:
    @pytest.mark.asyncio
    async def test_returns_chronological_ordered_entries(self, test_client, test_db, timeline_setup):
        """AC-WS1-1: 2+ seeded rows returned in chronological ASC order + shape.

        The later row is seeded FIRST to prove ordering is by created_at, not by
        insertion order.
        """
        site_id = timeline_setup["site_id"]
        visitor_id = "v-timeline"
        now = datetime.now(timezone.utc)

        # Seed the LATER event first (medium/perplexity/docs @ +120s) ...
        await _seed_handoff(
            test_db, site_id=site_id, visitor_id=visitor_id, page="/docs",
            vendor="perplexity", confidence="medium", created_at=now + timedelta(seconds=120),
        )
        # ... then the EARLIER event (high/openai/pricing @ now).
        await _seed_handoff(
            test_db, site_id=site_id, visitor_id=visitor_id, page="/pricing",
            vendor="openai", confidence="high", created_at=now,
        )

        resp = await test_client.get(
            f"/api/v1/visitors/{site_id}/{visitor_id}/agent-timeline",
            headers=_auth(timeline_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        entries = resp.json()["entries"]
        assert len(entries) == 2

        # Chronological ASC: earliest first.
        assert entries[0]["page"] == "/pricing"
        assert entries[0]["vendor"] == "openai"
        assert entries[0]["confidence"] == "high"
        assert entries[1]["page"] == "/docs"
        assert entries[1]["vendor"] == "perplexity"
        assert entries[1]["confidence"] == "medium"

        # Field shape: every entry carries the four thin fields.
        for e in entries:
            assert set(e.keys()) == {"page", "vendor", "timestamp", "confidence"}
            assert e["timestamp"] is not None

    @pytest.mark.asyncio
    async def test_empty_state_returns_200_not_404(self, test_client, timeline_setup):
        """AC-WS1-1 (empty state): valid visitor, zero handoff rows → 200 + []."""
        resp = await test_client.get(
            f"/api/v1/visitors/{timeline_setup['site_id']}/v-no-data/agent-timeline",
            headers=_auth(timeline_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"entries": []}

    @pytest.mark.asyncio
    async def test_foreign_site_id_returns_404_not_403(self, test_client, timeline_setup):
        """AC-WS1-1 (tenant isolation): a site the caller doesn't own → 404.

        Never 403 — matches get_visitor_detail's _verify_site_access, don't leak
        id existence.
        """
        resp = await test_client.get(
            "/api/v1/visitors/some_other_site/v-timeline/agent-timeline",
            headers=_auth(timeline_setup["token"]),
        )
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_foreign_visitor_no_cross_site_leak(self, test_client, test_db, timeline_setup):
        """AC-WS1-1 (tenant isolation): a handoff row under a DIFFERENT site with
        the same visitor_id must not leak into the caller's own-site query.

        Calling the caller's own site with that visitor_id returns an empty list
        (indistinguishable from 'no data' — never 403, never the other site's row).
        """
        from apps.api.models.site import Site

        # A second site owned by the SAME user, seeded with a handoff row.
        other_site_id = f"timeline_other_{uuidlib.uuid4().hex[:8]}"
        test_db.add(
            Site(site_id=other_site_id, user_id=timeline_setup["user"].id,
                 name="Other Site", url="https://o.example.com")
        )
        await test_db.commit()
        await _seed_handoff(
            test_db, site_id=other_site_id, visitor_id="v-shared",
            page="/secret", vendor="openai", confidence="high",
            created_at=datetime.now(timezone.utc),
        )

        # Query the ORIGINAL site with the same visitor_id → no cross-site rows.
        resp = await test_client.get(
            f"/api/v1/visitors/{timeline_setup['site_id']}/v-shared/agent-timeline",
            headers=_auth(timeline_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"entries": []}
