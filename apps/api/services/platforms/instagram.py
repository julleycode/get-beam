"""Instagram Graph API integration (via Meta / Facebook app)."""

import uuid
from datetime import datetime, timezone

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

_IG_AUTH_URL = "https://www.facebook.com/v19.0/dialog/oauth"
_IG_TOKEN_URL = "https://graph.facebook.com/v19.0/oauth/access_token"
_IG_API = "https://graph.facebook.com/v19.0"


class InstagramService(PlatformService):
    async def get_auth_url(self, state: str) -> str:
        params = {
            "client_id": settings.facebook_app_id,
            "redirect_uri": settings.instagram_redirect_uri,
            "state": state,
            "scope": "instagram_basic,instagram_manage_comments,pages_show_list",
            "response_type": "code",
        }
        return f"{_IG_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, state: str = "") -> OAuthTokens:
        if settings.mock_external_apis:
            return self._mock_tokens()

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                _IG_TOKEN_URL,
                params={
                    "client_id": settings.facebook_app_id,
                    "client_secret": settings.facebook_app_secret,
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
        if settings.mock_external_apis:
            return self._mock_tokens()
        raise NotImplementedError("IG uses long-lived tokens via Facebook")

    async def fetch_feed(
        self, access_token: str, *, limit: int = 20
    ) -> list[FeedPost]:
        if settings.mock_external_apis:
            return self._mock_feed(limit)

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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_transient_error),
        reraise=True,
    )
    async def post_comment(
        self, access_token: str, platform_post_id: str, text: str
    ) -> str:
        if settings.mock_external_apis:
            mock_id = f"mock_ig_comment_{uuid.uuid4().hex[:8]}"
            logger.info("mock_ig_comment", post_id=platform_post_id, comment_id=mock_id)
            return mock_id

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

    @staticmethod
    def _mock_tokens() -> OAuthTokens:
        return OAuthTokens(
            access_token=f"mock_ig_token_{uuid.uuid4().hex[:8]}",
            scopes=["instagram_basic", "instagram_manage_comments"],
            platform_user_id="mock_ig_200",
            username="mock_ig_user",
        )

    @staticmethod
    def _mock_feed(limit: int) -> list[FeedPost]:
        now = datetime.now(timezone.utc)
        samples = [
            ("Morning coffee and code", "coffeecoder", "https://picsum.photos/400"),
            ("New product photoshoot!", "brandbuilder", "https://picsum.photos/401"),
            ("Behind the scenes at the studio", "creativestudio", "https://picsum.photos/402"),
        ]
        return [
            FeedPost(
                platform_post_id=f"mock_ig_post_{i}",
                author_name=username,
                author_username=username,
                content=text,
                post_url=f"https://instagram.com/p/mock_{i}",
                posted_at=now,
                media_urls=[url],
            )
            for i, (text, username, url) in enumerate(samples[:limit])
        ]
