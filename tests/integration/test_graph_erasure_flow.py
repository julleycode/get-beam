"""Cross-tenant identity-graph erasure — end-to-end flow (needs Postgres).

Precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis`.

Covers the DB-truth half that the mocked unit lane structurally cannot reach:

- T-I1  a queued erasure actually removes the shared-graph row
- T-I2  it removes a row another tenant wrote (no source_site_id filter)
- T-I3  the delete endpoint is not an existence oracle
- T-I4  the whole flow is idempotent
- T-I5  blast radius is exactly the target identity
- T-I6  an erased person is not re-added on a later visit
- T-I7  the operator lookup is admin-gated and flag-gated
- T-I8  the volume marker never rejects the request or blocks local deletion
- T-I9  the operator queue-health surface reports ages, failed rows, and flags
- T-I10 a throttle-flagged row is claimed and processed exactly like any other
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.dependencies import get_current_user, require_admin
from apps.api.main import app
from apps.api.models.beam_identity import BeamIdentityNode
from apps.api.models.erasure_request import ErasureRequest
from apps.api.models.site import Site
from apps.api.models.suppression import SuppressionEntry
from apps.api.models.user import User
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services import graph_erasure as ge
from apps.api.services.pii_crypto import email_hash

pytestmark = pytest.mark.integration

SITE_A = "site_erasure_a"
SITE_B = "site_erasure_b"
EMAIL = "erase.me@example.com"
FP = "fp2_erasure_target"


@pytest_asyncio.fixture
async def sessions(test_engine, monkeypatch):
    """Session factory + the sweep patched to use it (it owns its own session)."""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(ge, "async_session", factory)
    monkeypatch.setattr(ge.settings, "graph_erasure_sweep_enabled", True)
    return factory


async def _seed_visitor(
    s: AsyncSession, site_id: str, visitor_id: str, fingerprint: str, email: str | None
) -> None:
    now = datetime.now(timezone.utc)
    s.add(
        Visitor(
            site_id=site_id,
            visitor_id=visitor_id,
            fingerprint=fingerprint,
            first_seen=now,
            last_seen=now,
            identity_status="identified" if email else "anonymous",
        )
    )
    if email:
        s.add(
            IdentifiedVisitor(
                site_id=site_id,
                visitor_id=visitor_id,
                email=email,
                first_seen=now,
                last_seen=now,
            )
        )


def _graph_node(fingerprint: str, email: str, source_site_id: str) -> BeamIdentityNode:
    return BeamIdentityNode(
        fingerprint=fingerprint,
        email=email,
        email_bidx=email_hash(email),
        full_name="Target Person",
        confidence_score=0.9,
        source_site_id=source_site_id,
        source_provider="pdl",
    )


async def _count_graph(s: AsyncSession, fingerprint: str) -> int:
    return len(
        (
            await s.execute(
                select(BeamIdentityNode.id).where(
                    BeamIdentityNode.fingerprint == fingerprint
                )
            )
        ).scalars().all()
    )


# ───────────────────────── T-I1 / T-I2 / T-I5 ─────────────────────────


@pytest.mark.asyncio
async def test_t_i1_queued_erasure_removes_the_shared_graph_row(sessions):
    async with sessions() as s:
        await _seed_visitor(s, SITE_A, "v-t-i1", FP, EMAIL)
        s.add(_graph_node(FP, EMAIL, SITE_A))
        await s.commit()

        await ge.enqueue_erasure(s, site_id=SITE_A, visitor_id="v-t-i1")

    await ge.run_graph_erasure_sweep()

    async with sessions() as s:
        assert await _count_graph(s, FP) == 0
        req = (await s.execute(select(ErasureRequest))).scalars().first()
        assert req.status == "done" and req.processed_at is not None
        scopes = {
            r.scope
            for r in (await s.execute(select(SuppressionEntry))).scalars().all()
            if r.email_hash == email_hash(EMAIL)
        }
        assert scopes == {"erased", "do_not_process"}


@pytest.mark.asyncio
async def test_t_i2_erases_a_row_another_tenant_wrote(sessions):
    """AC-2's mechanism: the DELETE carries no source_site_id filter."""
    async with sessions() as s:
        await _seed_visitor(s, SITE_A, "v-t-i2", FP, EMAIL)
        s.add(_graph_node(FP, EMAIL, SITE_B))  # written by the OTHER tenant
        await s.commit()
        await ge.enqueue_erasure(s, site_id=SITE_A, visitor_id="v-t-i2")

    await ge.run_graph_erasure_sweep()

    async with sessions() as s:
        assert await _count_graph(s, FP) == 0


