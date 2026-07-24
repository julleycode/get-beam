"""AC13 — first-party-capture Phase 3: visitor_emails `source` enum validation.

The pixel emits a widening set of capture `source` labels (now incl.
mailto_click / url_param). SPEC AC13: every source maps to a known documented
value; an unrecognized value is rejected or NORMALIZED rather than stored as
free text.

Pure unit test (no DB) over ``normalize_source`` — this is the fast-lane gate
(``pytest tests/unit -k source_enum``). Integration-level source-label storage is
separately covered by tests/integration/test_events_ingest.py::TestEmailCaptureSource.

NOTE (deviation): plan Phase 3 item 6 suggested extending the integration
TestEmailCaptureSource class, but the Phase 3 Test Gate command targets the UNIT
lane (`tests/unit -k source_enum`). The validated behavior (normalization) is a
pure function, so it belongs in — and is proven by — this unit test.
"""
import pytest

from apps.api.models.visitor_email import VISITOR_EMAIL_SOURCES, normalize_source

# Every value any live write path emits — MUST all survive normalization
# unchanged (a value silently rewritten to "other" would be a data-loss bug and
# would break the source CHECK constraint on existing rows).
LIVE_EMITTED = [
    "form", "utm", "manual", "email_click", "login", "checkout",
    "newsletter", "input", "identify", "mailto_click", "url_param",
]


class TestSourceEnum:
    @pytest.mark.parametrize("value", LIVE_EMITTED)
    def test_source_enum_accepts_all_live_values(self, value):
        assert value in VISITOR_EMAIL_SOURCES, f"{value!r} missing from enum → data loss"
        assert normalize_source(value) == value

    def test_source_enum_normalizes_unknown_to_other(self):
        assert normalize_source("totally-made-up") == "other"
        assert normalize_source("'; DROP TABLE visitor_emails; --") == "other"

    def test_source_enum_defaults_blank_to_form(self):
        assert normalize_source(None) == "form"
        assert normalize_source("") == "form"
        assert normalize_source("   ") == "form"

    def test_source_enum_is_case_insensitive_and_trimmed(self):
        assert normalize_source("  MailTo_Click  ") == "mailto_click"
        assert normalize_source("URL_PARAM") == "url_param"

    def test_source_enum_caps_length_then_normalizes(self):
        # Over-long free text is capped to 20 then normalized to "other".
        assert normalize_source("x" * 50) == "other"

    def test_source_enum_other_is_a_member(self):
        # The fallback itself must be a valid stored value (CHECK superset).
        assert "other" in VISITOR_EMAIL_SOURCES
