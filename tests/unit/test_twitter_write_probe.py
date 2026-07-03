"""TwitterService.check_write_access: read the x-access-level header to tell
whether a freshly-connected token can actually post."""

import httpx
import pytest

from apps.api.services.platforms.twitter import TwitterService

pytestmark = pytest.mark.asyncio


class _FakeResp:
    def __init__(self, status: int, headers: dict):
        self.status_code = status
        self.headers = headers


def _patch_get(monkeypatch, status: int, headers: dict) -> None:
    async def fake_get(self, url, *args, **kwargs):
        return _FakeResp(status, headers)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


async def test_write_access_probe(monkeypatch):
    svc = TwitterService()

    _patch_get(monkeypatch, 200, {"x-access-level": "read-write"})
    assert await svc.check_write_access("t") is True

    _patch_get(monkeypatch, 200, {"x-access-level": "read-write-directmessages"})
    assert await svc.check_write_access("t") is True

    _patch_get(monkeypatch, 200, {"x-access-level": "read"})
    assert await svc.check_write_access("t") is False

    # No header → unknown, not a false negative.
    _patch_get(monkeypatch, 200, {})
    assert await svc.check_write_access("t") is None

    # Non-200 → unknown (never blocks connect).
    _patch_get(monkeypatch, 403, {})
    assert await svc.check_write_access("t") is None


async def test_write_access_probe_swallows_errors(monkeypatch):
    svc = TwitterService()

    async def boom(self, url, *args, **kwargs):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(httpx.AsyncClient, "get", boom)
    assert await svc.check_write_access("t") is None
