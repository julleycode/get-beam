"""Twitter / X API v2 integration."""

from datetime import datetime, timedelta, timezone
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
    read_retry,
)
from apps.api.services.platforms.pkce import (
    generate_code_verifier,
    generate_code_challenge,
    store_code_verifier,
    get_code_verifier,
)


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
    @post_retry
    async def post_comment(
        self, access_token: str, platform_post_id: str, text: str
    ) -> str:
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

            # A 403 here means X refused the reply itself (e.g. the target
            # tweet restricts who can reply, a duplicate, or an account-level
            # limit) — NOT a token problem. We deliberately do NOT fall back to
            # browser automation: X blocks automated logins, so the Playwright
            # path is a dead end on the server and only produces confusing
            # failures. Surface the real 403 reason instead.
            if resp.status_code == 403:
                logger.warning(
                    "twitter_api_reply_forbidden",
                    post_id=platform_post_id,
                    detail=resp.text[:300],
                )

            resp.raise_for_status()
            return resp.json()["data"]["id"]

    # ── Search by handles (for visitor engagement) ──────
    async def search_by_handles(
        self, access_token: str, handles: list[str], *, limit: int = 20
    ) -> list[FeedPost]:
        """Search recent tweets FROM specific Twitter handles.

        Used to populate the Feed with posts from identified visitors
        (EasyTrack → enrichment → twitter_handle → fetch their tweets).
        """
        if not handles:
            return []

        # Build query: "from:handle1 OR from:handle2 OR ..."
        # Twitter search supports up to ~512 chars in query
        query_parts = [f"from:{h.lstrip('@')}" for h in handles[:15]]  # max 15 handles
        query = " OR ".join(query_parts) + " -is:retweet"

        headers = {"Authorization": f"Bearer {access_token}"}
        posts: list[FeedPost] = []

        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(
                    f"{_TWITTER_API}/tweets/search/recent",
                    headers=headers,
                    params={
                        "query": query,
                        "max_results": min(max(limit, 10), 100),
                        "tweet.fields": "created_at,author_id,text",
                        "expansions": "author_id",
                        "user.fields": "name,username,profile_image_url",
                    },
                )
                resp.raise_for_status()
                posts = self._parse_tweets(resp.json())
                logger.info("twitter_visitor_search_ok", handles=len(handles), results=len(posts))
            except httpx.HTTPStatusError as e:
                logger.warning("twitter_visitor_search_failed", status=e.response.status_code, detail=e.response.text[:200])

        return posts[:limit]

    async def check_write_access(self, access_token: str) -> bool | None:
        """True if the token can post, per X's ``x-access-level`` header on an
        authenticated read. "read-write"(-directmessages) → can post; "read" →
        cannot. Returns None on any error so a probe failure never blocks connect.
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_TWITTER_API}/users/me",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if resp.status_code != 200:
                return None
            level = resp.headers.get("x-access-level", "").lower()
            return "write" in level if level else None
        except Exception:
            logger.warning("twitter_write_probe_failed")
            return None

    # ── Outcome reads (engage-learning-agent Phase 1) ─────
    @read_retry
    async def fetch_reply_mentions(
        self, access_token: str, *, limit: int = 50
    ) -> list[dict]:
        """Recent mentions as RAW tweet dicts carrying author_id + referenced_tweets.

        `referenced_tweets` is requested here for the first time anywhere in this
        repo — it is what makes the reply-back linkage EXACT (which of our replies
        was replied to) instead of a temporal guess. `_parse_tweets` is deliberately
        NOT reused: `FeedPost` drops both `referenced_tweets` and `author_id`.
        """
        headers = {"Authorization": f"Bearer {access_token}"}
        me = await self._get_me(access_token)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_TWITTER_API}/tweets/search/recent",
                headers=headers,
                params={
                    "query": f"@{me['username']} -is:retweet",
                    "max_results": max(10, min(limit, 100)),
                    "tweet.fields": "created_at,author_id,referenced_tweets",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return [t for t in (data.get("data") or []) if isinstance(t, dict)]

    @read_retry
    async def get_tweets_metrics(
        self, access_token: str, ids: list[str]
    ) -> dict[str, dict[str, int]]:
        """Batched public_metrics read. Caller must pass <= 100 ids per call."""
        if not ids:
            return {}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_TWITTER_API}/tweets",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "ids": ",".join(ids[:100]),
                    "tweet.fields": "public_metrics",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        out: dict[str, dict[str, int]] = {}
        for tweet in data.get("data") or []:
            metrics = tweet.get("public_metrics") or {}
            # X's REAL field names. Passed through verbatim — no aliasing, so a
            # field X renames shows up as a missing key rather than a silent zero.
            out[str(tweet.get("id"))] = {
                k: v
                for k, v in metrics.items()
                if k in ("like_count", "retweet_count", "quote_count", "reply_count")
                and isinstance(v, int)
            }
        return out

    # ── Helpers ──────────────────────────────────────────
    async def _get_me(self, access_token: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_TWITTER_API}/users/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()["data"]
