"""PostgreSQL coverage for AI-attributable resolution eligibility and safety."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select

pytestmark = pytest.mark.integration


def _visitor(site_id: str, visitor_id: str, **overrides):
    from apps.api.models.visitor import Visitor

    values = {
        "site_id": site_id,
        "visitor_id": visitor_id,
        "first_seen": datetime.utcnow(),
        "last_seen": datetime.utcnow(),
        "pages_visited": [],
        "ip_address": "203.0.113.10",
        "intent_score": 1.0,
        "identity_status": "anonymous",
        "enrichment_status": "pending",
    }
    values.update(overrides)
    return Visitor(**values)


async def _signup(test_client, email: str) -> str:
    response = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "AI Priority"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest_asyncio.fixture
async def eligibility_setup(test_client, test_db, monkeypatch):
    from apps.api.config import settings
    from apps.api.models.agent_handoff_link import AgentHandoffLink
    from apps.api.models.site import Site
    from apps.api.models.user import User

    monkeypatch.setattr(settings, "first_win_boost_count", 0)
    email = f"ai-priority-{uuid.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (
        await test_db.execute(select(User).where(User.email == email))
    ).scalar_one()

    site_id = f"ai_priority_{uuid.uuid4().hex[:8]}"
    other_site_id = f"ai_priority_other_{uuid.uuid4().hex[:8]}"
    site = Site(
        site_id=site_id,
        user_id=user.id,
        name="AI Priority",
        url="https://priority.example.com",
        internal_damping_enabled=False,
    )
    test_db.add_all(
        [
            site,
            Site(
                site_id=other_site_id,
                user_id=user.id,
                name="Other",
                url="https://other.example.com",
            ),
            _visitor(site_id, "ai-low", ai_source="chatgpt"),
            _visitor(site_id, "handoff-low", intent_score=2.0),
            _visitor(site_id, "cross-site-low", intent_score=3.0),
            _visitor(site_id, "ordinary-high", intent_score=100.0),
            _visitor(
                site_id,
                "internal-ai",
                ai_source="claude",
                intent_score=90.0,
                internal_override="internal",
            ),
            _visitor(site_id, "optout-high", intent_score=99.0, do_not_resolve=True),
            _visitor(site_id, "synthetic-high", intent_score=98.0, is_agent_derived=True),
            _visitor(site_id, "manual-human", intent_score=0.0),
        ]
    )
    test_db.add_all(
        [
            AgentHandoffLink(
                site_id=site_id,
                visitor_id="handoff-low",
                agent_fetch_event_id=uuid.uuid4(),
                confidence="high",
                delta_seconds=30,
            ),
            AgentHandoffLink(
                site_id=site_id,
                visitor_id="handoff-low",
                agent_fetch_event_id=uuid.uuid4(),
                confidence="medium",
                delta_seconds=60,
            ),
            AgentHandoffLink(
                site_id=other_site_id,
                visitor_id="cross-site-low",
                agent_fetch_event_id=uuid.uuid4(),
                confidence="high",
                delta_seconds=20,
            ),
        ]
    )
    await test_db.commit()
    return {
        "site": site,
        "site_id": site_id,
        "token": token,
        "user": user,
    }


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestRunnerPriority:
    @pytest.mark.asyncio
    async def test_ai_eligibility_priority_and_safety(
        self, test_db, eligibility_setup, monkeypatch
    ):
        from apps.api.services import resolution_runner
        from apps.api.services.identity_resolver import IdentityResolver

        processed: list[str] = []

        async def fake_resolve(_self, visitor):
            processed.append(visitor.visitor_id)
            return None

        monkeypatch.setattr(IdentityResolver, "resolve", fake_resolve)
        monkeypatch.setattr(
            resolution_runner, "check_usage_allowed", AsyncMock(return_value=True)
        )

        site = eligibility_setup["site"]
        await resolution_runner.run_resolution_for_site(test_db, site, max_resolve=20)
        assert processed == [
            "internal-ai",
            "handoff-low",
            "ai-low",
            "ordinary-high",
        ]
        assert processed.count("handoff-low") == 1
        assert "cross-site-low" not in processed
        assert "optout-high" not in processed
        assert "synthetic-high" not in processed

        processed.clear()
        site.internal_damping_enabled = True
        await resolution_runner.run_resolution_for_site(test_db, site, max_resolve=20)
        assert processed == [
            "handoff-low",
            "ai-low",
            "ordinary-high",
            "internal-ai",
        ]


class _EndpointResolver:
    called: list[str] = []

    def __init__(self, db):
        self.db = db

    async def resolve(self, visitor, source_agent_visit_id=None, force_retry=False):
        from apps.api.models.visitor import IdentifiedVisitor

        self.called.append(visitor.visitor_id)
        visitor.identity_status = "identified"
        identified = IdentifiedVisitor(
            site_id=visitor.site_id,
            visitor_id=visitor.visitor_id,
            email=f"{visitor.visitor_id}@example.com",
            resolution_provider="test",
            confidence_score=0.9,
        )
        self.db.add(identified)
        await self.db.commit()
        return identified


class _NoopEnricher:
    def __init__(self, db):
        self.db = db

    async def enrich_tier1(self, visitor, identified):
        return None


class TestActiveAndManualSurfaces:
    @pytest.mark.asyncio
    async def test_counts_share_full_candidate_rule(
        self, test_client, test_db, eligibility_setup, monkeypatch
    ):
        from apps.api.models.visitor import Visitor
        from apps.api.routers import visitors
        from apps.api.routers.visitors_helpers import _resolution_skip_reason

        queued: list[int] = []

        async def capture_job(site_id: str, max_resolve: int):
            queued.append(max_resolve)

        monkeypatch.setattr(
            visitors,
            "check_identify_budget",
            AsyncMock(
                return_value={"allowed": True, "used": 0, "limit": None, "is_byok": True}
            ),
        )
        monkeypatch.setattr(visitors, "_run_resolution_job", capture_job)
        headers = _auth(eligibility_setup["token"])
        site_id = eligibility_setup["site_id"]
        rows = (
            await test_db.execute(
                select(Visitor).where(
                    Visitor.site_id == site_id,
                    Visitor.visitor_id.in_(
                        ["ai-low", "handoff-low", "cross-site-low"]
                    ),
                )
            )
        ).scalars()
        by_id = {row.visitor_id: row for row in rows}

        assert (
            await _resolution_skip_reason(
                test_db, eligibility_setup["site"], by_id["ai-low"], None
            )
            == "awaiting_next_run"
        )
        assert (
            await _resolution_skip_reason(
                test_db, eligibility_setup["site"], by_id["handoff-low"], None
            )
            == "awaiting_next_run"
        )
        assert (
            await _resolution_skip_reason(
                test_db, eligibility_setup["site"], by_id["cross-site-low"], None
            )
            == "below_intent_threshold"
        )

        stats = await test_client.get(f"/api/v1/visitors/{site_id}/stats", headers=headers)
        overview = await test_client.get("/api/v1/dashboard/overview", headers=headers)
        bulk = await test_client.post(f"/api/v1/visitors/{site_id}/resolve", headers=headers)

        assert stats.status_code == overview.status_code == bulk.status_code == 200
        assert stats.json()["eligible_for_resolution"] == 4
        assert overview.json()["stats"][site_id]["eligible_for_resolution"] == 4
        assert bulk.json()["queued"] == 4
        assert queued == [4]

    @pytest.mark.asyncio
    async def test_manual_endpoints_accept_ai_humans_and_reject_synthetic_rows(
        self, test_client, test_db, eligibility_setup, monkeypatch
    ):
        from apps.api.models.visitor import IdentifiedVisitor
        from apps.api.routers import visitors

        _EndpointResolver.called = []
        monkeypatch.setattr(visitors, "IdentityResolver", _EndpointResolver)
        monkeypatch.setattr(visitors, "Enricher", _NoopEnricher)
        monkeypatch.setattr(
            visitors, "check_usage_allowed", AsyncMock(return_value=True)
        )
        monkeypatch.setattr(visitors, "increment_usage", AsyncMock())
        headers = _auth(eligibility_setup["token"])
        site_id = eligibility_setup["site_id"]

        for visitor_id in ("ai-low", "handoff-low"):
            response = await test_client.post(
                f"/api/v1/visitors/{site_id}/{visitor_id}/resolve",
                headers=headers,
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "identified"

        synthetic_resolve = await test_client.post(
            f"/api/v1/visitors/{site_id}/synthetic-high/resolve",
            headers=headers,
        )
        synthetic_manual = await test_client.post(
            f"/api/v1/visitors/{site_id}/synthetic-high/identify",
            headers=headers,
            json={"email": "synthetic@example.com"},
        )
        human_manual = await test_client.post(
            f"/api/v1/visitors/{site_id}/manual-human/identify",
            headers=headers,
            json={"email": "human@example.com"},
        )

        assert _EndpointResolver.called == ["ai-low", "handoff-low"]
        assert synthetic_resolve.status_code == 404
        assert synthetic_manual.status_code == 404
        assert human_manual.status_code == 200
        synthetic_rows = (
            await test_db.execute(
                select(func.count())
                .select_from(IdentifiedVisitor)
                .where(IdentifiedVisitor.visitor_id == "synthetic-high")
            )
        ).scalar_one()
        assert synthetic_rows == 0
