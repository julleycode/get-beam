"""TikTok API integration (comments only, DMs very restricted)."""

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
from apps.api.services.platforms.pkce import (
    generate_code_verifier,
    generate_code_challenge,
    store_code_verifier,
    get_code_verifier,
)


def _is_transient_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout)):
        return True
    return False

logger = structlog.get_logger()

_TT_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize"
_TT_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
_TT_API = "https://open.tiktokapis.com/v2"


class TikTokService(PlatformService):
    def get_auth_url(self, state: str) -> str:
        code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(code_verifier)
        store_code_verifier(state, code_verifier)

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
        if settings.mock_external_apis:
            return self._mock_tokens()

        # Retrieve the code_verifier stored during get_auth_url
        code_verifier = get_code_verifier(state) if state else None
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
        if settings.mock_external_apis:
            return self._mock_tokens()

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
        if settings.mock_external_apis:
            return self._mock_feed(limit)

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
            mock_id = f"mock_tt_comment_{uuid.uuid4().hex[:8]}"
            logger.info("mock_tt_comment", post_id=platform_post_id, comment_id=mock_id)
            return mock_id

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

    @staticmethod
    def _mock_tokens() -> OAuthTokens:
        return OAuthTokens(
            access_token=f"mock_tt_token_{uuid.uuid4().hex[:8]}",
            refresh_token=f"mock_tt_refresh_{uuid.uuid4().hex[:8]}",
            scopes=["user.info.basic", "video.list"],
            platform_user_id="mock_tt_400",
            username="mock_tiktok_user",
        )

    @staticmethod
    def _mock_feed(limit: int) -> list[FeedPost]:
        now = datetime.now(timezone.utc)
        samples = [
            ("How I grew my brand to 100k followers", "growthguru"),
            ("POV: debugging at 2am", "codertok"),
            ("This productivity hack changed my life", "lifehacker"),
        ]
        return [
            FeedPost(
                platform_post_id=f"mock_tt_post_{i}",
                author_name=username,
                author_username=username,
                content=text,
                post_url=f"https://tiktok.com/@{username}/video/mock_{i}",
                posted_at=now,
                media_urls=["https://picsum.photos/300/500"],
            )
            for i, (text, username) in enumerate(samples[:limit])
        ]
