"""SSRF guard tests for user-supplied outbound URLs (Phase 5).

Covers: is_safe_public_url rejection of internal targets, safe_get redirect
re-validation, and that detect_platform / verify_pixel refuse a blocked URL
WITHOUT making any outbound request.
"""

import httpx
import pytest

from apps.api.services import platform_detector, pixel_verifier
from apps.api.services.url_guard import is_safe_public_url, safe_get


# ──────────────────────── is_safe_public_url ────────────────────────

@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://127.0.0.1/",                          # loopback
        "http://10.0.0.1/",                           # private
        "http://192.168.1.1/",                        # private
        "http://172.16.0.1/",                         # private
        "http://[::1]/",                              # ipv6 loopback
        "http://localhost/",                          # resolves to loopback
        "ftp://example.com/",                         # non-http scheme
        "not-a-url",                                  # no host
    ],
)
async def test_blocks_unsafe(url):
    assert await is_safe_public_url(url) is False


@pytest.mark.parametrize("url", ["http://8.8.8.8/", "https://1.1.1.1/"])
async def test_allows_public_ip(url):
    assert await is_safe_public_url(url) is True


# ──────────────────────────── safe_get ──────────────────────────────

class _FakeResp:
    def __init__(self, status: int, location: str | None = None, url: str = "http://good.example/"):
        self.status_code = status
        self.headers = {"location": location} if location else {}
        self.url = httpx.URL(url)
        self.text = ""

    @property
    def is_redirect(self) -> bool:
        return self.status_code in (301, 302, 303, 307, 308) and "location" in self.headers


class _FakeClient:
    def __init__(self, responses: list[_FakeResp]):
        self._responses = list(responses)
        self.gets: list[str] = []

    async def get(self, url: str) -> _FakeResp:
        self.gets.append(url)
        return self._responses.pop(0)


async def test_safe_get_blocks_redirect_to_internal():
    client = _FakeClient([_FakeResp(302, location="http://169.254.169.254/")])
    with pytest.raises(httpx.RequestError):
        await safe_get(client, "http://good.example/")


async def test_safe_get_follows_public_redirect():
    client = _FakeClient([
        _FakeResp(302, location="http://8.8.8.8/", url="http://good.example/"),
        _FakeResp(200, url="http://8.8.8.8/"),
    ])
    resp = await safe_get(client, "http://good.example/")
    assert resp.status_code == 200
    assert client.gets == ["http://good.example/", "http://8.8.8.8/"]


# ─────────────── detect_platform / verify_pixel refuse blocked URL ───────────────

async def test_detect_platform_refuses_metadata_without_fetch(monkeypatch):
    calls: list = []

    async def _track_get(self, *args, **kwargs):
        calls.append(args)
        raise httpx.ConnectError("must not be reached in test")

    monkeypatch.setattr(httpx.AsyncClient, "get", _track_get)
    res = await platform_detector.detect_platform("http://169.254.169.254/latest/meta-data/")
    assert res["platform"] == "unknown"
    assert res["confidence"] == 0.0
    assert calls == []  # guard refused before any outbound GET


async def test_fetch_site_content_refuses_metadata_without_fetch(monkeypatch):
    """The onboarding analysis fetch is the third consumer of the guard."""
    from apps.api.config import settings
    from apps.api.services import site_content

    # Mock mode short-circuits before the guard, so the posture must be proven
    # with mock OFF or the assertion is vacuous.
    monkeypatch.setattr(settings, "mock_external_apis", False)

    calls: list = []

    async def _track_get(self, *args, **kwargs):
        calls.append(args)
        raise httpx.ConnectError("must not be reached in test")

    monkeypatch.setattr(httpx.AsyncClient, "get", _track_get)

    for blocked in ("http://169.254.169.254/", "http://localhost:8000/"):
        res = await site_content.fetch_site_content(blocked)
        assert res["ok"] is False
        assert res["text"] == ""
    assert calls == []  # guard refused before any outbound GET


async def test_verify_pixel_refuses_metadata_without_fetch(monkeypatch):
    calls: list = []

    async def _track_get(self, *args, **kwargs):
        calls.append(args)
        raise httpx.ConnectError("must not be reached in test")

    monkeypatch.setattr(httpx.AsyncClient, "get", _track_get)
    res = await pixel_verifier.verify_pixel("http://127.0.0.1:8000/", "site_x")
    assert res["status"] == "fetch_error"
    assert res["verified"] is False
    assert calls == []
