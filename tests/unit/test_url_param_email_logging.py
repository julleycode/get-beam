"""AC4 (no-plaintext-in-logs) — first-party-capture Phase 1.

The URL-param / mailto / value-based capture paths all land in the same
``form_email_capture`` branch of ``_process_signal_events`` (apps/api/routers/
events.py). SPEC constraint: structlog lines touching a captured email must log
only the domain (``email_domain=``), never the full ``local@domain`` address or
the raw URL-param plaintext.

This is a source-discipline unit test (no DB) mirroring the existing
``tests/unit/test_pixel_capture.py`` string-assertion approach: it proves every
logger call in the email-capture region emits ``email_domain=...`` and never
passes a full-email-bearing variable (``raw_email`` / ``decoded_email`` /
``event.email``) as a logged value. Named so ``pytest -k email_domain_logging``
selects it (Phase 1 Test Gates).
"""
import pathlib
import re

import pytest

EVENTS_PATH = (
    pathlib.Path(__file__).parent.parent.parent / "apps" / "api" / "routers" / "events.py"
)


@pytest.fixture
def events_src() -> str:
    assert EVENTS_PATH.exists(), f"events.py not found at {EVENTS_PATH}"
    return EVENTS_PATH.read_text(encoding="utf-8")


def _logger_calls(src: str) -> list[str]:
    """Return the argument text of every logger.<level>(...) call, brace-matched."""
    calls: list[str] = []
    for m in re.finditer(r"logger\.\w+\(", src):
        start = m.end()
        depth = 1
        i = start
        while i < len(src) and depth:
            c = src[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            i += 1
        calls.append(src[start : i - 1])
    return calls


class TestEmailDomainLogging:
    def test_email_domain_logging_uses_domain_only(self, events_src):
        """Every log call that references a captured-email variable must reduce it
        to its domain via ``.split("@")[-1]`` — never log the whole address."""
        email_vars = ("raw_email", "decoded_email")
        for call in _logger_calls(events_src):
            for var in email_vars:
                # A bare "raw_email" / "decoded_email" reference in a log call is
                # only allowed as part of the domain split.
                for ref in re.finditer(re.escape(var), call):
                    tail = call[ref.start() : ref.start() + len(var) + 12]
                    assert '.split("@")' in tail or ".split('@')" in tail, (
                        f"logger call leaks full email via {var!r}: {call.strip()[:120]}"
                    )

    def test_email_domain_logging_no_raw_event_email_logged(self, events_src):
        """The raw ``event.email`` field must never be handed to a logger call."""
        for call in _logger_calls(events_src):
            assert "event.email" not in call, (
                f"logger call leaks raw event.email: {call.strip()[:120]}"
            )

    def test_email_domain_logging_pattern_present(self, events_src):
        """Sanity: the domain-only logging convention is actually in use (guards
        against the test silently passing on a refactor that removed logging)."""
        assert 'email_domain=raw_email.split("@")[-1]' in events_src
        assert 'email_domain=decoded_email.split("@")[-1]' in events_src
