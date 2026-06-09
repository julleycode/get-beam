"""LinkedIn API integration (posts + comments only, DMs require partnership)."""

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

_LI_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
_LI_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
_LI_API = "https://api.linkedin.com/v2"


class LinkedInService(PlatformService):
    async def get_auth_url(self, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": settings.linkedin_client_id,
            "redirect_uri": settings.linkedin_redirect_uri,
            "state": state,
            "scope": "openid profile w_member_social r_liteprofile",
        }
        return f"{_LI_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, state: str = "") -> OAuthTokens:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                _LI_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.linkedin_redirect_uri,
                    "client_id": settings.linkedin_client_id,
                    "client_secret": settings.linkedin_client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()

        user_info = await self._get_me(data["access_token"])
        return OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            scopes=["r_liteprofile", "w_member_social"],
            platform_user_id=user_info["id"],
            username=f"{user_info.get('localizedFirstName', '')} {user_info.get('localizedLastName', '')}",
        )

    async def refresh_tokens(self, refresh_token: str) -> OAuthTokens:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                _LI_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": settings.linkedin_client_id,
                    "client_secret": settings.linkedin_client_secret,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", refresh_token),
        )

    async def fetch_feed(
        self, access_token: str, *, limit: int = 20
    ) -> list[FeedPost]:
        # LinkedIn feed API is restricted; use posts endpoint for own network
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_LI_API}/posts",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "X-Restli-Protocol-Version": "2.0.0",
                },
                params={"q": "author", "count": limit},
            )
            resp.raise_for_status()
            data = resp.json()

        posts: list[FeedPost] = []
        for item in data.get("elements", []):
            posts.append(
                FeedPost(
                    platform_post_id=item.get("id", ""),
                    author_name=item.get("author", ""),
                    author_username=item.get("author", ""),
                    content=item.get("commentary", ""),
                    post_url=f"https://linkedin.com/feed/update/{item.get('id', '')}",
                    posted_at=datetime.fromtimestamp(
                        item.get("createdAt", 0) / 1000, tz=timezone.utc
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
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_LI_API}/socialActions/{platform_post_id}/comments",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "X-Restli-Protocol-Version": "2.0.0",
                },
                json={
                    "actor": "urn:li:person:me",
                    "message": {"text": text},
                },
            )
            resp.raise_for_status()
            return resp.json().get("id", "")

    async def _get_me(self, access_token: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_LI_API}/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()

