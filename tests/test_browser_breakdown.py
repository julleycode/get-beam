"""Unit tests for browser-capture breakdown logic (pure — no DB required)."""

import pytest

from apps.api.services.browser_breakdown import _coverage_status, classify_browser


@pytest.mark.parametrize(
    "ua,expected",
    [
        # Pure mobile Safari
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 "
            "Safari/604.1",
            "Safari",
        ),
        # Desktop Chrome — UA also contains "Safari", must not misread
        (
            "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36",
            "Chrome",
        ),
        # iOS Chrome = brand Chrome (WebKit under the hood)
        (
            "Mozilla/5.0 (iPhone) AppleWebKit/605 CriOS/120 Mobile/15E148 Safari/604.1",
            "Chrome",
        ),
        # iOS Firefox
        ("Mozilla/5.0 (iPhone) AppleWebKit/605 FxiOS/120 Mobile Safari/604", "Firefox"),
        # Edge carries both Chrome and Safari tokens
        ("Mozilla/5.0 (Windows) AppleWebKit/537 Chrome/120 Safari/537 Edg/120.0", "Edge"),
        ("Mozilla/5.0 (Windows) Gecko/20100101 Firefox/121.0", "Firefox"),
        (
            "Mozilla/5.0 (Linux; Android) AppleWebKit/537 SamsungBrowser/23 "
            "Chrome/115 Safari/537",
            "Samsung Internet",
        ),
        ("Mozilla/5.0 (Windows) Chrome/120 Safari/537 OPR/106", "Opera"),
        ("", "Unknown"),
        ("some random bot/1.0", "Other"),
    ],
)
def test_classify_browser(ua: str, expected: str) -> None:
    assert classify_browser(ua) == expected


def test_classify_browser_chrome_not_mistaken_for_safari() -> None:
    # Every Chrome UA contains "Safari" — order must catch Chrome first.
    assert classify_browser("X Chrome/1 Safari/2") == "Chrome"
    assert classify_browser("X Version/16 Safari/604") == "Safari"


@pytest.mark.parametrize(
    "total,ratio,status",
    [
        (50, 0.2, "insufficient_data"),  # below MIN_SAMPLE
        (500, None, "insufficient_data"),  # no expected baseline
        (500, 0.30, "likely_blocked"),
        (500, 0.59, "likely_blocked"),
        (500, 0.60, "watch"),
        (500, 0.84, "watch"),
        (500, 0.85, "ok"),
        (500, 1.10, "ok"),
    ],
)
def test_coverage_status(total: int, ratio: float | None, status: str) -> None:
    assert _coverage_status(total, ratio)[0] == status
