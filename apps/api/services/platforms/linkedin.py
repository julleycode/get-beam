"""LinkedIn API integration (posts + comments only, DMs require partnership).

Uses the current LinkedIn APIs:
- OAuth scopes: OpenID Connect (``openid profile email``) + ``w_member_social``.
  The legacy ``r_liteprofile`` scope was retired by LinkedIn and requesting it
  breaks the whole OAuth consent screen for non-approved apps.
- Profile: ``GET /v2/userinfo`` (OIDC) instead of the retired ``/v2/me``.
- Own posts: versioned ``GET /rest/posts?q=author`` with the
  ``LinkedIn-Version`` header. NOTE: reading member posts requires the
  Community Management API product (``r_member_social``), which LinkedIn only
  grants to approved partners — without it the endpoint returns 403 and we
  degrade gracefully to an empty feed instead of failing the whole sync.
"""

from datetime import datetime, timedelta, timezone

from urllib.parse import quote, urlencode

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

_LI_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
_LI_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
_LI_API = "https://api.linkedin.com/v2"
_LI_REST_API = "https://api.linkedin.com/rest"


def _versioned_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": settings.linkedin_api_version,
    }


class LinkedInService(PlatformService):
    async def get_auth_url(self, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": settings.linkedin_client_id,
            "redirect_uri": settings.linkedin_redirect_uri,
            "state": state,
            "scope": "openid profile email w_member_social",
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
        expires_at = None
        if data.get("expires_in"):
            expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=int(data["expires_in"])
            )
        return OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            scopes=["openid", "profile", "email", "w_member_social"],
            platform_user_id=user_info["sub"],
            username=user_info.get("name", ""),
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

        expires_at = None
        if data.get("expires_in"):
            expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=int(data["expires_in"])
            )
        return OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", refresh_token),
            expires_at=expires_at,
        )

    async def fetch_feed(
        self, access_token: str, *, limit: int = 20
    ) -> list[FeedPost]:
        """Fetch the member's own posts via the versioned Posts API.

        Returns [] (instead of raising) on 403 — that status means the app
        lacks the Community Management API product, which is expected for
        non-partner apps.
        """
        user_info = await self._get_me(access_token)
        author_urn = f"urn:li:person:{user_info['sub']}"
        author_name = user_info.get("name", "")

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_LI_REST_API}/posts",
                headers=_versioned_headers(access_token),
                params={"q": "author", "author": author_urn, "count": limit},
            )
            if resp.status_code == 403:
                logger.warning(
                    "linkedin_feed_read_restricted",
                    detail="App lacks Community Management API access "
                    "(r_member_social); cannot read member posts.",
                )
                return []
            resp.raise_for_status()
            data = resp.json()

        posts: list[FeedPost] = []
        for item in data.get("elements", []):
            post_urn = item.get("id", "")
            created_ms = item.get("publishedAt") or item.get("createdAt") or 0
            commentary = item.get("commentary") or ""
            posts.append(
                FeedPost(
                    platform_post_id=post_urn,
                    author_name=author_name,
                    author_username=author_name,
                    content=commentary,
                    post_url=f"https://www.linkedin.com/feed/update/{post_urn}",
                    posted_at=datetime.fromtimestamp(
                        created_ms / 1000, tz=timezone.utc
                    ),
                )
            )
        return posts

    @post_retry
    async def post_comment(
        self, access_token: str, platform_post_id: str, text: str
    ) -> str:
        # actor must be the member's real URN — "urn:li:person:me" is not
        # accepted by the socialActions API.
        user_info = await self._get_me(access_token)
        actor_urn = f"urn:li:person:{user_info['sub']}"

        # The target URN goes in the URL path and must be percent-encoded
        # (colons included) per the Restli 2.0 protocol.
        encoded_target = quote(platform_post_id, safe="")

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_LI_API}/socialActions/{encoded_target}/comments",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "X-Restli-Protocol-Version": "2.0.0",
                },
                json={
                    "actor": actor_urn,
                    "message": {"text": text},
                },
            )
            resp.raise_for_status()
            return resp.json().get("id", "")

    async def _get_me(self, access_token: str) -> dict:
        """OIDC userinfo: returns ``sub`` (member id), ``name``, ``email``…"""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_LI_API}/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()
