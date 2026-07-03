"""Facebook Graph API integration."""

from datetime import datetime, timezone
from typing import Optional

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

_FB_AUTH_URL = "https://www.facebook.com/v19.0/dialog/oauth"
_FB_TOKEN_URL = "https://graph.facebook.com/v19.0/oauth/access_token"
_FB_API = "https://graph.facebook.com/v19.0"


class FacebookService(PlatformService):
    async def get_auth_url(self, state: str) -> str:
        params = {
            "client_id": settings.facebook_app_id,
            "redirect_uri": settings.facebook_redirect_uri,
            "state": state,
            # Only public_profile is still grantable. Meta retired user_posts
            # (personal-feed read) and publish_to_groups (Groups API, 2024) —
            # including them makes the OAuth dialog reject the request with
            # "Invalid Scopes" instead of showing the consent screen.
            "scope": "public_profile",
            "response_type": "code",
        }
        return f"{_FB_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, state: str = "") -> OAuthTokens:
        async with httpx.AsyncClient(timeout=10) as client:
            # POST so the client_secret rides in the body, never the URL query —
            # a GET leaks the secret into any URL-bearing error log.
            resp = await client.post(
                _FB_TOKEN_URL,
                data={
                    "client_id": settings.facebook_app_id,
                    "client_secret": settings.facebook_app_secret,
                    "redirect_uri": settings.facebook_redirect_uri,
                    "code": code,
                },
            )
            if resp.status_code != 200:
                # Log Meta's exact reason (bad secret / redirect mismatch /
                # expired code). raise_for_status() would instead throw an error
                # whose message embeds the secret-bearing URL — don't use it.
                logger.error(
                    "facebook_token_exchange_failed",
                    status=resp.status_code,
                    body=resp.text[:500],
                )
                raise RuntimeError(
                    f"Facebook token exchange returned {resp.status_code}"
                )
            data = resp.json()

        user_info = await self._get_me(data["access_token"])
        return OAuthTokens(
            access_token=data["access_token"],
            platform_user_id=user_info["id"],
            username=user_info.get("name", ""),
            scopes=["public_profile", "user_posts"],
        )

    async def refresh_tokens(self, refresh_token: str) -> OAuthTokens:
        # Facebook uses long-lived tokens, no traditional refresh
        raise NotImplementedError("Use long-lived token exchange instead")

    async def fetch_feed(
        self, access_token: str, *, limit: int = 20
    ) -> list[FeedPost]:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_FB_API}/me/home",
                params={
                    "access_token": access_token,
                    "limit": limit,
                    "fields": "id,message,created_time,from,permalink_url",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        posts: list[FeedPost] = []
        for item in data.get("data", []):
            from_data = item.get("from", {})
            posts.append(
                FeedPost(
                    platform_post_id=item["id"],
                    author_name=from_data.get("name", ""),
                    author_username=from_data.get("id", ""),
                    content=item.get("message", ""),
                    post_url=item.get("permalink_url", ""),
                    posted_at=datetime.fromisoformat(
                        item["created_time"].replace("+0000", "+00:00")
                    ),
                )
            )
        return posts

    @post_retry
    async def post_comment(
        self, access_token: str, platform_post_id: str, text: str
    ) -> str:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_FB_API}/{platform_post_id}/comments",
                params={"access_token": access_token},
                json={"message": text},
            )
            resp.raise_for_status()
            return resp.json()["id"]

    async def _get_me(self, access_token: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_FB_API}/me",
                params={"access_token": access_token, "fields": "id,name"},
            )
            resp.raise_for_status()
            return resp.json()

