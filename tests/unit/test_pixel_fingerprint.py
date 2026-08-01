"""Tests for Phase 2: upgraded fingerprint in tracker.js.

Verifies the pixel has v2 fingerprint (17 signals, 128-bit hash),
strictly opt-in identity-vendor stacking (default OFF, no hardcoded
vendor account ids), and stays under size limit.
"""

import gzip
import pathlib
import re

import pytest

PIXEL_DIR = pathlib.Path(__file__).parent.parent.parent / "apps" / "pixel" / "src"
PIXEL_PATH = PIXEL_DIR / "tracker.js"
MIN_PIXEL_PATH = PIXEL_DIR / "tracker.min.js"


@pytest.fixture
def pixel_code() -> str:
    assert PIXEL_PATH.exists(), f"Pixel not found at {PIXEL_PATH}"
    return PIXEL_PATH.read_text(encoding="utf-8")


@pytest.fixture
def min_pixel_code() -> str:
    assert MIN_PIXEL_PATH.exists(), (
        f"Minified pixel not found at {MIN_PIXEL_PATH} — run `npm run build` in apps/pixel"
    )
    return MIN_PIXEL_PATH.read_text(encoding="utf-8")


class TestFingerprintV2:
    """Phase 2: 17-signal, 128-bit fingerprint."""

    def test_has_fp2_prefix(self, pixel_code: str):
        assert '"fp2_"' in pixel_code, "Fingerprint should use fp2_ prefix"

    def test_has_hash128_function(self, pixel_code: str):
        assert "hash128" in pixel_code, "Should have 128-bit hash function"

    def test_has_canvas_fingerprint(self, pixel_code: str):
        assert "canvasFp" in pixel_code, "Should collect canvas fingerprint"

    def test_has_webgl_fingerprint(self, pixel_code: str):
        assert "webglFp" in pixel_code, "Should collect WebGL fingerprint"

    def test_has_webgl_debug_renderer(self, pixel_code: str):
        assert "WEBGL_debug_renderer_info" in pixel_code

    def test_has_device_memory_signal(self, pixel_code: str):
        assert "deviceMemory" in pixel_code

    def test_has_max_touch_points(self, pixel_code: str):
        assert "maxTouchPoints" in pixel_code

    def test_has_hardware_concurrency(self, pixel_code: str):
        assert "hardwareConcurrency" in pixel_code

    def test_has_do_not_track(self, pixel_code: str):
        assert "doNotTrack" in pixel_code

    def test_has_color_depth(self, pixel_code: str):
        assert "colorDepth" in pixel_code

    def test_has_device_pixel_ratio(self, pixel_code: str):
        assert "devicePixelRatio" in pixel_code

    def test_has_timezone_signal(self, pixel_code: str):
        assert "DateTimeFormat" in pixel_code

    def test_has_connection_type(self, pixel_code: str):
        assert "effectiveType" in pixel_code

    def test_has_pdf_viewer(self, pixel_code: str):
        assert "pdfViewerEnabled" in pixel_code

    def test_has_math_tan_signal(self, pixel_code: str):
        assert "Math.tan" in pixel_code

    def test_four_lane_fnv_hash(self, pixel_code: str):
        assert "0x811c9dc5" in pixel_code, "FNV-1a offset basis lane 1"
        assert "0x01000193" in pixel_code, "FNV-1a prime lane 1"
        assert "Math.imul" in pixel_code, "Should use Math.imul for proper 32-bit multiplication"

    def test_hash_produces_base36(self, pixel_code: str):
        assert "toString(36)" in pixel_code


class TestIdentityGraphStacking:
    """Identity-vendor stacking is STRICTLY OPT-IN (default OFF).

    Third-party scripts load only when the snippet sets data-stack="1" and
    supplies per-vendor ids via data-stack-<vendor> attributes. No vendor
    account id may ship inside the tracker source.
    """

    def test_stacking_gated_behind_opt_in_flag(self, pixel_code: str):
        assert 'getAttribute("data-stack")' in pixel_code, (
            "Stacking must be gated behind the data-stack opt-in attribute"
        )

    def test_vendor_ids_come_from_per_vendor_attrs(self, pixel_code: str):
        assert '"data-stack-" + ' in pixel_code, (
            "Vendor ids must be read from data-stack-<vendor> attributes"
        )

    def test_no_default_provider_list(self, pixel_code: str):
        assert "_DP" not in pixel_code, "Default-on provider array must not exist"
        assert "data-identity-providers" not in pixel_code, (
            "Legacy JSON provider attr was replaced by data-stack-<vendor> attrs"
        )

    def test_no_hardcoded_vendor_account_id(self, pixel_code: str):
        assert "95247db8-8d49-4213-8ea7-ee0a6dd0ae78" not in pixel_code
        uuid_literal = re.compile(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
        )
        assert not uuid_literal.search(pixel_code), (
            "No UUID-shaped account id may ship in the tracker source"
        )

    def test_has_leadpipe_provider(self, pixel_code: str):
        assert "leadpipe" in pixel_code

    def test_has_capturify_provider(self, pixel_code: str):
        assert "capturify" in pixel_code

    def test_has_fullcontact_provider(self, pixel_code: str):
        assert "fullcontact" in pixel_code

    def test_has_customers_ai_provider(self, pixel_code: str):
        assert "customers-ai" in pixel_code

    def test_leadpipe_url_builder(self, pixel_code: str):
        assert "aws53.cloud" in pixel_code

    def test_capturify_url_builder(self, pixel_code: str):
        assert "capturify.io" in pixel_code

    def test_fullcontact_url_builder(self, pixel_code: str):
        assert "fullcontact.com" in pixel_code

    def test_customers_ai_url_builder(self, pixel_code: str):
        assert "customers.ai" in pixel_code


class TestPixelSizeLimit:
    """The SERVED pixel (minified tracker.min.js) must stay under 5KB gzipped.

    The unminified source is allowed to grow past the budget; serve_pixel()
    serves the minified build. A red here almost always means someone edited
    tracker.js without re-running `npm run build` in apps/pixel.
    """

    def test_under_5kb_gzipped(self, min_pixel_code: str):
        compressed = gzip.compress(min_pixel_code.encode())
        assert len(compressed) < 5000, (
            f"Minified pixel is {len(compressed)} bytes gzipped, must be under 5KB "
            "— re-run `npm run build` in apps/pixel"
        )

    def test_under_16kb_raw(self, min_pixel_code: str):
        # Raw cap is a sanity guard; the binding budget is 5KB gzipped above.
        assert len(min_pixel_code.encode()) < 16000, (
            f"Minified pixel is {len(min_pixel_code.encode())} bytes raw, should be under 16KB"
        )

    def test_minified_is_fresh(self, pixel_code: str, min_pixel_code: str):
        """Guard against a stale build: consent + core markers that survive
        minification (string literals + global props) must be present in the
        minified artifact whenever they're in source."""
        for marker in ('data-consent', 'beamConsent', '_rta_c', '"pageview"', 'beamIdentify'):
            if marker in pixel_code:
                assert marker in min_pixel_code, (
                    f"{marker!r} is in tracker.js but missing from tracker.min.js "
                    "— re-run `npm run build` in apps/pixel"
                )
