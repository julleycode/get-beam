"""LinkedIn feed sync: modern API client + sync wiring.

Covers the fix for "LinkedIn tab in Feed is always empty":
- sync_account_feed now routes LinkedIn accounts to sync_linkedin_my_posts
  (previously every sync source guard-returned 0 for non-Twitter platforms).
- LinkedInService uses OIDC userinfo + the versioned /rest/posts API and
  degrades to [] on 403 (Community Management API not granted).
"""

import uuid
from datetime import datetime, timezone

import httpx
import pytest

from types import SimpleNamespace

from apps.api.models.social_account import Platform
from apps.api.services.platforms.linkedin import LinkedInService
from apps.api.services import sync as sync_service


_USERINFO = {"sub": "AbC123", "name": "Julley Thai", "email": "j@example.com"}

_POSTS_PAYLOAD = {
    "elements": [
        {
            "id": "urn:li:share:7100000000000000001",
            "commentary": "Hello LinkedIn",
            "publishedAt": 1751400000000,
        },
        {
            "id": "urn:li:share:7100000000000000002",
            "commentary": "Second post",
            "createdAt": 1751300000000,
        },
    ]
}


def _fake_get(responses_by_path: dict[str, httpx.Response]):
    """Build an async replacement for httpx.AsyncClient.get keyed on URL path."""

    calls: list[str] = []

    async def fake_get(self, url, *args, **kwargs):
        calls.append(str(url))
        for path, resp in responses_by_path.items():
            if path in str(url):
                return resp
        raise AssertionError(f"Unexpected GET {url}")

    return fake_get, calls


def _resp(status: int, json_data: dict) -> httpx.Response:
    return httpx.Response(
        status,
        json=json_data,
        request=httpx.Request("GET", "https://api.linkedin.com/test"),
    )


# ── LinkedInService.fetch_feed ────────────────────────────


@pytest.mark.asyncio
async def test_fetch_feed_parses_versioned_posts(monkeypatch):
    fake_get, calls = _fake_get(
        {
            "/v2/userinfo": _resp(200, _USERINFO),
            "/rest/posts": _resp(200, _POSTS_PAYLOAD),
        }
    )
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    posts = await LinkedInService().fetch_feed("token", limit=10)

    assert len(posts) == 2
    first = posts[0]
    assert first.platform_post_id == "urn:li:share:7100000000000000001"
    assert first.author_name == "Julley Thai"
    assert first.content == "Hello LinkedIn"
    assert first.post_url == (
        "https://www.linkedin.com/feed/update/urn:li:share:7100000000000000001"
    )
    assert first.posted_at == datetime.fromtimestamp(
        1751400000, tz=timezone.utc
    )
    # createdAt fallback when publishedAt missing
    assert posts[1].posted_at == datetime.fromtimestamp(
        1751300000, tz=timezone.utc
    )
    # userinfo resolved before posts
    assert any("/v2/userinfo" in c for c in calls)


@pytest.mark.asyncio
async def test_fetch_feed_403_degrades_to_empty(monkeypatch):
    """403 = app lacks Community Management API — must NOT raise."""
    fake_get, _ = _fake_get(
        {
            "/v2/userinfo": _resp(200, _USERINFO),
            "/rest/posts": _resp(403, {"message": "Not enough permissions"}),
        }
    )
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    posts = await LinkedInService().fetch_feed("token")

    assert posts == []


@pytest.mark.asyncio
async def test_auth_url_uses_live_scopes():
    """r_liteprofile is retired — requesting it breaks the OAuth screen."""
    url = await LinkedInService().get_auth_url("state123")
    assert "r_liteprofile" not in url
    assert "openid" in url
    assert "w_member_social" in url


# ── sync wiring ───────────────────────────────────────────


def _account(platform: Platform) -> SimpleNamespace:
    # Stand-in for SocialAccount — the sync functions under test only read
    # these attributes, and instantiating the ORM model would drag the full
    # mapper graph into a unit test.
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        platform=platform,
        platform_user_id="AbC123",
        username="Julley Thai",
        access_token="enc",
        is_active=True,
    )


@pytest.mark.asyncio
async def test_sync_linkedin_my_posts_guards_platform():
    n = await sync_service.sync_linkedin_my_posts(None, _account(Platform.twitter))
    assert n == 0


@pytest.mark.asyncio
async def test_sync_account_feed_routes_linkedin(monkeypatch):
    seen: list[str] = []

    async def fake_linkedin(db, account):
        seen.append("linkedin")
        return 7

    async def fail(*args, **kwargs):  # twitter paths must not run
        raise AssertionError("twitter sync called for linkedin account")

    monkeypatch.setattr(sync_service, "sync_linkedin_my_posts", fake_linkedin)
    monkeypatch.setattr(sync_service, "sync_visitor_posts", fail)
    monkeypatch.setattr(sync_service, "sync_following_feed", fail)
    monkeypatch.setattr(sync_service, "sync_my_posts", fail)

    n = await sync_service.sync_account_feed(None, _account(Platform.linkedin))

    assert n == 7
    assert seen == ["linkedin"]


@pytest.mark.asyncio
async def test_sync_account_feed_twitter_path_unchanged(monkeypatch):
    async def fake_zero(db, account):
        return 0

    async def fake_linkedin(db, account):
        raise AssertionError("linkedin sync called for twitter account")

    monkeypatch.setattr(sync_service, "sync_visitor_posts", fake_zero)
    monkeypatch.setattr(sync_service, "sync_following_feed", fake_zero)
    monkeypatch.setattr(sync_service, "sync_my_posts", fake_zero)
    monkeypatch.setattr(sync_service, "sync_linkedin_my_posts", fake_linkedin)

    n = await sync_service.sync_account_feed(None, _account(Platform.twitter))

    assert n == 0
