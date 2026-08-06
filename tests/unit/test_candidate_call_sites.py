"""B4/B6: every reconciled `identity_status == "identified"` call site.

SPEC AC8 requires each site to handle the new candidate tier EXPLICITLY — never
silently folded into the "Identified" total, never silently dropped. These tests
pin the documented decision at each of the four real sites so a future edit
can't quietly re-absorb candidates into a number the owner reads as "confirmed".

Documented decision (identical at all four): candidates get their OWN count;
`identified` keeps meaning CONFIRMED only.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import apps.api.main  # noqa: F401  (registers ORM mappers)
from apps.api.routers.visitors_helpers import _compute_visitor_stat_counts
from apps.api.schemas.visitors import VisitorStatsResponse
from apps.api.services.kpi import compute_kpis
from apps.api.services.timeseries import build_series, compute_timeseries

pytestmark = pytest.mark.unit


def _counting_db(values: list[int]) -> AsyncMock:
    """db whose successive `.execute(...).scalar()` calls yield `values`."""
    db = AsyncMock()
    results = []
    for v in values:
        r = MagicMock()
        r.scalar.return_value = v
        results.append(r)
    db.execute = AsyncMock(side_effect=results)
    return db


class TestKpiFunnel:
    """Site 1 — apps/api/services/kpi.py."""

    @pytest.mark.asyncio
    async def test_candidates_reported_separately_from_identified(self):
        # Order of counts in compute_kpis: visitors, identified, candidates,
        # enriched, high_intent, acted, acted_high, sent.
        db = _counting_db([100, 10, 7, 8, 4, 3, 2, 1])

        kpis = await compute_kpis(db, "test-site", days=30)

        assert kpis["identified"] == 10, "identified must stay CONFIRMED-only"
        assert kpis["candidates"] == 7, "candidates must be their own number"
        # The two must not be conflated in either direction.
        assert kpis["identified"] != kpis["identified"] + kpis["candidates"]


class TestTimeseries:
    """Site 2 — apps/api/services/timeseries.py."""

    def test_build_series_emits_a_candidates_point(self):
        series = build_series(
            {"2026-08-04": {"visitors": 9, "identified": 2, "candidates": 3,
                            "high_intent": 1}},
            days=1,
            today=__import__("datetime").date(2026, 8, 4),
        )
        assert series[0]["identified"] == 2
        assert series[0]["candidates"] == 3

    def test_quiet_days_gap_fill_candidates_to_zero(self):
        series = build_series({}, days=2, today=__import__("datetime").date(2026, 8, 4))
        assert all(p["candidates"] == 0 for p in series)

    @pytest.mark.asyncio
    async def test_query_counts_candidate_rows_separately(self):
        # Must match compute_timeseries' own reference date (naive UTC today),
        # otherwise the gap-filled series never contains this row.
        today = __import__("datetime").datetime.utcnow().date().isoformat()
        rows = [SimpleNamespace(date=today, visitors=9, identified=2,
                                candidates=3, high_intent=1)]
        result = MagicMock()
        result.all.return_value = rows
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        out = await compute_timeseries(db, "test-site", days=1)
        point = next(p for p in out["series"] if p["date"] == today)

        assert point["identified"] == 2
        assert point["candidates"] == 3

    @pytest.mark.asyncio
    async def test_sql_has_a_distinct_candidate_case_expression(self):
        """The split must happen in SQL, not be inferable in Python."""
        result = MagicMock()
        result.all.return_value = []
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        await compute_timeseries(db, "test-site", days=1)

        sql = str(
            db.execute.await_args_list[0]
            .args[0]
            .compile(compile_kwargs={"literal_binds": True})
        )
        assert "'candidate'" in sql
        assert "'identified'" in sql


class TestVisitorStatCounts:
    """Site 3 — apps/api/routers/visitors_helpers.py."""

    @pytest.mark.asyncio
    async def test_candidates_surfaced_in_the_per_site_stats_payload(self, monkeypatch):
        monkeypatch.setattr(
            "apps.api.routers.visitors_helpers.first_win_boost_site_ids",
            AsyncMock(return_value=[]),
        )
        row = SimpleNamespace(total=50, identified=5, candidates=4, enriched=3,
                              enriched_unsegmented=1, eligible_for_resolution=9)
        stats_result = MagicMock()
        stats_result.one.return_value = row
        enrich_result = MagicMock()
        enrich_result.scalar.return_value = 0
        site_result = MagicMock()
        site_result.scalar_one_or_none.return_value = "https://example.com"

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[site_result, stats_result, enrich_result])

        out = await _compute_visitor_stat_counts(db, "test-site")

        assert out["identified"] == 5
        assert out["candidates"] == 4


class TestDashboardStatsSchema:
    """Site 4 — apps/api/routers/dashboard.py (via its response schema).

    The dashboard aggregate adds a `candidates` label alongside `identified`;
    this pins the contract it fills, and that the field defaults safely to 0 for
    any existing constructor that predates it.
    """

    def test_schema_carries_candidates(self):
        resp = VisitorStatsResponse(
            total_visitors=10, identified=2, candidates=3, enriched=1,
            could_enrich_more=0, enriched_unsegmented=0, eligible_for_resolution=0,
            identify_used_today=0, identify_daily_limit=None, identify_is_byok=False,
        )
        assert resp.identified == 2
        assert resp.candidates == 3

    def test_candidates_defaults_to_zero_for_existing_callers(self):
        resp = VisitorStatsResponse(
            total_visitors=10, identified=2, enriched=1, could_enrich_more=0,
            enriched_unsegmented=0, eligible_for_resolution=0,
            identify_used_today=0, identify_daily_limit=None, identify_is_byok=False,
        )
        assert resp.candidates == 0
