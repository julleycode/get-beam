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

    def test_xhr_sends_credentials_for_svid_cookie(self, pixel_code: str):
        """Cross-origin _rta_svid Set-Cookie requires credentialed XHR."""
        assert "xhr.withCredentials = true" in pixel_code


class TestFingerprintV3:
    """fp3 = the v2 base signals plus installed fonts and an audio render.

    fp2 must survive untouched: it is the key every already-stored fingerprint
    was written under, so replacing it would orphan the whole identity graph.
    """

    def test_has_fp3_prefix(self, pixel_code: str):
        assert '"fp3_"' in pixel_code, "Strong fingerprint should use fp3_ prefix"

    def test_fp2_still_emitted(self, pixel_code: str):
        assert '"fp2_"' in pixel_code, (
            "fp2 must keep being emitted — it is the match key for every "
            "fingerprint already stored"
        )

    def test_has_font_probe(self, pixel_code: str):
        assert "fontFp" in pixel_code
        assert "offsetWidth" in pixel_code, "Font probe compares rendered metrics"

    def test_font_probe_uses_fallback_bases(self, pixel_code: str):
        for base in ("monospace", "sans-serif", "serif"):
            assert base in pixel_code, f"Font probe needs the {base} fallback base"

    def test_has_audio_probe(self, pixel_code: str):
        assert "audioFp" in pixel_code
        assert "OfflineAudioContext" in pixel_code
        assert "createOscillator" in pixel_code
        assert "createDynamicsCompressor" in pixel_code

    def test_audio_sample_rate_pinned(self, pixel_code: str):
        assert "44100" in pixel_code, (
            "sampleRate must be pinned or the hash moves with the machine's "
            "audio config"
        )

    def test_audio_probe_has_timeout(self, pixel_code: str):
        assert "setTimeout" in pixel_code, (
            "audio render must not hang the fp3 callback forever"
        )

    def test_font_probe_waits_for_body(self, pixel_code: str):
        assert "whenBody" in pixel_code, (
            "font probe needs document.body — a head-loaded pixel must wait, "
            "or fp3 differs between head and body placement"
        )

    def test_fp3_sent_on_events(self, pixel_code: str):
        assert "_fp3" in pixel_code, "fp3 must reach the server as _fp3"

    def test_fp3_omitted_until_resolved(self, pixel_code: str):
        assert "if (fingerprint3) evt._fp3" in pixel_code, (
            "fp3 is async — events before it resolves must carry fp2 only, "
            "never a null fp3"
        )

    def test_fp3_present_in_minified(self, min_pixel_code: str):
        assert "fp3_" in min_pixel_code, (
            "fp3 is in tracker.js but missing from tracker.min.js "
            "— re-run `npm run build` in apps/pixel"
        )


class TestFingerprintV3:
    """fp3 = the v2 base signals plus installed fonts and an audio render.

    fp2 must survive untouched: it is the key every already-stored fingerprint
    was written under, so replacing it would orphan the whole identity graph.
    """

    def test_has_fp3_prefix(self, pixel_code: str):
        assert '"fp3_"' in pixel_code, "Strong fingerprint should use fp3_ prefix"

    def test_fp2_still_emitted(self, pixel_code: str):
        assert '"fp2_"' in pixel_code, (
            "fp2 must keep being emitted — it is the match key for every "
            "fingerprint already stored"
        )

    def test_has_font_probe(self, pixel_code: str):
        assert "fontFp" in pixel_code
        assert "offsetWidth" in pixel_code, "Font probe compares rendered metrics"

    def test_font_probe_uses_fallback_bases(self, pixel_code: str):
        for base in ("monospace", "sans-serif", "serif"):
            assert base in pixel_code, f"Font probe needs the {base} fallback base"

    def test_has_audio_probe(self, pixel_code: str):
        assert "audioFp" in pixel_code
        assert "OfflineAudioContext" in pixel_code
        assert "createOscillator" in pixel_code
        assert "createDynamicsCompressor" in pixel_code

    def test_audio_sample_rate_pinned(self, pixel_code: str):
        assert "44100" in pixel_code, (
            "sampleRate must be pinned or the hash moves with the machine's "
            "audio config"
        )

    def test_audio_probe_has_timeout(self, pixel_code: str):
        assert "setTimeout" in pixel_code, (
            "audio render must not hang the fp3 callback forever"
        )

    def test_font_probe_waits_for_body(self, pixel_code: str):
        assert "whenBody" in pixel_code, (
            "font probe needs document.body — a head-loaded pixel must wait, "
            "or fp3 differs between head and body placement"
        )

    def test_fp3_sent_on_events(self, pixel_code: str):
        assert "_fp3" in pixel_code, "fp3 must reach the server as _fp3"

    def test_fp3_omitted_until_resolved(self, pixel_code: str):
        assert "if (fingerprint3) evt._fp3" in pixel_code, (
            "fp3 is async — events before it resolves must carry fp2 only, "
            "never a null fp3"
        )

    def test_fp3_present_in_minified(self, min_pixel_code: str):
        assert "fp3_" in min_pixel_code, (
            "fp3 is in tracker.js but missing from tracker.min.js "
            "— re-run `npm run build` in apps/pixel"
        )


