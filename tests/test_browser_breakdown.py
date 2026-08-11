"""Unit tests for browser-capture breakdown logic (pure — no DB required)."""

import pytest

from apps.api.services.browser_breakdown import (
    CHROMIUM_FAMILY,
    FARBLED_FAMILY,
    _coverage_status,
    classify_browser,
    compute_browser_breakdown,
)

_CHROME_UA = "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
_FIREFOX_UA = "Mozilla/5.0 (Windows) Gecko/20100101 Firefox/121.0"


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    """Returns canned rows for the two SELECTs `compute_browser_breakdown` runs,
    in order: latest-UA-per-visitor, then the per-visitor row."""

    def __init__(self, ua_rows, v_rows):
        self._queued = [ua_rows, v_rows]

    async def execute(self, _stmt):
        return _Result(self._queued.pop(0))


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


# ── Privacy opt-out visibility (WS1a) ────────────────────────────────────────


def _rows(*specs):
    """(visitor_id, identity_status, country_code, do_not_resolve, unstable)."""
    return [
        (vid, status, "US", optout, unstable)
        for vid, status, optout, unstable in specs
    ]


async def _run(ua_rows, v_rows):
    return await compute_browser_breakdown(_FakeSession(ua_rows, v_rows), "site_1")


def _browser(result, name):
    return next(b for b in result["browsers"] if b["browser"] == name)


@pytest.mark.asyncio
async def test_optout_counted_per_browser() -> None:
    out = await _run(
        [("v1", _FIREFOX_UA), ("v2", _FIREFOX_UA), ("v3", _CHROME_UA)],
        _rows(
            ("v1", "identified", True, False),
            ("v2", "anonymous", True, False),
            ("v3", "anonymous", False, False),
        ),
    )

    ff = _browser(out, "Firefox")
    assert ff["captured"] == 2
    assert ff["opted_out"] == 2
    assert ff["optout_rate"] == 1.0

    chrome = _browser(out, CHROMIUM_FAMILY)
    assert chrome["opted_out"] == 0
    assert chrome["optout_rate"] == 0.0

    assert out["privacy_optout"] == {"visitors": 3, "opted_out": 2, "rate": 0.6667}


@pytest.mark.asyncio
async def test_optout_rate_rounds_to_four_places() -> None:
    # 1/3 must round to the existing 4-dp convention, not float-dump.
    out = await _run(
        [(f"v{i}", _CHROME_UA) for i in range(3)],
        _rows(
            ("v0", "anonymous", True, False),
            ("v1", "anonymous", False, False),
            ("v2", "anonymous", False, False),
        ),
    )
    assert _browser(out, CHROMIUM_FAMILY)["optout_rate"] == 0.3333
    assert out["privacy_optout"]["rate"] == 0.3333


@pytest.mark.asyncio
async def test_no_visitors_does_not_divide_by_zero() -> None:
    out = await _run([], [])
    assert out["browsers"] == []
    assert out["privacy_optout"] == {"visitors": 0, "opted_out": 0, "rate": 0.0}


@pytest.mark.asyncio
async def test_farbled_relabel_only_fires_for_flagged_chrome() -> None:
    out = await _run(
        [("v1", _CHROME_UA), ("v2", _CHROME_UA), ("v3", _FIREFOX_UA)],
        _rows(
            ("v1", "anonymous", False, True),  # flagged → relabelled
            ("v2", "anonymous", False, False),  # plain Chrome
            ("v3", "anonymous", False, True),  # flagged, but not Chrome
        ),
    )
    names = {b["browser"] for b in out["browsers"]}
    assert FARBLED_FAMILY in names
    assert _browser(out, FARBLED_FAMILY)["captured"] == 1
    assert _browser(out, CHROMIUM_FAMILY)["captured"] == 1
    # A flagged Firefox stays Firefox — the label describes the observed
    # property on the Chromium bucket, it is not a vendor claim.
    assert _browser(out, "Firefox")["captured"] == 1


@pytest.mark.asyncio
async def test_chromium_bucket_string_is_stable() -> None:
    # The relabel compares against this exact string; pin it.
    assert classify_browser(_CHROME_UA) == CHROMIUM_FAMILY == "Chrome"