@pytest.mark.asyncio
async def test_t_i5_blast_radius_is_exactly_the_target_identity(sessions):
    async with sessions() as s:
        await _seed_visitor(s, SITE_A, "v-t-i5", FP, EMAIL)
        s.add(_graph_node(FP, EMAIL, SITE_A))
        s.add(_graph_node("fp_other_same_site", "other@example.com", SITE_A))
        s.add(_graph_node("fp_other_other_site", "third@example.com", SITE_B))
        await s.commit()
        await ge.enqueue_erasure(s, site_id=SITE_A, visitor_id="v-t-i5")

    await ge.run_graph_erasure_sweep()

    async with sessions() as s:
        assert await _count_graph(s, FP) == 0
        assert await _count_graph(s, "fp_other_same_site") == 1
        assert await _count_graph(s, "fp_other_other_site") == 1


@pytest.mark.asyncio
async def test_t_i4_flow_is_idempotent(sessions):
    async with sessions() as s:
        await _seed_visitor(s, SITE_A, "v-t-i4", FP, EMAIL)
        s.add(_graph_node(FP, EMAIL, SITE_A))
        await s.commit()
        await ge.enqueue_erasure(s, site_id=SITE_A, visitor_id="v-t-i4")
        await ge.enqueue_erasure(s, site_id=SITE_A, visitor_id="v-t-i4")

    await ge.run_graph_erasure_sweep()
    await ge.run_graph_erasure_sweep()  # second pass must be a clean no-op

    async with sessions() as s:
        assert await _count_graph(s, FP) == 0
        statuses = [
            r.status for r in (await s.execute(select(ErasureRequest))).scalars().all()
        ]
        assert statuses == ["done", "done"]
        # on_conflict_do_nothing: still exactly one row per (hash, scope)
        rows = (await s.execute(select(SuppressionEntry))).scalars().all()
        assert len([r for r in rows if r.email_hash == email_hash(EMAIL)]) == 2


# ───────────────────────── T-I6: no silent re-creation ─────────────────────────


