"""Integration tests — ICP-fit persistence, reachability and query bound.

`Visitor.icp_fit` is written by ONE place only: `_score_icp_fit_for_site`, a
second pass that runs after the `since is None` (full-recompute) upsert loop in
`aggregate_visitors_for_site`. These tests pin the gating, the branch split, the
detail-endpoint reachability, the query bound and the sweep-resilience wrapper
against the real test DB.

Requires: PostgreSQL running locally (docker-compose, localhost:5433).

Scenario → AC map (phase-2-icp-fit-scoring_PLAN_16-08-26.md §Acceptance Criteria):
- test_flag_on_full_recompute_writes_icp_fit    → AC-7  (F3)
- test_flag_off_writes_nothing                  → AC-6  (F3)
- test_null_site_profile_writes_nothing         → AC-6  (F3)
- test_incremental_branch_never_writes_icp_fit  → AC-7  (D5 branch split)
- test_low_fit_visitor_scored_never_left_zero   → AC-5  (never 0 for unscored)
- test_intent_score_unchanged_by_this_phase     → AC-8  (F4)
- test_detail_endpoint_exposes_icp_fit          → AC-16 (F5)
- test_list_endpoint_still_200                  → AC-9  (F5)
- test_query_count_independent_of_visitor_count → AC-15 (F7)
- test_scorer_exception_does_not_abort_sweep    → sweep resilience (H-7)
"""

import uuid as uuidlib
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import event, select

pytestmark = pytest.mark.integration


# A schema-v1 site_profile whose ICP a "VP of Engineering at a US software
# company" matches on all three dimensions.
PROFILE = {
    "summary": "Developer tooling for platform teams.",
    "sells": ["observability"],
    "category": "Developer Tools",
    "sub_industry": None,
    "icp": {
        "personas": [
            {"role": "Engineering leader", "pain": "no visibility"},
            {"role": "Head of Platform", "pain": "toil"},
        ],
        "firmographics": {
            "size_band": "51-200 employees",
            "industries": ["software", "developer tools"],
            "geography": ["United States", "Western Europe"],
        },
    },
    "competitors": [],
    "meta": {"v": 1},
}


def _enable(monkeypatch, value: bool) -> None:
    """Per-test flag toggle — the repo idiom. A process-level env var cannot
    express the OFF case in the same process."""
    from apps.api.config import settings

    monkeypatch.setattr(settings, "icp_fit_enabled", value)


async def _mk_site(test_db, *, profile: dict | None) -> str:
    from apps.api.models.site import Site

    site_id = f"icp_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(
        Site(
            site_id=site_id,
            user_id=uuidlib.uuid4(),
            name="ICP Site",
            url="https://icp.example.com",
            site_profile=profile,
        )
    )
    await test_db.commit()
    return site_id


async def _seed_events(
    test_db,
    site_id: str,
    visitor_id: str,
    *,
    country_code: str = "US",
    pages: tuple[str, ...] = ("/pricing", "/docs", "/blog"),
    sessions: int = 2,
) -> None:
    """Seed pageview events the aggregator will roll into one Visitor row.

    `sessions` is produced by spacing event groups more than 30 minutes apart —
    the aggregator's session-boundary rule.
    """
    from apps.api.models.event import Event

    base = datetime.utcnow() - timedelta(days=1)
    for session_index in range(sessions):
        start = base + timedelta(hours=session_index * 2)
        for offset, page in enumerate(pages):
            test_db.add(
                Event(
                    site_id=site_id,
                    visitor_id=visitor_id,
                    event_type="pageview",
                    url=f"https://icp.example.com{page}",
                    page_path=page,
                    country_code=country_code,
                    device_type="desktop",
                    ip_address="203.0.113.9",
                    scroll_depth=90,
                    time_on_page=30,
                    created_at=start + timedelta(minutes=offset),
                )
            )
    await test_db.commit()


async def _seed_enrichment(
    test_db,
    site_id: str,
    visitor_id: str,
    *,
    job_title: str = "VP of Engineering",
    company_name: str = "Acme",
    industry: str = "Software",
    company_size: str = "51-200",
    seniority_level: str = "executive",
) -> None:
    from apps.api.models.enrichment import EnrichmentProfile

    test_db.add(
        EnrichmentProfile(
            site_id=site_id,
            visitor_id=visitor_id,
            job_title=job_title,
            company_name=company_name,
            industry=industry,
            company_size=company_size,
            seniority_level=seniority_level,
        )
    )
    await test_db.commit()


async def _icp_fit_of(test_db, site_id: str, visitor_id: str) -> float | None:
    from apps.api.models.visitor import Visitor

    return (
        await test_db.execute(
            select(Visitor.icp_fit).where(
                Visitor.site_id == site_id, Visitor.visitor_id == visitor_id
            )
        )
    ).scalar_one()


