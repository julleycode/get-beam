"""Unit tests for traffic-fit logic (pure — no DB required)."""

import pytest

from apps.api.services.traffic_fit import (
    DEFAULT_US_MATCH,
    MIN_SAMPLE,
    _fit_estimate,
    _fit_verdict,
)


@pytest.mark.parametrize(
    "located,us_share,status",
    [
        (MIN_SAMPLE - 1, 1.0, "insufficient_data"),  # too few located visitors
        (0, 0.0, "insufficient_data"),
        (100, 0.50, "good_fit"),
        (100, 0.80, "good_fit"),
        (100, 0.49, "partial_fit"),
        (100, 0.20, "partial_fit"),
        (100, 0.19, "poor_fit"),
        (100, 0.0, "poor_fit"),
    ],
)
def test_fit_verdict(located: int, us_share: float, status: str) -> None:
    assert _fit_verdict(located, us_share)[0] == status


def test_fit_verdict_message_quotes_share() -> None:
    # The poor-fit message must surface the actual US % so the user sees why.
    _, msg = _fit_verdict(200, 0.05)
    assert "5%" in msg
    assert "US" in msg


def test_fit_estimate_us_heavy_measured() -> None:
    # 80 of 100 located are US; 60 of those identified → measured 75% match.
    est = _fit_estimate(located=100, us_count=80, identified_us=60)
    assert est["us_share"] == 0.8
    assert est["us_match_rate"] == 0.75
    # 0.8 US share × 0.75 measured match.
    assert est["identifiable_estimate"] == 0.6


def test_fit_estimate_vn_heavy_poor() -> None:
    # 5 of 100 located are US → tiny servable share, low estimate.
    est = _fit_estimate(located=100, us_count=5, identified_us=2)
    assert est["us_share"] == 0.05
    # < MIN_US_FOR_MEASURED US visitors → fall back to the conservative default.
    assert est["identifiable_estimate"] == round(0.05 * DEFAULT_US_MATCH, 4)


def test_fit_estimate_few_us_uses_default_not_measured() -> None:
    # Only 10 US visitors (< MIN_US_FOR_MEASURED) — don't trust the measured rate.
    est = _fit_estimate(located=100, us_count=10, identified_us=10)
    assert est["us_match_rate"] == 1.0  # reported for transparency…
    # …but the estimate uses the default floor, not the noisy 100%.
    assert est["identifiable_estimate"] == round(0.10 * DEFAULT_US_MATCH, 4)


def test_fit_estimate_empty_window() -> None:
    # No located visitors / no US visitors must not divide-by-zero.
    est = _fit_estimate(located=0, us_count=0, identified_us=0)
    assert est == {
        "us_share": 0.0,
        "us_match_rate": None,
        "identifiable_estimate": 0.0,
    }