@pytest.mark.asyncio
async def test_t_i6_erased_person_is_not_re_added_on_a_later_visit(sessions):
    from apps.api.services.identity_resolver import IdentityResolver

    async with sessions() as s:
        await _seed_visitor(s, SITE_A, "v-t-i6", FP, EMAIL)
        s.add(_graph_node(FP, EMAIL, SITE_A))
        await s.commit()
        await ge.enqueue_erasure(s, site_id=SITE_A, visitor_id="v-t-i6")

    await ge.run_graph_erasure_sweep()

    async with sessions() as s:
        # A later visit on ANY site that would normally write the graph row.
        visitor = Visitor(
            site_id=SITE_B,
            visitor_id="v-returning",
            fingerprint=FP,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        resolver = IdentityResolver(s, redis_client=None)
        await resolver._upsert_beam_identity(visitor, {"email": EMAIL}, "pdl")
        assert await _count_graph(s, FP) == 0, "erased identity was silently re-added"


# ───────────────────────── T-I10: flagged-row processing parity ─────────────────


@pytest.mark.asyncio
async def test_t_i10_throttle_flagged_row_is_processed_identically(sessions):
    """The forensic marker must alter NO execution path."""
    async with sessions() as s:
        s.add(_graph_node("fp_flagged", "flagged@example.com", SITE_A))
        s.add(_graph_node("fp_plain", "plain@example.com", SITE_A))
        for vid, fp, email, flagged in (
            ("v-flagged", "fp_flagged", "flagged@example.com", True),
            ("v-plain", "fp_plain", "plain@example.com", False),
        ):
            s.add(
                ErasureRequest(
                    requesting_site_id=SITE_A,
                    visitor_id=vid,
                    email_bidx_list=[email_hash(email)],
                    fingerprint_list=[fp],
                    targets=["beam_identity_graph"],
                    status="pending",
                    throttle_flagged=flagged,
                )
            )
        await s.commit()

    await ge.run_graph_erasure_sweep()

    async with sessions() as s:
        rows = (await s.execute(select(ErasureRequest))).scalars().all()
        assert {r.status for r in rows} == {"done"}
        assert await _count_graph(s, "fp_flagged") == 0
        assert await _count_graph(s, "fp_plain") == 0
        hashes = {
            r.email_hash for r in (await s.execute(select(SuppressionEntry))).scalars()
        }
        assert email_hash("flagged@example.com") in hashes
        assert email_hash("plain@example.com") in hashes


# ───────────────────────── endpoint-level: T-I3 / T-I8 ─────────────────────────


@pytest_asyncio.fixture
async def user_client(test_client, test_engine, sessions):
    user_id = uuid.uuid4()
    async with sessions() as s:
        s.add(Site(site_id=SITE_A, user_id=user_id, domain="a.example.com"))
        await _seed_visitor(s, SITE_A, "v-with-graph", FP, EMAIL)
        await _seed_visitor(s, SITE_A, "v-without-graph", "fp_no_graph", None)
        s.add(_graph_node(FP, EMAIL, SITE_A))
        await s.commit()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=user_id, email="op@getbeam.fyi"
    )
    yield test_client
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_t_i3_delete_endpoint_is_not_an_existence_oracle(user_client):
    with_graph = await user_client.delete(
        f"/api/v1/visitors/{SITE_A}/v-with-graph/data"
    )
    without_graph = await user_client.delete(
        f"/api/v1/visitors/{SITE_A}/v-without-graph/data"
    )

    assert with_graph.status_code == without_graph.status_code == 200
    a, b = with_graph.json(), without_graph.json()
    assert a.keys() == b.keys()
    assert a["status"] == b["status"] == "deleted"
    assert a["erasure_request"]["status"] == b["erasure_request"]["status"] == "queued"
    assert a["erasure_request"].keys() == b["erasure_request"].keys()
    # No match count / found boolean anywhere in the payload.
    for payload in (a, b):
        assert "found" not in str(payload) and "match" not in str(payload)


@pytest.mark.asyncio
async def test_t_i8_volume_marker_never_rejects_or_blocks_local_deletion(
    user_client, sessions, monkeypatch
):
    """Hard gate: this endpoint has no limiter today. A trip must not regress it
    into failing to delete the tenant's OWN rows."""
    monkeypatch.setattr(ge.settings, "graph_erasure_max_per_minute", 0)

    resp = await user_client.delete(f"/api/v1/visitors/{SITE_A}/v-with-graph/data")

    assert resp.status_code == 200, "the volume marker rejected the request"
    assert resp.status_code != 429
    body = resp.json()
    assert body["erasure_request"]["status"] == "queued"

    async with sessions() as s:
        # The tenant's own rows really are gone.
        assert (
            await s.execute(
                select(Visitor.id).where(
                    Visitor.site_id == SITE_A, Visitor.visitor_id == "v-with-graph"
                )
            )
        ).scalar_one_or_none() is None
        req = (await s.execute(select(ErasureRequest))).scalars().first()
        assert req.throttle_flagged is True
        assert req.status == "pending", "a flagged row was withheld from the queue"


# ───────────────────────── operator surfaces: T-I7 / T-I9 ─────────────────────


@pytest_asyncio.fixture
async def admin_client(test_client, monkeypatch):
    monkeypatch.setattr(ge.settings, "graph_identity_lookup_enabled", True)
    app.dependency_overrides[require_admin] = lambda: User(
        id=uuid.uuid4(), email="admin@getbeam.fyi"
    )
    yield test_client
    app.dependency_overrides.pop(require_admin, None)


