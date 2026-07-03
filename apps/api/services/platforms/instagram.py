"""Instagram Graph API integration (via Meta / Facebook app)."""

from datetime import datetime, timezone

from urllib.parse import urlencode

import httpx
import structlog
from apps.api.config import settings
from apps.api.services.platforms.base import (
    FeedPost,
    OAuthTokens,
    PlatformService,
    post_retry,
)


logger = structlog.get_logger()

_IG_AUTH_URL = "https://www.facebook.com/v19.0/dialog/oauth"
_IG_TOKEN_URL = "https://graph.facebook.com/v19.0/oauth/access_token"
_IG_API = "https://graph.facebook.com/v19.0"


def instagram_app_id() -> str:
    """Instagram's Meta app id, falling back to the Facebook app for legacy setups."""
    return settings.instagram_app_id or settings.facebook_app_id


def instagram_app_secret() -> str:
    """Instagram's Meta app secret, falling back to the Facebook app for legacy setups."""
    return settings.instagram_app_secret or settings.facebook_app_secret


class InstagramService(PlatformService):
    async def get_auth_url(self, state: str) -> str:
        params = {
            "client_id": instagram_app_id(),
            "redirect_uri": settings.instagram_redirect_uri,
            "state": state,
            "scope": "instagram_basic,instagram_manage_comments,pages_show_list",
            "response_type": "code",
        }
        return f"{_IG_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, state: str = "") -> OAuthTokens:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                _IG_TOKEN_URL,
                params={
                    "client_id": instagram_app_id(),
                    "client_secret": instagram_app_secret(),
                    "redirect_uri": settings.instagram_redirect_uri,
                    "code": code,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # Get linked IG business account
        ig_account = await self._get_ig_account(data["access_token"])
        return OAuthTokens(
            access_token=data["access_token"],
            platform_user_id=ig_account["id"],
            username=ig_account.get("username", ""),
            scopes=["instagram_basic", "instagram_manage_comments"],
        )

    async def refresh_tokens(self, refresh_token: str) -> OAuthTokens:
        raise NotImplementedError("IG uses long-lived tokens via Facebook")

    async def fetch_feed(
        self, access_token: str, *, limit: int = 20
    ) -> list[FeedPost]:
        # IG Graph API: fetch recent media with comments enabled
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_IG_API}/me/media",
                params={
                    "access_token": access_token,
                    "limit": limit,
                    "fields": "id,caption,timestamp,permalink,username,media_url",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        posts: list[FeedPost] = []
        for item in data.get("data", []):
            media_urls = [item["media_url"]] if item.get("media_url") else []
            posts.append(
                FeedPost(
                    platform_post_id=item["id"],
                    author_name=item.get("username", ""),
                    author_username=item.get("username", ""),
                    content=item.get("caption", ""),
                    post_url=item.get("permalink", ""),
                    posted_at=datetime.fromisoformat(
                        item["timestamp"].replace("+0000", "+00:00")
                    ),
                    media_urls=media_urls,
                )
            )
        return posts

    @post_retry
    async def post_comment(
        self, access_token: str, platform_post_id: str, text: str
    ) -> str:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_IG_API}/{platform_post_id}/comments",
                params={"access_token": access_token},
                json={"message": text},
            )
            resp.raise_for_status()
            return resp.json()["id"]

    async def _get_ig_account(self, access_token: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_IG_API}/me/accounts",
                params={"access_token": access_token, "fields": "instagram_business_account"},
            )
            resp.raise_for_status()
            pages = resp.json().get("data", [])
            for page in pages:
                ig = page.get("instagram_business_account")
                if ig:
                    r2 = await client.get(
                        f"{_IG_API}/{ig['id']}",
                        params={"access_token": access_token, "fields": "id,username"},
                    )
                    r2.raise_for_status()
                    return r2.json()
        return {"id": "unknown", "username": "unknown"}

