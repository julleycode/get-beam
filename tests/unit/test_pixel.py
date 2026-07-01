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

    def test_click_tracking_bounded(self, pixel_code: str):
        # Click tracking is back (intent signal) but must stay bounded so a
        # click-happy page can't flood the batch payload.
        assert "element_text" in pixel_code
        assert "element_href" in pixel_code
        assert "clickCount >= 25" in pixel_code

    def test_has_visibility_tracking(self, pixel_code: str):
        assert "visibilitychange" in pixel_code

    def test_emits_engagement_signals(self, pixel_code: str):
        # Intent scoring needs scroll depth + time on page (+15 / +10 points);
        # without these emitters single-session visitors can never reach the
        # >=40 identity-resolution threshold.
        assert '"time_on_page"' in pixel_code
        assert '"scroll"' in pixel_code
        assert '"click"' in pixel_code


class TestPixelConsent:
    """EU-gated cookie consent (data-consent: off|eu|all|cmp)."""

    def test_reads_consent_attribute(self, pixel_code: str):
        assert 'getAttribute("data-consent")' in pixel_code

    def test_default_consent_off(self, pixel_code: str):
        # Absent attribute → "off" → today's behavior (backward compatible).
        assert '"data-consent") || "off"' in pixel_code

    def test_has_eu_timezone_detection(self, pixel_code: str):
        assert "isEU" in pixel_code
        assert '"Europe/"' in pixel_code

    def test_exposes_beam_consent_hook(self, pixel_code: str):
        # CMP mode: customer's consent tool calls window.beamConsent(granted).
        assert "window.beamConsent" in pixel_code

    def test_decline_reuses_optout(self, pixel_code: str):
        # Declined consent must flow through the existing OPTOUT → do_not_resolve
        # path rather than a parallel mechanism.
        assert "OPTOUT = true" in pixel_code

    def test_flush_gated_by_consent(self, pixel_code: str):
        assert "consentBlocked()" in pixel_code

    def test_consent_state_key(self, pixel_code: str):
        assert "_rta_c" in pixel_code


class TestPixelSize:
    """Pixel should be small and efficient."""

    def test_source_under_20kb(self, pixel_code: str):
        # Source raw grew past 16KB with the consent banner; this is only a
        # sanity guard. The binding budget applies to the SERVED (minified)
        # tracker.min.js at <5KB gzipped — see test_pixel_fingerprint.py.
        assert len(pixel_code.encode()) < 20000, f"Pixel source is {len(pixel_code.encode())} bytes, should be under 20KB"

    def test_is_iife(self, pixel_code: str):
        """Should be wrapped in an IIFE for isolation."""
        stripped = pixel_code.strip()
        assert stripped.startswith("(function()"), "Pixel should start with IIFE"
        assert stripped.endswith("})();"), "Pixel should end with IIFE invocation"