@pytest.fixture(autouse=True)
def no_company_resolution(monkeypatch):
    """Keep the aggregation sweep off the network. Individual tests that assert
    on resolution re-patch it with a spy."""

    async def _noop(db, site_id):
        return None

    monkeypatch.setattr(
        "apps.api.services.visitor_aggregator._resolve_companies", _noop
    )


# ─── AC-6 / AC-7 — gating and the full-vs-incremental split ──────────────────


class TestPersistenceGating:
    async def test_flag_on_full_recompute_writes_icp_fit(self, test_db, monkeypatch):
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

        _enable(monkeypatch, True)
        site_id = await _mk_site(test_db, profile=PROFILE)
        await _seed_events(test_db, site_id, "v-fit")
        await _seed_enrichment(test_db, site_id, "v-fit")

        await aggregate_visitors_for_site(test_db, site_id, since=None)

        score = await _icp_fit_of(test_db, site_id, "v-fit")
        assert score is not None
        assert 0 <= score <= 100
        # All three dimensions match strongly — this must not be a token score.
        assert score >= 40

    async def test_flag_off_writes_nothing(self, test_db, monkeypatch):
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

        _enable(monkeypatch, False)
        site_id = await _mk_site(test_db, profile=PROFILE)
        await _seed_events(test_db, site_id, "v-off")
        await _seed_enrichment(test_db, site_id, "v-off")

        await aggregate_visitors_for_site(test_db, site_id, since=None)

        assert await _icp_fit_of(test_db, site_id, "v-off") is None

    async def test_null_site_profile_writes_nothing(self, test_db, monkeypatch):
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

        _enable(monkeypatch, True)
        site_id = await _mk_site(test_db, profile=None)
        await _seed_events(test_db, site_id, "v-noprofile")
        await _seed_enrichment(test_db, site_id, "v-noprofile")

        await aggregate_visitors_for_site(test_db, site_id, since=None)

        assert await _icp_fit_of(test_db, site_id, "v-noprofile") is None

    async def test_unscorable_visitor_left_null_never_zero(self, test_db, monkeypatch):
        """No enrichment row and an unmapped country ⇒ 0 scorable dimensions.
        The column must stay NULL — 0 would claim "scored and a poor fit"."""
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

        _enable(monkeypatch, True)
        site_id = await _mk_site(test_db, profile=PROFILE)
        await _seed_events(test_db, site_id, "v-bare", country_code="ZZ")

        await aggregate_visitors_for_site(test_db, site_id, since=None)

        assert await _icp_fit_of(test_db, site_id, "v-bare") is None

    async def test_incremental_branch_never_writes_icp_fit(self, test_db, monkeypatch):
        """The incremental path is deliberately not a writer (D5/D7)."""
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

        _enable(monkeypatch, True)
        site_id = await _mk_site(test_db, profile=PROFILE)
        await _seed_events(test_db, site_id, "v-inc")
        await _seed_enrichment(test_db, site_id, "v-inc")

        await aggregate_visitors_for_site(
            test_db, site_id, since=datetime.utcnow() - timedelta(days=7)
        )

        assert await _icp_fit_of(test_db, site_id, "v-inc") is None


# ─── AC-8 — intent_score is untouched ────────────────────────────────────────


class TestNoIntentRegression:
    async def test_intent_score_unchanged_by_this_phase(self, test_db, monkeypatch):
        from apps.api.models.visitor import Visitor
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

        site_off = await _mk_site(test_db, profile=PROFILE)
        await _seed_events(test_db, site_off, "v-cmp")
        await _seed_enrichment(test_db, site_off, "v-cmp")
        _enable(monkeypatch, False)
        await aggregate_visitors_for_site(test_db, site_off, since=None)
        before = (
            await test_db.execute(
                select(Visitor.intent_score).where(
                    Visitor.site_id == site_off, Visitor.visitor_id == "v-cmp"
                )
            )
        ).scalar_one()

        _enable(monkeypatch, True)
        await aggregate_visitors_for_site(test_db, site_off, since=None)
        after = (
            await test_db.execute(
                select(Visitor.intent_score).where(
                    Visitor.site_id == site_off, Visitor.visitor_id == "v-cmp"
                )
            )
        ).scalar_one()

        assert after == before
        # ...and the ICP score DID land, so this is not a vacuous comparison.
        assert await _icp_fit_of(test_db, site_off, "v-cmp") is not None


# ─── AC-15 — bounded query count ─────────────────────────────────────────────


