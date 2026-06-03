"""Tests for the tracking pixel JavaScript (apps/pixel/src/tracker.js).

These tests verify the pixel code contains expected markers and does NOT
contain removed features (scroll, click, visibility tracking).
"""

import pathlib

import pytest

PIXEL_PATH = pathlib.Path(__file__).parent.parent.parent / "apps" / "pixel" / "src" / "tracker.js"


@pytest.fixture
def pixel_code() -> str:
    """Read the pixel JavaScript source."""
    assert PIXEL_PATH.exists(), f"Pixel file not found at {PIXEL_PATH}"
    return PIXEL_PATH.read_text()


class TestPixelRequiredFeatures:
    """Pixel should have these features present."""

    def test_has_bot_detection(self, pixel_code: str):
        assert "navigator.webdriver" in pixel_code

    def test_has_spa_tracking_pushstate(self, pixel_code: str):
        assert "pushState" in pixel_code

    def test_has_spa_tracking_replacestate(self, pixel_code: str):
        assert "replaceState" in pixel_code

    def test_has_popstate_listener(self, pixel_code: str):
        assert "popstate" in pixel_code

    def test_has_user_agent_collection(self, pixel_code: str):
        assert "user_agent" in pixel_code

    def test_has_page_path_collection(self, pixel_code: str):
        assert "page_path" in pixel_code

    def test_has_page_title_collection(self, pixel_code: str):
        assert "page_title" in pixel_code

    def test_has_sendbeacon(self, pixel_code: str):
        assert "sendBeacon" in pixel_code

    def test_has_visitor_id_cookie(self, pixel_code: str):
        assert "_rta_vid" in pixel_code

    def test_sends_pageview_event(self, pixel_code: str):
        assert '"pageview"' in pixel_code

    def test_has_site_id_attribute(self, pixel_code: str):
        assert "data-site" in pixel_code

    def test_has_utm_tracking(self, pixel_code: str):
        assert "utm_source" in pixel_code


class TestPixelRemovedFeatures:
    """These noisy features should have been removed."""

    def test_no_scroll_tracking(self, pixel_code: str):
        assert "getScrollPercent" not in pixel_code
        assert "scrollThresholds" not in pixel_code

    def test_no_click_tracking(self, pixel_code: str):
        assert "element_text" not in pixel_code
        assert "element_href" not in pixel_code

    def test_no_visibility_tracking(self, pixel_code: str):
        assert "visibilitychange" not in pixel_code

    def test_no_time_on_page_pings(self, pixel_code: str):
        # Should not have time_on_page event type in the pixel
        # (the schema still accepts it from old data, but pixel shouldn't send it)
        assert '"time_on_page"' not in pixel_code


class TestPixelSize:
    """Pixel should be small and efficient."""

    def test_under_8kb(self, pixel_code: str):
        # Bumped from 5KB to 8KB after adding form capture, fingerprint, and UTM identification
        assert len(pixel_code.encode()) < 8000, f"Pixel is {len(pixel_code.encode())} bytes, should be under 8KB"

    def test_is_iife(self, pixel_code: str):
        """Should be wrapped in an IIFE for isolation."""
        stripped = pixel_code.strip()
        assert stripped.startswith("(function()"), "Pixel should start with IIFE"
        assert stripped.endswith("})();"), "Pixel should end with IIFE invocation"
