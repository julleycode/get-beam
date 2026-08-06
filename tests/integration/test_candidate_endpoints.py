"""Integration tests for identity-honesty Phase 1 — candidate reject/confirm.

Covers SPEC AC6 (reject → anonymous, do_not_email set, sweep-eligible again),
AC7 (confirm → identified, confirmed_at stamped), the B2 per-row-Identify
decision for candidates, and the multi-tenancy 404 contract.

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
        json={"email": email, "password": "testpass123", "full_name": "Candidate Tester"},
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
        ip_address="203.0.113.9",
        intent_score=75.0,
        identity_status="candidate",
        enrichment_status="pending",
    )
    defaults.update(overrides)
    return Visitor(**defaults)


def _identified(site_id: str, visitor_id: str, **overrides):
    from apps.api.models.visitor import IdentifiedVisitor

    defaults = dict(
        site_id=site_id,
        visitor_id=visitor_id,
        email=f"{visitor_id}@acme.com",
        full_name="Graph Guess",
        resolution_provider="rb2b",
        confidence_score=0.99,
    )
    defaults.update(overrides)
    return IdentifiedVisitor(**defaults)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def candidate_setup(test_client, test_db):
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"candidate-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"cand_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(
        Site(site_id=site_id, user_id=user.id, name="Cand Site", url="https://c.example.com")
    )
    for vid in ("v-reject", "v-confirm", "v-retry"):
        test_db.add(_visitor(site_id, vid))
        test_db.add(_identified(site_id, vid))
    test_db.add(_visitor(site_id, "v-anon", identity_status="anonymous"))
    await test_db.commit()
    return {"token": token, "site_id": site_id, "user": user}


class TestRejectCandidate:
    @pytest.mark.asyncio
    async def test_reject_returns_visitor_to_anonymous_and_blocks_email(
        self, test_client, test_db, candidate_setup
    ):
        from apps.api.models.visitor import IdentifiedVisitor, Visitor

        site_id = candidate_setup["site_id"]
        resp = await test_client.post(
            f"/api/v1/visitors/{site_id}/v-reject/reject-candidate",
            headers=_auth(candidate_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "anonymous"

        status = (
            await test_db.execute(
                select(Visitor.identity_status).where(
                    Visitor.site_id == site_id, Visitor.visitor_id == "v-reject"
                )
            )
        ).scalar_one()
        assert status == "anonymous", "AC6: rejected candidate is sweep-eligible again"

        dne = (
            await test_db.execute(
                select(IdentifiedVisitor.do_not_email).where(
                    IdentifiedVisitor.site_id == site_id,
                    IdentifiedVisitor.visitor_id == "v-reject",
                )
            )
        ).scalar_one()
        assert dne is True, "AC6: the rejected match must stop being contactable"

    @pytest.mark.asyncio
    async def test_reject_keeps_the_row_for_audit(
        self, test_client, test_db, candidate_setup
    ):
        from apps.api.models.visitor import IdentifiedVisitor

        site_id = candidate_setup["site_id"]
        await test_client.post(
            f"/api/v1/visitors/{site_id}/v-reject/reject-candidate",
            headers=_auth(candidate_setup["token"]),
        )
        row = (
            await test_db.execute(
                select(IdentifiedVisitor).where(
                    IdentifiedVisitor.site_id == site_id,
                    IdentifiedVisitor.visitor_id == "v-reject",
                )
            )
        ).scalar_one_or_none()
        assert row is not None, "must not hard-delete — resolved_at stays visible"

    @pytest.mark.asyncio
    async def test_reject_refuses_a_non_candidate(self, test_client, candidate_setup):
        resp = await test_client.post(
            f"/api/v1/visitors/{candidate_setup['site_id']}/v-anon/reject-candidate",
            headers=_auth(candidate_setup["token"]),
        )
        assert resp.status_code == 400


class TestConfirmCandidate:
    @pytest.mark.asyncio
    async def test_confirm_promotes_and_stamps_confirmed_at(
        self, test_client, test_db, candidate_setup
    ):
        from apps.api.models.visitor import IdentifiedVisitor, Visitor

        site_id = candidate_setup["site_id"]
        resp = await test_client.post(
            f"/api/v1/visitors/{site_id}/v-confirm/confirm-candidate",
            headers=_auth(candidate_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "identified"

        status = (
            await test_db.execute(
                select(Visitor.identity_status).where(
                    Visitor.site_id == site_id, Visitor.visitor_id == "v-confirm"
                )
            )
        ).scalar_one()
        assert status == "identified"

        confirmed_at = (
            await test_db.execute(
                select(IdentifiedVisitor.confirmed_at).where(
                    IdentifiedVisitor.site_id == site_id,
                    IdentifiedVisitor.visitor_id == "v-confirm",
                )
            )
        ).scalar_one()
        assert confirmed_at is not None, "AC7: confirmed_at must be stamped"

    @pytest.mark.asyncio
    async def test_confirm_is_not_repeatable(self, test_client, candidate_setup):
        """Once promoted, the visitor is no longer a candidate."""
        site_id = candidate_setup["site_id"]
        first = await test_client.post(
            f"/api/v1/visitors/{site_id}/v-confirm/confirm-candidate",
            headers=_auth(candidate_setup["token"]),
        )
        assert first.status_code == 200
        second = await test_client.post(
            f"/api/v1/visitors/{site_id}/v-confirm/confirm-candidate",
            headers=_auth(candidate_setup["token"]),
        )
        assert second.status_code == 400


class TestCandidateTenancy:
    """C3: cross-tenant access is 404, never 403 — never leak id existence."""

    @pytest.mark.asyncio
    async def test_other_users_site_is_404(self, test_client, candidate_setup):
        other_token = await _signup(
            test_client, f"other-{uuidlib.uuid4().hex[:8]}@test.com"
        )
        for endpoint in ("reject-candidate", "confirm-candidate"):
            resp = await test_client.post(
                f"/api/v1/visitors/{candidate_setup['site_id']}/v-confirm/{endpoint}",
                headers=_auth(other_token),
            )
            assert resp.status_code == 404, endpoint

    @pytest.mark.asyncio
    async def test_unknown_visitor_is_404(self, test_client, candidate_setup):
        resp = await test_client.post(
            f"/api/v1/visitors/{candidate_setup['site_id']}/v-nope/confirm-candidate",
            headers=_auth(candidate_setup["token"]),
        )
        assert resp.status_code == 404


class TestPerRowIdentifyOnACandidate:
    """B2 documented decision: a candidate is NOT re-resolved by the Identify
    button — it would spend provider budget on a status that cannot change."""

    @pytest.mark.asyncio
    async def test_identify_short_circuits_and_points_at_confirm_reject(
        self, test_client, candidate_setup
    ):
        resp = await test_client.post(
            f"/api/v1/visitors/{candidate_setup['site_id']}/v-retry/resolve",
            headers=_auth(candidate_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "candidate"
        assert "confirm" in data["message"].lower()


class TestCandidateStaysEmailable:
    """AC3: candidate-tier is an honesty signal, not a suppression signal."""

    @pytest.mark.asyncio
    async def test_candidate_row_is_still_emailable(self, test_db, candidate_setup):
        from apps.api.services.identity_classification import is_emailable_identity

        assert is_emailable_identity("rb2b", None, False) is True


class TestConfidenceScoreReachesTheApi:
    """AC5: the badge needs confidence_score on the LIST response too."""

    @pytest.mark.asyncio
    async def test_list_response_carries_confidence_score(
        self, test_client, candidate_setup
    ):
        resp = await test_client.get(
            f"/api/v1/visitors/{candidate_setup['site_id']}",
            headers=_auth(candidate_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        rows = {v["visitor_id"]: v for v in resp.json()["visitors"]}
        assert rows["v-confirm"]["confidence_score"] == pytest.approx(0.99)
        assert rows["v-confirm"]["identity_status"] == "candidate"
