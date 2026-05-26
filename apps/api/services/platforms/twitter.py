"""Twitter / X API v2 integration."""

import uuid
from datetime import datetime, timedelta, timezone
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
from apps.api.services.platforms.pkce import (
    generate_code_verifier,
    generate_code_challenge,
    store_code_verifier,
    get_code_verifier,
)


def _is_transient_error(exc: BaseException) -> bool:
    """Return True for HTTP errors worth retrying (5xx, 429)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout)):
        return True
    return False

logger = structlog.get_logger()

_TWITTER_AUTH_URL = "https://twitter.com/i/oauth2/authorize"
_TWITTER_TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
_TWITTER_API = "https://api.twitter.com/2"


class TwitterService(PlatformService):
    # ── OAuth (PKCE with S256) ───────────────────────────
    async def get_auth_url(self, state: str) -> str:
        code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(code_verifier)
        await store_code_verifier(state, code_verifier)

        params = {
            "response_type": "code",
            "client_id": settings.twitter_client_id,
            "redirect_uri": settings.twitter_redirect_uri,
            "scope": "tweet.read tweet.write users.read follows.read offline.access",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{_TWITTER_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, state: str = "") -> OAuthTokens:
        if settings.mock_external_apis:
            return self._mock_tokens()

        # Retrieve the code_verifier stored during get_auth_url
        code_verifier = await get_code_verifier(state) if state else None
        if not code_verifier:
            raise ValueError(
                "PKCE code_verifier not found for this OAuth state. "
                "The authorization may have expired (10 min TTL). Try connecting again."
            )

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                _TWITTER_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.twitter_redirect_uri,
                    "client_id": settings.twitter_client_id,
                    "code_verifier": code_verifier,
                },
                auth=(settings.twitter_client_id, settings.twitter_client_secret),
            )
            resp.raise_for_status()
            data = resp.json()

        # Compute token expiry from expires_in (Twitter returns seconds)
        expires_at = None
        if "expires_in" in data:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"])

        # Get user info
        user_info = await self._get_me(data["access_token"])
        return OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            scopes=data.get("scope", "").split(),
            platform_user_id=user_info["id"],
            username=user_info["username"],
        )

    async def refresh_tokens(self, refresh_token: str) -> OAuthTokens:
        if settings.mock_external_apis:
            return self._mock_tokens()

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                _TWITTER_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": settings.twitter_client_id,
                },
                auth=(settings.twitter_client_id, settings.twitter_client_secret),
            )
            resp.raise_for_status()
            data = resp.json()

        expires_at = None
        if "expires_in" in data:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"])

        return OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", refresh_token),
            expires_at=expires_at,
            scopes=data.get("scope", "").split(),
        )

    # ── Read ─────────────────────────────────────────────
    async def fetch_feed(
        self, access_token: str, *, limit: int = 20
    ) -> list[FeedPost]:
        if settings.mock_external_apis:
            return self._mock_feed(limit)

        # ── Primary: Playwright browser scraping (free, reliable) ──
        try:
            from apps.api.services.platforms.twitter_browser import (
                TwitterBrowserPoster,
                TwitterBrowserError,
            )

            poster = TwitterBrowserPoster()
            posts = await poster.fetch_timeline(limit=limit)
            if posts:
                logger.info("twitter_browser_feed_ok", count=len(posts))
                return posts
        except TwitterBrowserError as exc:
            logger.warning("twitter_browser_feed_failed", error=str(exc))
        except Exception as exc:
            logger.warning("twitter_browser_feed_unexpected_error", error=str(exc))

        # ── Fallback: API (works for own tweets on Free tier) ──
        posts: list[FeedPost] = []
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient(timeout=10) as client:
            me = await self._get_me(access_token)
            my_id = me["id"]

            # Try own tweets
            try:
                resp = await client.get(
                    f"{_TWITTER_API}/users/{my_id}/tweets",
                    headers=headers,
                    params={
                        "max_results": min(limit, 100),
                        "tweet.fields": "created_at,author_id,text",
                        "expansions": "author_id",
                        "user.fields": "name,username,profile_image_url",
                    },
                )
                resp.raise_for_status()
                posts.extend(self._parse_tweets(resp.json()))
                logger.info("twitter_own_tweets_fallback", count=len(posts))
            except httpx.HTTPStatusError as e:
                logger.warning("twitter_own_tweets_failed", status=e.response.status_code)

            # Try search mentions
            try:
                resp = await client.get(
                    f"{_TWITTER_API}/tweets/search/recent",
                    headers=headers,
                    params={
                        "query": f"@{me['username']} -is:retweet",
                        "max_results": min(limit, 10),
                        "tweet.fields": "created_at,author_id,text",
                        "expansions": "author_id",
                        "user.fields": "name,username,profile_image_url",
                    },
                )
                resp.raise_for_status()
                posts.extend(self._parse_tweets(resp.json()))
                logger.info("twitter_mentions_fallback", count=len(posts))
            except httpx.HTTPStatusError:
                pass

        # Deduplicate and sort
        seen: set[str] = set()
        unique: list[FeedPost] = []
        for p in posts:
            if p.platform_post_id not in seen:
                seen.add(p.platform_post_id)
                unique.append(p)
        unique.sort(key=lambda p: p.posted_at, reverse=True)
        return unique[:limit]

    @staticmethod
    def _parse_tweets(data: dict) -> list[FeedPost]:
        """Parse Twitter API v2 response into FeedPost list."""
        users_map: dict[str, dict] = {}
        for u in data.get("includes", {}).get("users", []):
            users_map[u["id"]] = u

        posts: list[FeedPost] = []
        for tweet in data.get("data", []):
            author = users_map.get(tweet.get("author_id", ""), {})
            try:
                posted_at = datetime.fromisoformat(
                    tweet["created_at"].replace("Z", "+00:00")
                )
            except (KeyError, ValueError):
                posted_at = datetime.now(timezone.utc)

            posts.append(
                FeedPost(
                    platform_post_id=tweet["id"],
                    author_name=author.get("name", ""),
                    author_username=author.get("username", ""),
                    author_avatar_url=author.get("profile_image_url"),
                    content=tweet["text"],
                    post_url=f"https://x.com/{author.get('username', '_')}/status/{tweet['id']}",
                    posted_at=posted_at,
                )
            )
        return posts

    # ── Write ────────────────────────────────────────────
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
            mock_id = f"mock_reply_{uuid.uuid4().hex[:8]}"
            logger.info("mock_twitter_reply", post_id=platform_post_id, reply_id=mock_id)
            return mock_id

        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient(timeout=10) as client:
            # Try direct reply first
            resp = await client.post(
                f"{_TWITTER_API}/tweets",
                headers=headers,
                json={
                    "text": text,
                    "reply": {"in_reply_to_tweet_id": platform_post_id},
                },
            )

            # If reply/quote is blocked (403 — Free tier limitation),
            # fall back to Playwright browser automation.
            if resp.status_code == 403:
                logger.warning(
                    "twitter_api_reply_blocked_trying_browser",
                    post_id=platform_post_id,
                    detail=resp.text,
                )
                from apps.api.services.platforms.twitter_browser import (
                    TwitterBrowserPoster,
                )

                poster = TwitterBrowserPoster()
                tweet_url = f"https://x.com/i/status/{platform_post_id}"
                reply_id = await poster.post_reply(tweet_url, text)
                return reply_id

            resp.raise_for_status()
            return resp.json()["data"]["id"]

    # ── Helpers ──────────────────────────────────────────
    async def _get_me(self, access_token: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_TWITTER_API}/users/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()["data"]

    @staticmethod
    def _mock_tokens() -> OAuthTokens:
        return OAuthTokens(
            access_token=f"mock_twitter_token_{uuid.uuid4().hex[:8]}",
            refresh_token=f"mock_twitter_refresh_{uuid.uuid4().hex[:8]}",
            scopes=["tweet.read", "tweet.write", "users.read"],
            platform_user_id="mock_12345",
            username="mock_user",
        )

    @staticmethod
    def _mock_feed(limit: int) -> list[FeedPost]:
        now = datetime.now(timezone.utc)
        posts: list[FeedPost] = []
        samples = [
            ("Just shipped a new feature!", "indiehacker"),
            ("Working on my SaaS this weekend", "buildinpublic"),
            ("Anyone else struggling with OAuth?", "devlife"),
            ("Our MRR hit $10k!", "startupfounder"),
            ("Hot take: REST > GraphQL for most apps", "techtwitter"),
        ]
        for i, (text, username) in enumerate(samples[:limit]):
            posts.append(
                FeedPost(
                    platform_post_id=f"mock_tweet_{i}",
                    author_name=username.title(),
                    author_username=username,
                    content=text,
                    post_url=f"https://x.com/{username}/status/mock_{i}",
                    posted_at=now,
                )
            )
        return posts
