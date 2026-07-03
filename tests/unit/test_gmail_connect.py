"""Unit tests for the Connect-Gmail send path (pure functions, no DB/network)."""

import base64
import email
import json

import pytest

from apps.api.services.email_providers import gmail


def _fake_id_token(email_addr: str) -> str:
    """Minimal unsigned JWT with an email claim (only the payload segment is read)."""
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"email": email_addr}).encode()
    ).decode().rstrip("=")
    return f"{header}.{payload}.sig"


def test_build_auth_url_requests_send_scope_and_offline(monkeypatch):
    monkeypatch.setattr(gmail.settings, "google_client_id", "cid")
    monkeypatch.setattr(gmail.settings, "google_redirect_uri", "https://api.example/cb")
    url = gmail.build_auth_url("state123")
    assert "gmail.send" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=state123" in url
    assert "client_id=cid" in url


def test_email_from_id_token_parses_claim():
    assert gmail._email_from_id_token(_fake_id_token("founder@acme.com")) == "founder@acme.com"


def test_email_from_id_token_handles_garbage():
    assert gmail._email_from_id_token(None) is None
    assert gmail._email_from_id_token("not-a-jwt") is None


def test_tokens_from_response_maps_fields_and_keeps_prev_refresh():
    data = {
        "access_token": "at1",
        "expires_in": 3600,
        "id_token": _fake_id_token("me@acme.com"),
        "scope": "openid email https://www.googleapis.com/auth/gmail.send",
    }
    # Refresh omitted on a refresh response → keep the prior one.
    tokens = gmail._tokens_from_response(data, prev_refresh="rt-old")
    assert tokens.access_token == "at1"
    assert tokens.refresh_token == "rt-old"
    assert tokens.email == "me@acme.com"
    assert tokens.expires_at is not None
    assert "https://www.googleapis.com/auth/gmail.send" in tokens.scopes


def test_tokens_from_response_uses_new_refresh_when_present():
    tokens = gmail._tokens_from_response(
        {"access_token": "at", "refresh_token": "rt-new"}, prev_refresh="rt-old"
    )
    assert tokens.refresh_token == "rt-new"


def test_build_raw_message_is_valid_mime_with_headers():
    raw = gmail._build_raw_message(
        from_email="me@acme.com",
        to_email="lead@corp.com",
        subject="Hi there",
        body_html="<p>Hello</p>",
        unsubscribe_url="https://api.example/unsubscribe?t=abc",
    )
    decoded = base64.urlsafe_b64decode(raw.encode())
    msg = email.message_from_bytes(decoded)
    assert msg["From"] == "me@acme.com"
    assert msg["To"] == "lead@corp.com"
    assert msg["Subject"] == "Hi there"
    assert msg["List-Unsubscribe"] == "<https://api.example/unsubscribe?t=abc>"
    # Body is base64 transfer-encoded; decode the payload to read the HTML.
    assert "Hello" in msg.get_payload(decode=True).decode()


def test_is_configured_reflects_settings(monkeypatch):
    monkeypatch.setattr(gmail.settings, "google_client_id", "")
    monkeypatch.setattr(gmail.settings, "google_client_secret", "")
    assert gmail.is_configured() is False
    monkeypatch.setattr(gmail.settings, "google_client_id", "cid")
    monkeypatch.setattr(gmail.settings, "google_client_secret", "secret")
    assert gmail.is_configured() is True
