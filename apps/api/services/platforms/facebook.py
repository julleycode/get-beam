"""Facebook Graph API integration."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from urllib.parse import urlencode

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from apps.api.config import settings
from apps.api.services.platforms.base import (
    FeedPost,
    OAuthTokens,
    PlatformService,
)


def _is_transient_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout)):
        return True
    return False

logger = structlog.get_logger()

_FB_AUTH_URL = "https://www.facebook.com/v19.0/dialog/oauth"
_FB_TOKEN_URL = "https://graph.facebook.com/v19.0/oauth/access_token"
_FB_API = "https://graph.facebook.com/v19.0"


class FacebookService(PlatformService):
    async def get_auth_url(self, state: str) -> str:
        if settings.mock_social_oauth:
            params = urlencode({"code": f"mock_code_{state[:8]}", "state": state})
            return f"{settings.api_base_url}/api/v1/social/callback/facebook?{params}"

        params = {
            "client_id": settings.facebook_app_id,
            "redirect_uri": settings.facebook_redirect_uri,
            "state": state,
            "scope": "public_profile,user_posts,publish_to_groups",
            "response_type": "code",
        }
        return f"{_FB_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, state: str = "") -> OAuthTokens:
        if settings.mock_social_oauth:
            return self._mock_tokens()

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                _FB_TOKEN_URL,
                params={
                    "client_id": settings.facebook_app_id,
                    "client_secret": settings.facebook_app_secret,
                    "redirect_uri": settings.facebook_redirect_uri,
                    "code": code,
                },
            )
            resp.raise_for_status()
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
        if settings.mock_social_oauth:
            return self._mock_tokens()
        raise NotImplementedError("Use long-lived token exchange instead")

    async def fetch_feed(
        self, access_token: str, *, limit: int = 20
    ) -> list[FeedPost]:
        if settings.mock_social_oauth:
            return self._mock_feed(limit)

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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_transient_error),
        reraise=True,
    )
    async def post_comment(
        self, access_token: str, platform_post_id: str, text: str
    ) -> str:
        if settings.mock_social_oauth:
            mock_id = f"mock_fb_comment_{uuid.uuid4().hex[:8]}"
            logger.info("mock_fb_comment", post_id=platform_post_id, comment_id=mock_id)
            return mock_id

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

    @staticmethod
    def _mock_tokens() -> OAuthTokens:
        return OAuthTokens(
            access_token=f"mock_fb_token_{uuid.uuid4().hex[:8]}",
            scopes=["public_profile", "user_posts"],
            platform_user_id="mock_fb_100",
            username="Mock Facebook User",
        )

    @staticmethod
    def _mock_feed(limit: int) -> list[FeedPost]:
        now = datetime.now(timezone.utc)
        samples = [
            ("Loving the weather today!", "Sarah Johnson"),
            ("Just launched my online store", "Mike Chen"),
            ("Friday vibes! Who's ready for the weekend?", "Lisa Park"),
        ]
        return [
            FeedPost(
                platform_post_id=f"mock_fb_post_{i}",
                author_name=name,
                author_username=name.lower().replace(" ", "."),
                content=text,
                post_url=f"https://facebook.com/mock_post_{i}",
                posted_at=now,
            )
            for i, (text, name) in enumerate(samples[:limit])
        ]
