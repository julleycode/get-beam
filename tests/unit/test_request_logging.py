"""Unit tests for the admin request/response log — redaction + logging policy.

Pure-function coverage only: no DB, no ASGI scope. The two modules under test
(``log_redaction``, ``request_logger``) are deliberately structured so the policy
is testable without either, matching the shape of ``test_intent_score`` and
``cadence_bot_flag``'s pure-function tests.
"""

import json

import pytest

from apps.api.services import log_redaction as lr
from apps.api.services import request_logger as rl


# ── Redaction: emails ──


def test_mask_email_keeps_domain_and_first_char():
    assert lr.mask_email("bob@acme.com") == "b***@acme.com"


def test_mask_email_without_domain_is_fully_redacted():
    assert lr.mask_email("not-an-email") == lr.REDACTED


def test_mask_email_empty_local_part():
    assert lr.mask_email("@acme.com") == "***@acme.com"


def test_email_masked_anywhere_in_a_string():
    out = lr.redact("contact us at sales@acme.com or ops@beam.fyi")
    assert "sales@acme.com" not in out
    assert "s***@acme.com" in out
    assert "o***@beam.fyi" in out


def test_two_senders_same_domain_stay_distinguishable():
    """The surviving first char is what lets an operator correlate two rows."""
    assert lr.redact("alice@acme.com") != lr.redact("bob@acme.com")


# ── Redaction: credential-shaped keys ──


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "Password",
        "api_key",
        "apiKey",
        "X-Api-Key",
        "authorization",
        "session_token",
        "client_secret",
        "cvv",
    ],
)
def test_sensitive_keys_are_redacted_regardless_of_value(key):
    out = lr.redact({key: "some-plain-value"})
    assert out[key] == lr.REDACTED


def test_non_sensitive_keys_survive():
    out = lr.redact({"site_id": "beam_x", "count": 3, "ok": True, "none": None})
    assert out == {"site_id": "beam_x", "count": 3, "ok": True, "none": None}


def test_redaction_is_recursive_through_dicts_and_lists():
    payload = {
        "events": [
            {"email": "a@b.com", "token": "abc"},
            {"email": "c@d.com", "path": "/pricing"},
        ]
    }
    out = lr.redact(payload)
    assert out["events"][0]["email"] == "a***@b.com"
    assert out["events"][0]["token"] == lr.REDACTED
    assert out["events"][1]["path"] == "/pricing"


def test_redact_does_not_mutate_input():
    payload = {"email": "a@b.com", "password": "x"}
    original = json.dumps(payload, sort_keys=True)
    lr.redact(payload)
    assert json.dumps(payload, sort_keys=True) == original


def test_depth_bound_stops_runaway_nesting():
    deep: dict = {"k": "leaf@x.com"}
    for _ in range(30):
        deep = {"k": deep}
    out = lr.redact(deep)
    # Walk down until we hit the guard marker; it must appear before we exhaust.
    node = out
    for _ in range(40):
        if node == lr.REDACTED:
            break
        node = node["k"] if isinstance(node, dict) else node
    assert node == lr.REDACTED


def test_width_bound_truncates_wide_dicts():
    wide = {f"k{i}": i for i in range(600)}
    out = lr.redact(wide)
    assert "__truncated__" in out


def test_long_strings_are_truncated():
    out = lr.redact("x" * 5000)
    assert out.endswith(lr.TRUNCATED_SUFFIX)


def test_redact_headers_masks_authorization_and_cookie():
    out = lr.redact_headers(
        {"Authorization": "Bearer abc", "Cookie": "sid=1", "User-Agent": "curl/8"}
    )
    assert out["Authorization"] == lr.REDACTED
    assert out["Cookie"] == lr.REDACTED
    assert out["User-Agent"] == "curl/8"


# ── Policy: classify ──


def test_explicit_reason_wins_over_status():
    """A bot drop returns 204 — only the explicit marker can surface it."""
    assert rl.classify(204, explicit_reason="bot_drop") == "bot_drop"


def test_5xx_is_exception():
    assert rl.classify(500) == rl.REASON_EXCEPTION


def test_429_is_rate_limited_not_generic_http_error():
    assert rl.classify(429) == rl.REASON_RATE_LIMITED


def test_4xx_is_http_error():
    assert rl.classify(404) == rl.REASON_HTTP_ERROR
    assert rl.classify(413) == rl.REASON_HTTP_ERROR


def test_success_is_not_logged_at_default_sample_rate():
    """Default request_log_sample_rate is 0.0 — clean traffic writes nothing."""
    assert rl.classify(200, sample_roll=0.0) is None
    assert rl.classify(204, sample_roll=0.99) is None


def test_success_is_sampled_when_rate_raised(monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "request_log_sample_rate", 0.5)
    assert rl.classify(200, sample_roll=0.1) == rl.REASON_SAMPLED
    assert rl.classify(200, sample_roll=0.9) is None


def test_should_log_returns_none_when_flag_off(monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "request_log_enabled", False)
    assert rl.should_log(500, "/api/v1/anything") is None


def test_should_log_skips_excluded_paths(monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "request_log_enabled", True)
    assert rl.should_log(500, "/health") is None
    assert rl.should_log(500, "/api/v1/admin/request-logs") is None
    assert rl.should_log(500, "/api/v1/events/ingest") == rl.REASON_EXCEPTION


def test_viewer_does_not_log_its_own_reads(monkeypatch):
    """Regression guard: the log endpoint reading logs must not create logs.

    Covers the SUB-routes too — exact matching would have excluded the list
    endpoint while still capturing /stats and /{log_id}, so browsing the viewer
    would generate the rows being browsed.
    """
    from apps.api.config import settings

    monkeypatch.setattr(settings, "request_log_enabled", True)
    assert rl.is_excluded("/api/v1/admin/request-logs")
    assert rl.is_excluded("/api/v1/admin/request-logs/stats")
    assert rl.is_excluded("/api/v1/admin/request-logs/abc-123")
    assert rl.should_log(500, "/api/v1/admin/request-logs/stats") is None
    # A different admin router must NOT be swept up by the prefix.
    assert not rl.is_excluded("/api/v1/admin/other-tool")


# ── Policy: decode_body ──


def test_decode_json_body_is_redacted():
    body, truncated = rl.decode_body(b'{"email":"a@b.com"}', 1000)
    assert body == {"email": "a***@b.com"}
    assert truncated is False


def test_decode_non_json_body_is_kept_as_raw():
    body, truncated = rl.decode_body(b"site_id=x&email=a@b.com", 1000)
    assert "__raw__" in body
    assert "a***@b.com" in body["__raw__"]
    assert truncated is False


def test_decode_oversized_body_is_truncated_and_flagged():
    raw = json.dumps({"k": "v" * 500}).encode()
    body, truncated = rl.decode_body(raw, 50)
    assert truncated is True
    assert "__raw__" in body


def test_decode_empty_body_is_none():
    assert rl.decode_body(b"", 100) == (None, False)
    assert rl.decode_body(None, 100) == (None, False)


def test_decode_scalar_json_is_wrapped_for_uniform_column_shape():
    body, _ = rl.decode_body(b"42", 100)
    assert body == {"__raw__": 42}


def test_decode_json_array_stays_an_array():
    body, _ = rl.decode_body(b'[{"email":"a@b.com"}]', 1000)
    assert isinstance(body, list)
    assert body[0]["email"] == "a***@b.com"


def test_decode_undecodable_bytes_does_not_raise():
    body, _ = rl.decode_body(b"\xff\xfe\x00binary", 100)
    assert "__raw__" in body
