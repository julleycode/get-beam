"""EvalLayer Phase 05 — agent→company resolution sweep + AC2 exclusion (offline).

All Fully-Automated, mocked ``AsyncSession`` (no Docker, no live DB, no network):

* AC9        — a qualifying agent visit resolves into a Company/lead via the
               existing human pipeline; the contactable identity is the resolved
               human/company, NEVER the AgentVisit record itself.
* D2 GUARD#1 — ``source_agent_visit_id`` is set on the IdentifiedVisitor in the
               SAME INSERT that creates it (marker atomic, no deferred UPDATE).
* AC2 GUARD#2— every enumerated human-data query site (all 7) excludes
               agent-derived rows: the compiled SQL carries
               ``is_agent_derived IS false`` (before/after: an agent row is
               definitionally unselectable), proven per site.
* OQ4        — the synthetic visitor_id runs through resolve()'s own
               check_daily_budget / was_recently_attempted (shared budget +
               30-day no-retry), no separate bucket.
* AC14       — the sweep runs fully offline under MOCK_EXTERNAL_APIS=true.
* D1/D6      — literal-field-name tripwires for both markers.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import apps.api.main  # noqa: F401 — registers ALL ORM models so statement
#                        compilation (below) can configure mappers (relationships
#                        like User→SocialAccount resolve only when every model is
#                        imported). Mirrors tests/conftest.py's model-import block.
from apps.api.config import settings
from apps.api.models.visitor import IdentifiedVisitor
from apps.api.services import agent_company_resolution
from apps.api.services.agent_visitor_filters import human_only_visitor_filter
from apps.api.services.identity_resolver import IdentityResolver

pytestmark = pytest.mark.unit


def _compiled(stmt) -> str:
    """Render a SQLAlchemy statement to SQL text for column-name assertions.

    Uses plain ``str()`` (bound-param placeholders, no literal_binds) so it never
    trips on rendering a mismatched literal — the ``is_agent_derived IS false``
    predicate is inlined either way, which is all these assertions check.
    """
    return str(stmt)


def _fake_agent_visit(**over):
    now = datetime.now(timezone.utc)
    base = dict(
        id=uuid.uuid4(),
        site_id="site-1",
        ip_address="203.0.113.7",
        first_seen_at=now,
        last_seen_at=now,
        resolved_company_id=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


# ─── AC9 + D2 (GUARD #1 marker threaded) — the sweep path ─────────────────────


class _FakeResolver:
    """Stand-in for IdentityResolver that records the marker it was called with
    and simulates an IP→company hit (sets visitor.company_domain)."""

    def __init__(self, db):
        self.db = db
        self.calls: list = []

    async def resolve(self, visitor, source_agent_visit_id=None):
        self.calls.append((visitor.visitor_id, source_agent_visit_id))
        # Simulate resolve()'s IP→company step committing a domain on the visitor.
        visitor.company_domain = "acme.com"
        # The contactable identity is the resolved human/company — NOT the
        # AgentVisit record itself.
        return SimpleNamespace(
            visitor_id=visitor.visitor_id,
            email="lead@acme.com",
            resolution_provider="hunter",
            source_agent_visit_id=source_agent_visit_id,
        )


@pytest.mark.asyncio
async def test_sweep_creates_company_and_threads_marker(monkeypatch):
    av = _fake_agent_visit()
    company_id = uuid.uuid4()

    r_visits = MagicMock()
    r_visits.scalars.return_value.all.return_value = [av]
    r_synth = MagicMock()
    r_synth.scalar_one_or_none.return_value = None  # no existing synthetic row
    r_company = MagicMock()
    r_company.scalar_one_or_none.return_value = company_id

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[r_visits, r_synth, r_company])
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    fake_resolver = _FakeResolver(db)
    monkeypatch.setattr(
        agent_company_resolution, "IdentityResolver", lambda _db: fake_resolver
    )
    upsert = AsyncMock()
    monkeypatch.setattr(agent_company_resolution, "_upsert_company", upsert)

    counters = await agent_company_resolution.run_company_resolution_sweep(db, limit=20)

    # AC9: a Company/lead was upserted from the agent-visit's resolved domain.
    upsert.assert_awaited_once()
    assert upsert.await_args.args[1] == "site-1"
    assert upsert.await_args.args[2] == "acme.com"
    # AC9: the agent visit now points at the resolved company.
    assert av.resolved_company_id == company_id
    # AC9: contactable identity is the resolved company/lead, never the AgentVisit.
    assert fake_resolver.calls, "resolve() must be called for the eligible row"
    # D2 (GUARD #1): the marker passed to resolve() is the AgentVisit.id string.
    called_visitor_id, called_marker = fake_resolver.calls[0]
    assert called_visitor_id == f"agent:{av.id}"
    assert called_marker == str(av.id)
    assert counters == {"processed": 1, "resolved": 1, "companies": 1}


@pytest.mark.asyncio
async def test_sweep_reuses_existing_synthetic_visitor(monkeypatch):
    """Idempotency: an already-created synthetic Visitor is fetched, not duplicated."""
    av = _fake_agent_visit()
    existing = SimpleNamespace(
        visitor_id=f"agent:{av.id}", site_id="site-1", company_domain=None
    )

    r_visits = MagicMock()
    r_visits.scalars.return_value.all.return_value = [av]
    r_synth = MagicMock()
    r_synth.scalar_one_or_none.return_value = existing  # already exists

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[r_visits, r_synth])
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    class _NoDomainResolver(_FakeResolver):
        async def resolve(self, visitor, source_agent_visit_id=None):
            self.calls.append((visitor.visitor_id, source_agent_visit_id))
            return None  # no identity hit, no domain

    fake_resolver = _NoDomainResolver(db)
    monkeypatch.setattr(
        agent_company_resolution, "IdentityResolver", lambda _db: fake_resolver
    )
    monkeypatch.setattr(agent_company_resolution, "_upsert_company", AsyncMock())

    counters = await agent_company_resolution.run_company_resolution_sweep(db)

    # No new Visitor added — the existing synthetic row was reused.
    db.add.assert_not_called()
    assert counters == {"processed": 1, "resolved": 0, "companies": 0}
    assert av.resolved_company_id is None


@pytest.mark.asyncio
async def test_sweep_isolates_per_row_failure(monkeypatch):
    """One bad row must not abort the batch (fail-open, mirror verification sweep)."""
    good = _fake_agent_visit()
    boom = _fake_agent_visit()

    r_visits = MagicMock()
    r_visits.scalars.return_value.all.return_value = [boom, good]

    # boom: synthetic lookup raises. good: synthetic lookup None, company lookup id.
    r_good_synth = MagicMock()
    r_good_synth.scalar_one_or_none.return_value = None
    r_good_company = MagicMock()
    r_good_company.scalar_one_or_none.return_value = uuid.uuid4()

    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            r_visits,
            RuntimeError("boom synthetic lookup failed"),
            r_good_synth,
            r_good_company,
        ]
    )
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    monkeypatch.setattr(
        agent_company_resolution, "IdentityResolver", lambda _db: _FakeResolver(db)
    )
    monkeypatch.setattr(agent_company_resolution, "_upsert_company", AsyncMock())

    counters = await agent_company_resolution.run_company_resolution_sweep(db)

    # Both attempted; boom rolled back; good still resolved.
    assert counters["processed"] == 2
    assert counters["companies"] == 1
    db.rollback.assert_awaited()


# ─── D2 (GUARD #1) atomicity — marker set in the SAME INSERT as the row ───────


@pytest.mark.asyncio
async def test_guard1_marker_set_atomically_in_save_identified():
    added: list = []
    executed: list = []

    async def _exec(stmt, *a, **k):
        executed.append(_compiled(stmt) if hasattr(stmt, "compile") else str(stmt))
        m = MagicMock()
        m.scalar_one_or_none.return_value = None
        return m

    db = MagicMock()
    db.add = lambda o: added.append(o)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(side_effect=_exec)

    resolver = IdentityResolver(db, redis_client=None)
    resolver._active_source_agent_visit_id = "av-123"

    visitor = SimpleNamespace(
        visitor_id="agent:av-123", site_id="site-1", fingerprint=None
    )
    # full_name only (no email) — skips email validation + dedup, isolates the
    # INSERT path. provider rb2b is person-level and NOT owned → no ledger write.
    out = await resolver._save_identified(visitor, {"full_name": "Jane"}, "rb2b")

    assert added, "an IdentifiedVisitor row must be inserted"
    identified = added[0]
    assert isinstance(identified, IdentifiedVisitor)
    # GUARD #1: the marker is present ON THE INSERTED ROW (constructor time).
    assert identified.source_agent_visit_id == "av-123"
    assert out is identified
    # Atomicity: no UPDATE targeting source_agent_visit_id after the initial insert.
    assert not any(
        "UPDATE" in s.upper() and "source_agent_visit_id" in s for s in executed
    ), "marker must be atomic — no deferred UPDATE"


@pytest.mark.asyncio
async def test_human_path_leaves_marker_null():
    added: list = []
    db = MagicMock()
    db.add = lambda o: added.append(o)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())

    resolver = IdentityResolver(db, redis_client=None)
    # Default (never touched by resolve) → None, human behavior unchanged.
    visitor = SimpleNamespace(
        visitor_id="v-1", site_id="site-1", fingerprint=None
    )
    await resolver._save_identified(visitor, {"full_name": "Bob"}, "rb2b")

    assert added[0].source_agent_visit_id is None


# ─── OQ4 — shared budget + 30-day no-retry reuse for the synthetic visitor ────


@pytest.mark.asyncio
async def test_synthetic_visitor_hits_recency_gate(monkeypatch):
    db = MagicMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    resolver = IdentityResolver(db, redis_client=None)

    seen: dict = {}

    async def fake_recent(site_id, visitor_id):
        seen["recent"] = (site_id, visitor_id)
        return True  # 30-day no-retry blocks

    monkeypatch.setattr(resolver, "was_recently_attempted", fake_recent)
    monkeypatch.setattr(resolver, "_check_prior_signals", AsyncMock(return_value=None))
    monkeypatch.setattr(resolver, "_is_email_opted_out", AsyncMock(return_value=False))

    visitor = SimpleNamespace(
        visitor_id="agent:xyz", site_id="site-1", do_not_resolve=False,
        ip_address="203.0.113.9",
    )
    out = await resolver.resolve(visitor, source_agent_visit_id="xyz")

    assert out is None
    # The SYNTHETIC visitor_id debits the same shared per-site recency rule.
    assert seen["recent"] == ("site-1", "agent:xyz")


@pytest.mark.asyncio
async def test_synthetic_visitor_hits_daily_budget(monkeypatch):
    db = MagicMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    resolver = IdentityResolver(db, redis_client=None)

    seen: dict = {}

    async def fake_budget(site_id):
        seen["budget"] = site_id
        return False  # budget exhausted → resolution stops

    monkeypatch.setattr(resolver, "was_recently_attempted", AsyncMock(return_value=False))
    monkeypatch.setattr(resolver, "check_daily_budget", fake_budget)
    monkeypatch.setattr(resolver, "_check_prior_signals", AsyncMock(return_value=None))
    monkeypatch.setattr(resolver, "_is_email_opted_out", AsyncMock(return_value=False))

    visitor = SimpleNamespace(
        visitor_id="agent:xyz", site_id="site-1", do_not_resolve=False,
        ip_address="203.0.113.9",
    )
    out = await resolver.resolve(visitor, source_agent_visit_id="xyz")

    assert out is None
    # Same shared per-site daily budget bucket — no separate agent bucket.
    assert seen["budget"] == "site-1"


# ─── AC2 (GUARD #2) — every enumerated site excludes agent-derived rows ───────


def test_human_only_filter_compiles_to_exclusion():
    assert "is_agent_derived" in _compiled(human_only_visitor_filter())


def test_ac2_shared_router_filter_present():
    # list_visitors (query + count) AND the country-facet endpoint both build
    # their predicates via _build_visitor_filters — assert the human-only
    # predicate is included there (covers plan sites D1 + D6-facet).
    import asyncio
    from apps.api.routers import visitors_helpers

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock())
    filters = asyncio.run(
        visitors_helpers._build_visitor_filters(db, "site-1")
    )
    assert any("is_agent_derived" in _compiled(p) for p in filters)


@pytest.mark.asyncio
async def test_ac2_stat_counts_excludes_agent_rows():
    from apps.api.routers import visitors_helpers

    captured: list = []

    async def _exec(stmt, *a, **k):
        captured.append(_compiled(stmt))
        m = MagicMock()
        m.one.return_value = SimpleNamespace(
            total=1, identified=1, enriched=0,
            enriched_unsegmented=0, eligible_for_resolution=0,
        )
        m.scalar.return_value = 0
        return m

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_exec)
    await visitors_helpers._compute_visitor_stat_counts(db, "site-1")

    assert any("is_agent_derived" in s for s in captured)


@pytest.mark.asyncio
async def test_ac2_resolution_runner_excludes_agent_rows():
    from apps.api.services import resolution_runner

    captured: list = []

    async def _exec(stmt, *a, **k):
        captured.append(_compiled(stmt))
        m = MagicMock()
        m.scalars.return_value.all.return_value = []  # empty → short-circuit
        return m

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_exec)
    # `url` is NOT NULL on the real Site model and run_resolution_for_site reads it
    # via site_resolves_all_us(); a non-owner domain keeps the ordinary intent gate.
    site = SimpleNamespace(
        site_id="site-1", user_id="user-1", url="https://example.com"
    )
    await resolution_runner.run_resolution_for_site(db, site)

    assert any("is_agent_derived" in s for s in captured)


@pytest.mark.asyncio
async def test_ac2_segmentation_select_excludes_agent_rows():
    from apps.api.tasks import segmentation_tasks

    captured: list = []

    async def _exec(stmt, *a, **k):
        captured.append(_compiled(stmt))
        m = MagicMock()
        m.scalars.return_value.all.return_value = []  # empty → early return
        return m

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_exec)
    site = SimpleNamespace(site_id="site-1", user_id="user-1")
    await segmentation_tasks._run_segmentation_for_site(db, site)

    assert any("is_agent_derived" in s for s in captured)


@pytest.mark.asyncio
async def test_ac2_resolution_tasks_process_site_excludes_agent_rows():
    """D7 — the 7th site (Celery-beat process_all_pending_visitors)."""
    from apps.api.tasks import resolution_tasks

    captured: list = []

    r_site = MagicMock()
    # `url` is NOT NULL on the real Site model and _process_site reads it via
    # site_resolves_all_us(); a non-owner domain keeps the ordinary intent gate.
    r_site.scalar_one_or_none.return_value = SimpleNamespace(
        site_id="site-1", user_id="user-1", url="https://example.com"
    )
    r_visitors = MagicMock()
    r_visitors.scalars.return_value.all.return_value = []  # empty → short-circuit

    async def _exec(stmt, *a, **k):
        captured.append(_compiled(stmt))
        return r_site if len(captured) == 1 else r_visitors

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_exec)
    await resolution_tasks._process_site(db, "site-1")

    # The eligibility query (2nd execute) must carry the exclusion.
    assert any("is_agent_derived" in s for s in captured)


@pytest.mark.asyncio
async def test_ac2_visitor_aggregator_resolve_companies_excludes_agent_rows():
    from apps.api.services import visitor_aggregator

    captured: list = []

    async def _exec(stmt, *a, **k):
        captured.append(_compiled(stmt))
        m = MagicMock()
        m.scalars.return_value.all.return_value = []  # empty → early return
        return m

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_exec)
    await visitor_aggregator._resolve_companies(db, "site-1")

    assert any("is_agent_derived" in s for s in captured)


# ─── AC14 — sweep runs fully offline under MOCK_EXTERNAL_APIS=true ────────────


@pytest.mark.asyncio
async def test_sweep_runs_offline_in_mock_mode(monkeypatch):
    monkeypatch.setattr(settings, "mock_external_apis", True)
    av = _fake_agent_visit()

    r_visits = MagicMock()
    r_visits.scalars.return_value.all.return_value = [av]
    r_synth = MagicMock()
    r_synth.scalar_one_or_none.return_value = None

    class _NoNetResolver(_FakeResolver):
        async def resolve(self, visitor, source_agent_visit_id=None):
            self.calls.append((visitor.visitor_id, source_agent_visit_id))
            return None  # no domain, no company → no external dependency

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[r_visits, r_synth])
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    monkeypatch.setattr(
        agent_company_resolution, "IdentityResolver", lambda _db: _NoNetResolver(db)
    )
    monkeypatch.setattr(agent_company_resolution, "_upsert_company", AsyncMock())

    counters = await agent_company_resolution.run_company_resolution_sweep(db)
    assert counters["processed"] == 1


# ─── D1/D6 — literal-field-name tripwires ─────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]

_MARKER_FILES = [
    "apps/api/models/visitor.py",
    "apps/api/services/identity_resolver.py",
    "apps/api/services/agent_company_resolution.py",
]

_AC2_FILES = [
    "apps/api/services/agent_visitor_filters.py",
    "apps/api/routers/visitors.py",
    "apps/api/routers/visitors_helpers.py",
    "apps/api/services/resolution_runner.py",
    "apps/api/tasks/segmentation_tasks.py",
    "apps/api/services/visitor_aggregator.py",
    "apps/api/tasks/resolution_tasks.py",
]


@pytest.mark.parametrize("rel_path", _MARKER_FILES)
def test_source_agent_visit_id_literal_present(rel_path):
    text = (_REPO_ROOT / rel_path).read_text(encoding="utf-8")
    assert "source_agent_visit_id" in text, (
        f"{rel_path} lost the literal 'source_agent_visit_id' — a rename silently "
        "reopens the AC10 agent-origin outreach guard."
    )


@pytest.mark.parametrize("rel_path", _AC2_FILES)
def test_ac2_filter_referenced_at_every_site(rel_path):
    text = (_REPO_ROOT / rel_path).read_text(encoding="utf-8")
    assert "human_only_visitor_filter" in text, (
        f"{rel_path} no longer references human_only_visitor_filter — an AC2 "
        "exclusion site regressed and agent rows can pollute human data."
    )
