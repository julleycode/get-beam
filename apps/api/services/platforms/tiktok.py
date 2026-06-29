"""TikTok API integration (comments only, DMs very restricted)."""

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
from apps.api.services.platforms.pkce import (
    generate_code_verifier,
    generate_code_challenge,
    store_code_verifier,
    get_code_verifier,
)


logger = structlog.get_logger()

_TT_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize"
_TT_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
_TT_API = "https://open.tiktokapis.com/v2"


class TikTokService(PlatformService):
    async def get_auth_url(self, state: str) -> str:
        code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(code_verifier)
        await store_code_verifier(state, code_verifier)

        params = {
            "client_key": settings.tiktok_client_key,
            "response_type": "code",
            "scope": "user.info.basic,video.list,video.publish",
            "redirect_uri": settings.tiktok_redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{_TT_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, state: str = "") -> OAuthTokens:
        # Retrieve the code_verifier stored during get_auth_url
        code_verifier = await get_code_verifier(state) if state else None
        if not code_verifier:
            raise ValueError(
                "PKCE code_verifier not found for this OAuth state. "
                "The authorization may have expired (10 min TTL). Try connecting again."
            )

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                _TT_TOKEN_URL,
                json={
                    "client_key": settings.tiktok_client_key,
                    "client_secret": settings.tiktok_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": settings.tiktok_redirect_uri,
                    "code_verifier": code_verifier,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            platform_user_id=data.get("open_id", ""),
            username="tiktok_user",
            scopes=data.get("scope", "").split(","),
        )

    async def refresh_tokens(self, refresh_token: str) -> OAuthTokens:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                _TT_TOKEN_URL,
                json={
                    "client_key": settings.tiktok_client_key,
                    "client_secret": settings.tiktok_client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
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
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_TT_API}/video/list/",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"max_count": limit},
                params={"fields": "id,title,create_time,share_url,cover_image_url"},
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})

        posts: list[FeedPost] = []
        for video in data.get("videos", []):
            posts.append(
                FeedPost(
                    platform_post_id=video["id"],
                    author_name="",
                    author_username="",
                    content=video.get("title", ""),
                    post_url=video.get("share_url", ""),
                    posted_at=datetime.fromtimestamp(
                        video.get("create_time", 0), tz=timezone.utc
                    ),
                    media_urls=[video["cover_image_url"]] if video.get("cover_image_url") else [],
                )
            )
        return posts

    @post_retry
    async def post_comment(
        self, access_token: str, platform_post_id: str, text: str
    ) -> str:
        # TikTok comments API
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_TT_API}/comment/publish/",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "video_id": platform_post_id,
                    "text": text,
                },
            )
            resp.raise_for_status()
            return resp.json().get("data", {}).get("comment_id", "")

