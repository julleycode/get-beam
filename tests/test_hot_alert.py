"""Unit tests for the hot-visitor alert gate (pure — no DB/Redis/email)."""

import pytest

from apps.api.services.hot_alert import HIGH_INTENT, should_alert


@pytest.mark.parametrize(
    "country,intent,enabled,expected",
    [
        ("US", 80, True, True),          # the happy path
        ("US", HIGH_INTENT, True, True),  # exactly at the bar
        ("us", 90, True, True),          # case-insensitive country
        ("US", HIGH_INTENT - 1, True, False),  # just below intent bar
        ("US", 95, False, False),        # toggle off
        ("VN", 95, True, False),         # non-US never pings
        (None, 95, True, False),         # missing geo
        ("US", None, True, False),       # missing intent
    ],
)
def test_should_alert(country, intent, enabled, expected) -> None:
    assert should_alert(country, intent, enabled) is expected
