"""P4 (own-data): pixel deterministic email capture.

String-level assertions on the pixel source (same approach as test_optout.py) —
the capture must be OPTOUT-gated, deduped, and wired to submit + blur/change +
the window.beamIdentify hook, so logins/checkouts/newsletters that never fire a
classic <form> submit still feed an owned identity. Whitespace-insensitive so
the assertions survive pixel-size compaction.
"""
import pathlib

import pytest

PIXEL_PATH = pathlib.Path(__file__).parent.parent.parent / "apps" / "pixel" / "src" / "tracker.js"


def _nospace(s: str) -> str:
    return "".join(s.split())


@pytest.fixture
def pixel() -> str:
    assert PIXEL_PATH.exists(), f"Pixel not found at {PIXEL_PATH}"
    return PIXEL_PATH.read_text()


class TestDeterministicCapture:
    def test_has_capture_helper(self, pixel):
        assert "function captureEmail(" in pixel

    def test_capture_is_optout_gated(self, pixel):
        # OPTOUT must be checked inside captureEmail before anything is sent.
        body = pixel.split("function captureEmail(", 1)[1]
        head = body[: body.index("pushEvent")]
        assert "OPTOUT" in head

    def test_capture_is_deduped(self, pixel):
        assert "_sent[email]" in pixel

    def test_wired_to_submit(self, pixel):
        assert 'addEventListener("submit"' in pixel

    def test_wired_to_blur_and_change(self, pixel):
        ns = _nospace(pixel)
        # blur doesn't bubble → both registered in the capture phase (true).
        assert _nospace('addEventListener("blur", onFieldDone, true)') in ns
        assert _nospace('addEventListener("change", onFieldDone, true)') in ns

    def test_exposes_beamIdentify_hook(self, pixel):
        assert "window.beamIdentify=function" in _nospace(pixel)
        assert '"identify"' in pixel  # source tag for the hook

    def test_infers_richer_sources(self, pixel):
        for tag in ("login", "checkout", "newsletter"):
            assert tag in pixel

    def test_sends_source_field(self, pixel):
        body = pixel.split("function captureEmail(", 1)[1]
        evt = body[body.index("pushEvent") : body.index("flush()")]
        assert "form_email_capture" in evt
        assert "source" in evt
