"""Unit tests for detection_scanner — the service behind /sites/{id}/detection-preview.

The module was lost once (imported by sites.py but never committed → prod 500s),
so these tests also pin the public contract the frontend relies on:
each signal = {key, name, category, active, description}.
"""

import httpx
import pytest

from apps.api.services import detection_scanner
from apps.api.services.detection_scanner import (
    _signals_from_html,
    scan_detection_signals,
)

SITE_ID = "site_abc123"
SITE_URL = "https://example.com"

FULL_SNIPPET = (
    '<html><head><script async src="https://example.com/tracker.js" '
    f'data-site="{SITE_ID}" data-consent="eu" data-stack="1"></script>'
    "</head><body><form><input type='email'></form></body></html>"
)

MINIMAL_SNIPPET = (
    '<html><head><script src="https://api.getbeam.fyi/pixel/tracker.js" '
    f'data-site="{SITE_ID}"></script></head><body>hello</body></html>'
)


def _by_key(signals):
    return {s["key"]: s for s in signals}


# ─────────────────────────── contract shape ───────────────────────────


def test_signal_shape_matches_frontend_contract():
    signals = _signals_from_html(FULL_SNIPPET, SITE_ID, SITE_URL)
    assert signals, "must always return signals"
    for s in signals:
        assert set(s.keys()) == {"key", "name", "category", "active", "description"}
        assert isinstance(s["active"], bool)
    # onboarding UI groups by these categories
    assert {s["category"] for s in signals} == {
        "Tracking",
        "Identification",
        "Privacy",
    }


# ─────────────────────────── HTML derivation ───────────────────────────


def test_full_install_lights_everything():
    sig = _by_key(_signals_from_html(FULL_SNIPPET, SITE_ID, SITE_URL))
    assert all(s["active"] for s in sig.values()), sig


def test_minimal_install_core_on_options_off():
    sig = _by_key(_signals_from_html(MINIMAL_SNIPPET, SITE_ID, SITE_URL))
    # always-on with any correct install
    assert sig["pixel_installed"]["active"]
    assert sig["spa_tracking"]["active"]
    assert sig["persistent_id"]["active"]
    assert sig["device_fingerprint"]["active"]
    assert sig["gpc_respect"]["active"]
    # install-dependent options absent in minimal snippet
    assert not sig["async_loading"]["active"]
    assert not sig["consent_banner"]["active"]
    assert not sig["identity_stack"]["active"]
    assert not sig["first_party"]["active"]  # served from api.getbeam.fyi
    assert not sig["form_capture"]["active"]  # no <form> on page


def test_wrong_site_id_means_not_installed():
    sig = _by_key(_signals_from_html(FULL_SNIPPET, "site_OTHER", SITE_URL))
    assert not any(s["active"] for s in sig.values())


def test_no_pixel_at_all():
    sig = _by_key(_signals_from_html("<html><form></form></html>", SITE_ID, SITE_URL))
    assert not any(s["active"] for s in sig.values())


def test_site_id_via_query_param():
    html = f'<script src="https://example.com/tracker.js?site={SITE_ID}"></script>'
    sig = _by_key(_signals_from_html(html, SITE_ID, SITE_URL))
    assert sig["pixel_installed"]["active"]
    assert sig["first_party"]["active"]


def test_minified_tracker_and_www_host_equivalence():
    html = (
        '<script defer src="https://www.example.com/tracker.min.js" '
        f'data-site="{SITE_ID}"></script>'
    )
    sig = _by_key(_signals_from_html(html, SITE_ID, SITE_URL))
    assert sig["pixel_installed"]["active"]
    assert sig["async_loading"]["active"]  # defer counts as non-blocking
    assert sig["first_party"]["active"]  # www. stripped both sides


def test_consent_off_is_not_active():
    html = (
        '<script src="https://example.com/tracker.js" '
        f'data-site="{SITE_ID}" data-consent="off"></script>'
    )
    sig = _by_key(_signals_from_html(html, SITE_ID, SITE_URL))
    assert not sig["consent_banner"]["active"]


# ─────────────────────────── fetch behavior ───────────────────────────


@pytest.mark.asyncio
async def test_ssrf_blocked_url_returns_all_inactive_without_fetch(monkeypatch):
    calls: list = []

    async def _track_get(self, *args, **kwargs):
        calls.append(args)
        raise httpx.ConnectError("must not be reached in test")

    monkeypatch.setattr(httpx.AsyncClient, "get", _track_get)
    signals = await scan_detection_signals("http://169.254.169.254/", SITE_ID)
    assert calls == []  # guard refused before any outbound GET
    assert len(signals) > 0
    assert not any(s["active"] for s in signals)


@pytest.mark.asyncio
async def test_fetch_error_returns_all_inactive(monkeypatch):
    async def _yes(url: str) -> bool:
        return True

    async def _boom(client, url, **kwargs):
        raise httpx.TimeoutException("slow site")

    monkeypatch.setattr(detection_scanner, "is_safe_public_url", _yes)
    monkeypatch.setattr(detection_scanner, "safe_get", _boom)
    signals = await scan_detection_signals("https://example.com", SITE_ID)
    assert len(signals) > 0
    assert not any(s["active"] for s in signals)


@pytest.mark.asyncio
async def test_successful_scan_end_to_end(monkeypatch):
    async def _yes(url: str) -> bool:
        return True

    async def _fake_get(client, url, **kwargs):
        return httpx.Response(200, text=FULL_SNIPPET, request=httpx.Request("GET", url))

    monkeypatch.setattr(detection_scanner, "is_safe_public_url", _yes)
    monkeypatch.setattr(detection_scanner, "safe_get", _fake_get)
    signals = await scan_detection_signals("example.com", SITE_ID)  # scheme added
    assert all(s["active"] for s in signals)