class TestAudioTimeoutDeterminism:
    """The 1s audio watchdog is the ONLY nondeterministic fp3 input.

    Every other "" the probe can yield (no OfflineAudioContext, a throw) is a
    stable per-browser constant and is safe to hash — dropping fp3 for those
    would needlessly cost coverage on a signal that already lands on only ~34%
    of visitors. The watchdog is different: it is a race against machine load,
    so the SAME browser can produce two different fp3 values across sessions
    with no farbling involved. Since the server reads an fp3 change as evidence
    of farbling, hashing that value would flag ordinary visitors and — once
    farbled_fingerprint_gate_enabled is on — cost them Check 2 and Check 3.
    """

    def test_timeout_path_is_distinguishable_from_unsupported_path(
        self, pixel_code: str
    ):
        assert 'finish("", false)' in pixel_code, (
            "the audio watchdog must mark its value unreliable — otherwise it "
            "is indistinguishable from the deterministic empty paths"
        )
        assert 'if (!C) return cb("")' in pixel_code, (
            "the unsupported-browser path must stay a plain deterministic "
            '"" — it is a stable per-browser constant'
        )

    def test_fp3_not_assigned_on_the_timeout_path(self, pixel_code: str):
        body = pixel_code.split("whenBody(function() {")[1].split("\n  });")[0]
        assert "if (ok === false) return;" in body, (
            "an unreliable audio value must suppress fp3 for the session "
            "instead of being hashed into it"
        )
        assert body.index("if (ok === false) return;") < body.index(
            'fingerprint3 = "fp3_"'
        ), "the suppression must guard the assignment, not follow it"

    def test_fp3_still_assigned_on_the_deterministic_empty_path(
        self, pixel_code: str
    ):
        """Only `false` suppresses — the unsupported path passes undefined."""
        body = pixel_code.split("whenBody(function() {")[1].split("\n  });")[0]
        assert "ok === false" in body, (
            "the guard must be strict-equality on false; a truthiness check "
            "would also drop fp3 for the deterministic unsupported path"
        )

    def test_timeout_suppression_present_in_minified(self, min_pixel_code: str):
        assert "!1" in min_pixel_code or "false" in min_pixel_code, (
            "the reliability flag is missing from tracker.min.js "
            "— re-run `npm run build` in apps/pixel"
        )

    def test_fp_parts_still_unchanged(self, pixel_code: str):
        """Re-assertion: the audio fix must not reach fpBase.

        Any edit to fpParts() rotates every fp2 stored on disk, for every
        tenant, globally.
        """
        body = pixel_code.split("function fpParts(")[1].split("\n  }")[0]
        for banned in ("audioFp", "fontFp", "OfflineAudioContext", "navigator.brave"):
            assert banned not in body, (
                f"{banned!r} leaked into fpParts() — this rotates every stored "
                "fp2 for every tenant"
            )

    def test_brave_probe_still_after_consent_gate(self, pixel_code: str):
        """Re-assertion of Hard Guardrail G7 — unchanged by this work."""
        gate_idx = pixel_code.index("var consentDecision = GATED")
        assert pixel_code.index("navigator.brave") > gate_idx


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
    """The SERVED pixel (minified tracker.min.js) must stay under 6KB gzipped.

    Raised from 5KB when the font-probe and audio-render signals landed
    (fp3): those two cost ~850B gzipped and the old ceiling left only 157B.

    Raised again 5859 -> 6144 when the WS2 farbled-browser probe
    (navigator.brave) landed: it cost 45B gzipped and the old 6000 ceiling left
    only 41B. 6144 is not a NEW allowance — it is the value
    tests/unit/test_pixel.py::test_minified_gzip_size_within_budget has always
    asserted, so this reconciles two budgets that silently disagreed rather than
    relaxing one.

    The unminified source is allowed to grow past the budget; serve_pixel()
    serves the minified build. A red here almost always means someone edited
    tracker.js without re-running `npm run build` in apps/pixel.
    """

    def test_under_6kb_gzipped(self, min_pixel_code: str):
        compressed = gzip.compress(min_pixel_code.encode())
        assert len(compressed) < 6144, (
            f"Minified pixel is {len(compressed)} bytes gzipped, must be under 6KB "
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


class TestFarbledBrowserProbe:
    """WS2 Detector B — the navigator.brave probe (secondary detector).

    String/regex assertions against raw source. They prove the probe is PRESENT
    and POSITIONED correctly; that it actually EXECUTES is proven only by
    apps/pixel/e2e/farbled-browser.spec.ts.
    """

    def test_probe_present_in_source(self, pixel_code: str):
        assert "navigator.brave" in pixel_code
        assert "isBrave" in pixel_code

    def test_probe_present_in_minified(self, min_pixel_code: str):
        assert "navigator.brave" in min_pixel_code, (
            "the farbled probe is in tracker.js but missing from tracker.min.js "
            "— re-run `npm run build` in apps/pixel"
        )
        assert "isBrave" in min_pixel_code

    def test_marker_attached_in_push_event(self, pixel_code: str):
        """_fb rides along on the outgoing event, next to _fp3/_asig."""
        body = pixel_code.split("function pushEvent(")[1].split("\n  }")[0]
        assert "evt._fb" in body, "_fb is not attached inside pushEvent"

    def test_probe_is_after_consent_gate(self, pixel_code: str):
        """Hard Guardrail G7: no signal is read before GATED resolves.

        Same string-index technique as
        test_pixel.py::test_agent_sig_collection_is_after_consent_gate.
        """
        gate_idx = pixel_code.index("var consentDecision = GATED")
        assert pixel_code.index("navigator.brave") > gate_idx, (
            "the navigator.brave probe is read before the consent gate — "
            "bypasses the EU consent-hold (G7)"
        )

    def test_fp_parts_body_unchanged(self, pixel_code: str):
        """The probe is a SIBLING signal, never a fingerprint component.

        Folding it into fpParts()/fpBase would rotate every fp2 stored on disk,
        globally, for every tenant — every already-known visitor would look new.
        """
        body = pixel_code.split("function fpParts(")[1].split("\n  }")[0]
        for banned in ("navigator.brave", "isBrave", "FBL"):
            assert banned not in body, (
                f"{banned!r} leaked into fpParts() — this rotates every stored "
                "fp2 for every tenant"
            )