class TestQueryBound:
    async def _count_for(self, test_db, test_engine, monkeypatch, n_visitors: int) -> int:
        from apps.api.services.visitor_aggregator import (
            _score_icp_fit_for_site,
            aggregate_visitors_for_site,
        )

        _enable(monkeypatch, True)
        site_id = await _mk_site(test_db, profile=PROFILE)
        for i in range(n_visitors):
            await _seed_events(test_db, site_id, f"v-{i}", sessions=1, pages=("/pricing",))
            await _seed_enrichment(test_db, site_id, f"v-{i}")
        # Materialize the Visitor rows first so the counter measures ONLY the
        # ICP pass, not the aggregation that precedes it.
        await aggregate_visitors_for_site(test_db, site_id, since=None)

        counted: list[str] = []

        def _counter(conn, cursor, statement, parameters, context, executemany):
            counted.append(statement)

        # `.sync_engine` is REQUIRED: the test_engine fixture yields an
        # AsyncEngine and `before_cursor_execute` is a synchronous Engine event,
        # so listening on the AsyncEngine directly never fires.
        event.listen(test_engine.sync_engine, "before_cursor_execute", _counter)
        try:
            await _score_icp_fit_for_site(test_db, site_id)
        finally:
            event.remove(test_engine.sync_engine, "before_cursor_execute", _counter)
        return len(counted)

    async def test_query_count_independent_of_visitor_count(
        self, test_db, test_engine, monkeypatch
    ):
        one = await self._count_for(test_db, test_engine, monkeypatch, 1)
        many = await self._count_for(test_db, test_engine, monkeypatch, 25)
        assert one == many, (
            f"query count grew with visitor count ({one} -> {many}): the pass is "
            "no longer bounded (N+1 regression)"
        )
        # 3 reads + 1 bulk write.
        assert one == 4


# ─── H-7 — the new pass must never abort the sweep ──────────────────────────


class TestSweepResilience:
    async def test_scorer_exception_does_not_abort_sweep(self, test_db, monkeypatch):
        """A raise inside the ICP pass must not suppress company resolution —
        the pass runs upstream of it on the same branch."""
        from apps.api.services import visitor_aggregator as agg

        _enable(monkeypatch, True)
        site_id = await _mk_site(test_db, profile=PROFILE)
        await _seed_events(test_db, site_id, "v-boom")

        async def _boom(db, sid):
            raise RuntimeError("scorer exploded")

        resolved: list[str] = []

        async def _spy(db, sid):
            resolved.append(sid)

        monkeypatch.setattr(agg, "_score_icp_fit_for_site", _boom)
        monkeypatch.setattr(agg, "_resolve_companies", _spy)

        count = await agg.aggregate_visitors_for_site(test_db, site_id, since=None)

        assert count == 1
        assert resolved == [site_id], "company resolution was skipped by the ICP pass"


# ─── AC-9 / AC-16 — the score is actually reachable by a user ───────────────


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "ICP Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def owned_site(test_client, test_db):
    """A signed-up owner + one site carrying a reviewed site_profile."""
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"icp-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"icp_owned_{uuidlib.uuid4().hex[:8]}"
    test_db.add(
        Site(
            site_id=site_id,
            user_id=user.id,
            name="ICP Site",
            url="https://icp.example.com",
            site_profile=PROFILE,
        )
    )
    await test_db.commit()
    return token, site_id


class TestDetailReachability:
    async def test_detail_endpoint_exposes_icp_fit(
        self, test_client, test_db, monkeypatch, owned_site
    ):
        """AC-16. The seeded visitor carries THREE non-ICP conviction parts
        (enriched who-they-are + returned 2x + a hot page), so `parts[:3]` is
        FULL — this proves the clause survives truncation rather than passing
        on the trivially easy sparse case."""
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

        token, site_id = owned_site
        _enable(monkeypatch, True)
        await _seed_events(test_db, site_id, "v-detail", sessions=2)
        await _seed_enrichment(test_db, site_id, "v-detail")
        await aggregate_visitors_for_site(test_db, site_id, since=None)

        assert await _icp_fit_of(test_db, site_id, "v-detail") is not None

        resp = await test_client.get(
            f"/api/v1/visitors/{site_id}/v-detail",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["icp_fit"] is not None, "detail response never exposes the score"

        conviction = body["conviction"]
        assert conviction, "seed produced no conviction line at all"
        # The band phrase is present AND the three non-ICP parts survived.
        from apps.api.services.icp_fit import VERDICT_BANDS

        assert any(band in conviction for band in VERDICT_BANDS), conviction
        assert "at Acme" in conviction
        assert "returned 2×" in conviction
        assert "viewed your pricing page" in conviction

    async def test_list_endpoint_still_200(
        self, test_client, test_db, monkeypatch, owned_site
    ):
        """AC-9. `icp_fit` is on VisitorDetailOut only; the list select must be
        unaffected by the schema change."""
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

        token, site_id = owned_site
        _enable(monkeypatch, True)
        await _seed_events(test_db, site_id, "v-list")
        await _seed_enrichment(test_db, site_id, "v-list")
        await aggregate_visitors_for_site(test_db, site_id, since=None)

        resp = await test_client.get(
            f"/api/v1/visitors/{site_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        rows = resp.json()["visitors"]
        assert rows
        # Detail-only by design — the list row must NOT carry the score, and its
        # conviction string must therefore carry no band phrase.
        from apps.api.services.icp_fit import VERDICT_BANDS

        for row in rows:
            assert "icp_fit" not in row
            if row.get("conviction"):
                assert not any(band in row["conviction"] for band in VERDICT_BANDS)
