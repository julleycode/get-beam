"""Unit tests for the resolution intent floor + first-win boost (no DB, no network).

Covers:
- RESOLUTION_MIN_INTENT is the resolution floor (20), decoupled from the
  "hot / high-intent" DISPLAY label (40) used by kpi/hot_alert/conviction/timeseries.
- ``resolution_intent_filter`` tiering: plain floor, all-US widening, and the
  first-win-boost widening that waives the floor entirely for listed sites.
- ``first_win_boost_site_ids``: zero-row sites are inside the window, sites at
  the threshold are out, and a non-positive setting disables the boost.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# Import the app so ALL mappers register before touching the ORM (same rationale
# as conftest.test_engine / test_resolution_sweep).
import apps.api.main  # noqa: F401
from apps.api.config import settings
from apps.api.models.visitor import RESOLUTION_MIN_INTENT, resolution_intent_filter
from apps.api.services import resolution_eligibility
from apps.api.services.resolution_eligibility import first_win_boost_site_ids


def _sql(expr) -> str:
    return str(expr.compile(compile_kwargs={"literal_binds": True}))


class TestResolutionFloor:
    def test_floor_is_twenty(self):
        """The resolution floor dropped 40 -> 20; the display label stays 40."""
        assert RESOLUTION_MIN_INTENT == 20

    def test_display_label_constants_untouched(self):
        """Guard: the hot/high-intent label must NOT be coupled to the floor."""
        from apps.api.services import conviction, kpi

        source = f"{kpi.__file__} {conviction.__file__}"
        assert "RESOLUTION_MIN_INTENT" not in open(kpi.__file__).read(), source
        assert "RESOLUTION_MIN_INTENT" not in open(conviction.__file__).read(), source


class TestResolutionIntentFilter:
    def test_empty_lists_is_floor_only(self):
        sql = _sql(resolution_intent_filter())
        assert "intent_score >= 20" in sql
        assert "site_id IN" not in sql

    def test_empty_tuples_match_no_args(self):
        assert _sql(resolution_intent_filter((), ())) == _sql(resolution_intent_filter())

    def test_all_us_site_widens_floor(self):
        sql = _sql(resolution_intent_filter(["site_us"]))
        assert "intent_score >= 20" in sql
        assert "'site_us'" in sql
        assert "US" in sql

    def test_no_floor_site_bypasses_intent_condition(self):
        """A boost site qualifies on site_id alone — no intent term gating it."""
        sql = _sql(resolution_intent_filter(no_floor_site_ids=["site_new"]))
        # The site_id membership is OR'd with the floor, so any visitor on
        # site_new matches regardless of intent_score.
        assert "site_id IN ('site_new')" in sql.replace('"', "")
        assert " OR " in sql.upper()
        assert "intent_score >= 20" in sql

    def test_both_lists_compose(self):
        sql = _sql(resolution_intent_filter(["site_us"], ["site_new"]))
        assert "'site_us'" in sql and "'site_new'" in sql
        assert "intent_score >= 20" in sql

    def test_falsy_ids_are_dropped(self):
        assert _sql(resolution_intent_filter([None, ""], ["", None])) == _sql(
            resolution_intent_filter()
        )


def _db_returning(counts: dict[str, int]):
    """AsyncSession stand-in whose execute() yields grouped (site_id, n) rows."""
    rows = [SimpleNamespace(site_id=sid, n=n) for sid, n in counts.items()]
    db = AsyncMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: rows))
    return db


class TestFirstWinBoostSiteIds:
    @pytest.mark.asyncio
    async def test_zero_row_site_is_inside_window(self, monkeypatch):
        """A site absent from the grouped result has 0 identified -> boosted."""
        monkeypatch.setattr(settings, "first_win_boost_count", 5)
        ids = await first_win_boost_site_ids(_db_returning({}), ["fresh_site"])
        assert ids == ["fresh_site"]

    @pytest.mark.asyncio
    async def test_site_at_threshold_is_excluded(self, monkeypatch):
        monkeypatch.setattr(settings, "first_win_boost_count", 5)
        db = _db_returning({"at_limit": 5, "over_limit": 9, "under_limit": 4})
        ids = await first_win_boost_site_ids(
            db, ["at_limit", "over_limit", "under_limit", "absent"]
        )
        assert ids == ["under_limit", "absent"]

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self, monkeypatch):
        monkeypatch.setattr(settings, "first_win_boost_count", 0)
        db = _db_returning({})
        assert await first_win_boost_site_ids(db, ["fresh_site"]) == []
        db.execute.assert_not_awaited()  # no query when the boost is off

    @pytest.mark.asyncio
    async def test_no_site_ids_returns_empty(self, monkeypatch):
        monkeypatch.setattr(settings, "first_win_boost_count", 5)
        db = _db_returning({})
        assert await first_win_boost_site_ids(db, []) == []
        assert await first_win_boost_site_ids(db, [None, ""]) == []
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_default_setting_is_five(self):
        assert resolution_eligibility.settings.first_win_boost_count == 5
