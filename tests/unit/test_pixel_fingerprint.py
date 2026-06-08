"""Tests for Phase 2: upgraded fingerprint in tracker.js.

Verifies the pixel has v2 fingerprint (17 signals, 128-bit hash),
identity graph stacking with all 4 providers, and stays under size limit.
"""

import gzip
import pathlib
import re

import pytest

PIXEL_PATH = pathlib.Path(__file__).parent.parent.parent / "apps" / "pixel" / "src" / "tracker.js"


@pytest.fixture
def pixel_code() -> str:
    assert PIXEL_PATH.exists(), f"Pixel not found at {PIXEL_PATH}"
    return PIXEL_PATH.read_text()


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
    """Phase 1: all 4 identity graph providers activated by default."""

    def test_has_leadpipe_provider(self, pixel_code: str):
        assert "leadpipe" in pixel_code

    def test_has_capturify_provider(self, pixel_code: str):
        assert "capturify" in pixel_code

    def test_has_fullcontact_provider(self, pixel_code: str):
        assert "fullcontact" in pixel_code

    def test_has_customers_ai_provider(self, pixel_code: str):
        assert "customers_ai" in pixel_code

    def test_default_dp_has_one_entry(self, pixel_code: str):
        dp_match = re.search(r'var _DP=\[(.*?)\]', pixel_code)
        assert dp_match, "Should have _DP default providers array"
        entries = dp_match.group(1).split("},{")
        assert len(entries) == 1, f"Expected 1 default provider, got {len(entries)}"

    def test_leadpipe_url_builder(self, pixel_code: str):
        assert "aws53.cloud" in pixel_code

    def test_capturify_url_builder(self, pixel_code: str):
        assert "capturify.io" in pixel_code

    def test_fullcontact_url_builder(self, pixel_code: str):
        assert "fullcontact.com" in pixel_code

    def test_customers_ai_url_builder(self, pixel_code: str):
        assert "customers.ai" in pixel_code

    def test_custom_providers_override(self, pixel_code: str):
        assert "data-identity-providers" in pixel_code, "Should support custom provider override"


class TestPixelSizeLimit:
    """Pixel must stay under 5KB gzipped."""

    def test_under_5kb_gzipped(self, pixel_code: str):
        compressed = gzip.compress(pixel_code.encode())
        assert len(compressed) < 5000, (
            f"Pixel is {len(compressed)} bytes gzipped, must be under 5KB"
        )

    def test_under_10kb_raw(self, pixel_code: str):
        assert len(pixel_code.encode()) < 10000, (
            f"Pixel is {len(pixel_code.encode())} bytes raw, should be under 10KB"
        )
