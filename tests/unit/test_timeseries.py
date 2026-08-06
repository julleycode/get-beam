"""Unit tests for the timeseries gap-fill (pure — no DB)."""

from datetime import date

from apps.api.services.timeseries import build_series


def test_gap_fill_length_and_order() -> None:
    series = build_series({}, days=7, today=date(2026, 6, 29))
    assert len(series) == 7
    # Continuous, ascending, ending on `today`.
    assert series[0]["date"] == "2026-06-23"
    assert series[-1]["date"] == "2026-06-29"
    assert [p["date"] for p in series] == sorted(p["date"] for p in series)


def test_quiet_days_are_zero() -> None:
    series = build_series({}, days=3, today=date(2026, 6, 29))
    assert all(
        p["visitors"] == 0 and p["identified"] == 0 and p["high_intent"] == 0
        for p in series
    )


def test_known_day_populated() -> None:
    counts = {"2026-06-29": {"visitors": 10, "identified": 4, "high_intent": 2}}
    series = build_series(counts, days=3, today=date(2026, 6, 29))
    last = series[-1]
    assert last == {
        "date": "2026-06-29",
        "visitors": 10,
        "identified": 4,
        # Identity-honesty Phase 1 (B4): candidates get their own series key,
        # zero-filled when the day's counts don't carry one.
        "candidates": 0,
        "high_intent": 2,
    }
    # Earlier days untouched (zero-filled).
    assert series[0]["visitors"] == 0


def test_missing_metric_keys_default_zero() -> None:
    # A day present in counts but without all metrics must not KeyError.
    counts = {"2026-06-29": {"visitors": 5}}
    series = build_series(counts, days=1, today=date(2026, 6, 29))
    assert series[0] == {
        "date": "2026-06-29",
        "visitors": 5,
        "identified": 0,
        "candidates": 0,
        "high_intent": 0,
    }
