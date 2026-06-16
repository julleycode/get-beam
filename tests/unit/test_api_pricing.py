"""Unit tests for the API cost estimate map (no DB, no network)."""

import pytest

from apps.api.services.api_pricing import price_for

pytestmark = pytest.mark.unit


def test_known_provider_success():
    assert price_for("pdl") == pytest.approx(0.01)
    assert price_for("rb2b") == pytest.approx(0.09)
    assert price_for("osint-industries") == pytest.approx(1.0)


def test_failure_is_free():
    # Most providers bill per match/credit, not per attempt.
    assert price_for("rb2b", success=False) == 0.0
    assert price_for("osint-industries", success=False) == 0.0


def test_units_multiply_base():
    assert price_for("osint-industries", units=2) == pytest.approx(2.0)
    # units only multiply when the base price is non-zero
    assert price_for("twitter", units=5) == 0.0


def test_unknown_provider_is_free():
    assert price_for("totally-made-up") == 0.0