@pytest.mark.asyncio
async def test_t_i7_operator_lookup_reports_contributing_sites(
    admin_client, sessions
):
    async with sessions() as s:
        s.add(_graph_node(FP, EMAIL, SITE_A))
        s.add(_graph_node("fp_second", EMAIL, SITE_B))
        await s.commit()

    resp = await admin_client.get(
        "/api/v1/privacy/graph-identity", params={"email": EMAIL}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["exists"] is True
    assert body["row_count"] == 2
    assert sorted(body["contributing_site_ids"]) == sorted([SITE_A, SITE_B])
    assert body["matched_by"] == "email"
    # Never leaks the identity itself.
    assert EMAIL not in resp.text and "Target Person" not in resp.text


@pytest.mark.asyncio
async def test_t_i7b_lookup_requires_exactly_one_selector(admin_client):
    both = await admin_client.get(
        "/api/v1/privacy/graph-identity",
        params={"email": EMAIL, "fingerprint": FP},
    )
    neither = await admin_client.get("/api/v1/privacy/graph-identity")
    assert both.status_code == 400 and neither.status_code == 400


@pytest.mark.asyncio
async def test_t_i7c_lookup_is_not_tenant_reachable(test_client, monkeypatch):
    """No admin override installed: an ordinary caller must never reach it.
    Shipping this route tenant-reachable is a FAIL condition."""
    monkeypatch.setattr(ge.settings, "graph_identity_lookup_enabled", True)
    resp = await test_client.get(
        "/api/v1/privacy/graph-identity", params={"email": EMAIL}
    )
    assert resp.status_code in (401, 403, 404)


@pytest.mark.asyncio
async def test_t_i7d_lookup_is_dormant_when_flag_off(admin_client, monkeypatch):
    monkeypatch.setattr(ge.settings, "graph_identity_lookup_enabled", False)
    resp = await admin_client.get(
        "/api/v1/privacy/graph-identity", params={"email": EMAIL}
    )
    assert resp.status_code == 404, "the route was reachable with the flag off"


@pytest.mark.asyncio
async def test_t_i9_queue_health_reports_ages_failed_and_flags(
    admin_client, sessions
):
    old = datetime.now(timezone.utc) - timedelta(hours=200)
    async with sessions() as s:
        s.add(
            ErasureRequest(
                requesting_site_id=SITE_A,
                visitor_id="v-stuck",
                status="pending",
                targets=["beam_identity_graph"],
                created_at=old,
            )
        )
        s.add(
            ErasureRequest(
                requesting_site_id=SITE_A,
                visitor_id="v-flagged",
                status="pending",
                targets=["beam_identity_graph"],
                throttle_flagged=True,
                created_at=old,
            )
        )
        s.add(
            ErasureRequest(
                requesting_site_id=SITE_A,
                visitor_id="v-failed",
                status="failed",
                targets=["beam_identity_graph"],
                created_at=datetime.now(timezone.utc) - timedelta(hours=30),
            )
        )
        await s.commit()

    resp = await admin_client.get("/api/v1/privacy/erasure-queue-health")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["pending"] == 2
    assert body["oldest_pending_age_hours"] > 199
    assert body["failed"] == 1
    assert 29 < body["oldest_failed_age_hours"] < 31
    assert body["throttle_flagged_count"] == 1
    # Counts and ages only — no request row, bidx, fingerprint, or email.
    assert "bidx" not in resp.text and "fingerprint" not in resp.text
    assert "@" not in resp.text and "v-stuck" not in resp.text


@pytest.mark.asyncio
async def test_t_i9b_queue_health_is_not_tenant_reachable(test_client, monkeypatch):
    monkeypatch.setattr(ge.settings, "graph_identity_lookup_enabled", True)
    resp = await test_client.get("/api/v1/privacy/erasure-queue-health")
    assert resp.status_code in (401, 403, 404)
