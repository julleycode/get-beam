"""Sentry is a no-op without a DSN, and a dummy DSN captures a scrubbed event."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import sentry_sdk
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.sentry_init import bind_clerk_user, init_sentry, scrub_sentry_event

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
# Public example key. The recording transport never opens a socket.
DUMMY_DSN = "https://public@o0.ingest.sentry.io/0"


class RecordingTransport(sentry_sdk.transport.Transport):
    envelopes: list = []

    def __init__(self, options=None):
        super().__init__(options)
        type(self).envelopes = []

    def capture_envelope(self, envelope):
        type(self).envelopes.append(envelope)


def _event_blobs():
    events = []
    for envelope in RecordingTransport.envelopes:
        event = envelope.get_event()
        if event is not None:
            events.append(event)
    return events


@pytest.fixture
def sentry_disabled():
    yield
    os.environ["SENTRY_DSN"] = ""
    sentry_sdk.init(dsn="")
    RecordingTransport.envelopes = []


def test_api_boots_with_no_dsn():
    """Importing the FastAPI app with SENTRY_DSN unset must not enable Sentry."""
    env = os.environ.copy()
    env["SENTRY_DSN"] = ""
    env["APP_ENV"] = "test"
    env["PYTHONPATH"] = str(ROOT)
    code = (
        "import sentry_sdk\n"
        "from apps.api.sentry_init import init_sentry\n"
        "assert init_sentry('') is False\n"
        "assert sentry_sdk.is_initialized() is False\n"
        "import apps.api.main\n"
        "assert sentry_sdk.is_initialized() is False\n"
        "print('noop-ok')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    assert "noop-ok" in proc.stdout


def test_scrub_drops_auth_headers_cookies_and_email():
    event = {
        "request": {
            "headers": {
                "Authorization": "Bearer secret-token",
                "Cookie": "sid=secret-cookie",
                "User-Agent": "pytest",
            },
            "cookies": {"sid": "secret-cookie"},
            "data": {"email": "secret@example.com"},
        },
        "user": {
            "id": "user_abc",
            "email": "secret@example.com",
            "ip_address": "203.0.113.5",
        },
    }
    scrubbed = scrub_sentry_event(event)
    assert scrubbed["request"]["headers"] == {"User-Agent": "pytest"}
    assert "cookies" not in scrubbed["request"]
    assert "data" not in scrubbed["request"]
    assert scrubbed["user"] == {"id": "user_abc"}
    blob = json.dumps(scrubbed)
    assert "secret-token" not in blob
    assert "secret-cookie" not in blob
    assert "secret@example.com" not in blob


def test_bind_clerk_user_is_noop_when_sdk_is_off(sentry_disabled):
    bind_clerk_user("user_abc")


def test_dummy_dsn_captures_forced_error_without_pii(sentry_disabled):
    assert init_sentry(DUMMY_DSN, environment="test", transport=RecordingTransport)
    sentry_sdk.set_user({"id": "user_abc", "email": "secret@example.com"})
    try:
        raise RuntimeError("forced sentry test")
    except RuntimeError:
        sentry_sdk.capture_exception()
    sentry_sdk.flush(timeout=2)

    events = _event_blobs()
    assert events, "transport received no event"
    event = events[0]
    assert event["exception"]["values"][0]["value"] == "forced sentry test"
    assert event["user"] == {"id": "user_abc"}
    assert "email" not in event["user"]
    request = event.get("request") or {}
    headers = {str(k).lower(): v for k, v in (request.get("headers") or {}).items()}
    assert "authorization" not in headers
    assert "cookie" not in headers
    assert "cookies" not in request


def test_fastapi_error_captures_clerk_id_and_drops_auth(sentry_disabled):
    assert init_sentry(DUMMY_DSN, environment="test", transport=RecordingTransport)
    app = FastAPI()

    @app.get("/boom")
    def boom():
        bind_clerk_user("user_abc")
        raise RuntimeError("forced sentry test")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(
        "/boom",
        headers={
            "Authorization": "Bearer secret-token",
            "Cookie": "sid=secret-cookie",
        },
    )
    assert response.status_code == 500
    sentry_sdk.flush(timeout=2)

    events = _event_blobs()
    assert events, "FastAPI integration did not capture the error"
    blob = json.dumps(events)
    assert "forced sentry test" in blob
    assert "user_abc" in blob
    assert "secret-token" not in blob
    assert "secret-cookie" not in blob
    for event in events:
        user = event.get("user") or {}
        assert "email" not in user
        assert list(user.keys()) <= ["id"]
