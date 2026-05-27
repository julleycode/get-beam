"""Twitter public scraper via syndication API.

Fetches tweets from any public Twitter profile WITHOUT authentication.
Uses Twitter's embed/syndication endpoint — the same one that powers
embedded tweet widgets on websites.

No API keys, no OAuth, no cookies, no Playwright needed.
"""

import re
import json
from datetime import datetime, timezone

import httpx
import structlog

from apps.api.services.platforms.base import FeedPost

logger = structlog.get_logger()

_SYNDICATION_URL = "https://syndication.twitter.com/srv/timeline-profile/screen-name/{username}"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


async def fetch_user_tweets(username: str, *, limit: int = 20) -> list[FeedPost]:
    """Fetch recent tweets from a public Twitter profile.

    Args:
        username: Twitter handle (without @).
        limit: Max tweets to return.

    Returns:
        List of FeedPost objects, newest first.
    """
    clean = username.lstrip("@").strip()
    if not clean:
        return []

    url = _SYNDICATION_URL.format(username=clean)

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=_HEADERS)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            logger.info("twitter_scraper_user_not_found", username=clean)
            return []
        logger.warning("twitter_scraper_http_error", username=clean, status=e.response.status_code)
        return []
    except httpx.HTTPError as e:
        logger.warning("twitter_scraper_network_error", username=clean, error=str(e))
        return []

    # Extract __NEXT_DATA__ JSON from HTML
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        resp.text,
    )
    if not match:
        logger.warning("twitter_scraper_no_next_data", username=clean)
        return []

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        logger.warning("twitter_scraper_json_parse_error", username=clean)
        return []

    entries = (
        data.get("props", {})
        .get("pageProps", {})
        .get("timeline", {})
        .get("entries", [])
    )

    posts: list[FeedPost] = []
    for entry in entries:
        if entry.get("type") != "tweet":
            continue

        tweet = entry.get("content", {}).get("tweet", {})
        if not tweet:
            continue

        tweet_id = tweet.get("id_str") or tweet.get("conversation_id_str", "")
        if not tweet_id:
            continue

        user = tweet.get("user", {})
        text = tweet.get("full_text") or tweet.get("text", "")

        # Parse created_at: "Tue May 26 15:44:05 +0000 2026"
        try:
            posted_at = datetime.strptime(
                tweet["created_at"], "%a %b %d %H:%M:%S %z %Y"
            )
        except (KeyError, ValueError):
            posted_at = datetime.now(timezone.utc)

        # Skip retweets
        if text.startswith("RT @"):
            continue

        posts.append(
            FeedPost(
                platform_post_id=tweet_id,
                author_name=user.get("name", clean),
                author_username=user.get("screen_name", clean),
                author_avatar_url=user.get("profile_image_url_https"),
                content=text,
                post_url=f"https://x.com/{user.get('screen_name', clean)}/status/{tweet_id}",
                posted_at=posted_at,
            )
        )

        if len(posts) >= limit:
            break

    logger.info("twitter_scraper_ok", username=clean, tweets=len(posts))
    return posts


async def fetch_multiple_users_tweets(
    usernames: list[str], *, limit_per_user: int = 5, total_limit: int = 30
) -> list[FeedPost]:
    """Fetch tweets from multiple users, merge and sort by date.

    Args:
        usernames: List of Twitter handles.
        limit_per_user: Max tweets per user.
        total_limit: Max total tweets to return.

    Returns:
        Merged list sorted by posted_at descending.
    """
    all_posts: list[FeedPost] = []

    for username in usernames[:20]:  # Cap at 20 users to avoid rate limits
        try:
            posts = await fetch_user_tweets(username, limit=limit_per_user)
            all_posts.extend(posts)
        except Exception:
            logger.exception("twitter_scraper_user_failed", username=username)

    # Sort by date, newest first
    all_posts.sort(key=lambda p: p.posted_at, reverse=True)
    return all_posts[:total_limit]


# ── OAuth-based fetching (uses the user's own access token) ──

async def fetch_own_tweets_oauth(
    access_token: str, platform_user_id: str, username: str, *, limit: int = 20
) -> list[FeedPost]:
    """Fetch the authenticated user's own tweets via Twitter API v2.

    Uses the OAuth 2.0 user token obtained when the user connected their account.
    Twitter Free tier allows GET /2/users/:id/tweets for own tweets.

    Args:
        access_token: Decrypted OAuth access token.
        platform_user_id: Twitter user ID (numeric).
        username: Twitter handle (for constructing post URLs).
        limit: Max tweets to return.

    Returns:
        List of FeedPost objects, newest first.
    """
    if not access_token or not platform_user_id:
        return []

    url = f"https://api.twitter.com/2/users/{platform_user_id}/tweets"
    params = {
        "max_results": min(limit, 100),
        "tweet.fields": "created_at,author_id,text",
        "exclude": "retweets",
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers, params=params)

            if resp.status_code == 403:
                logger.warning("twitter_oauth_forbidden", hint="Free tier may not allow this endpoint")
                return []

            resp.raise_for_status()
            data = resp.json()

        tweets = data.get("data", [])
        if not tweets:
            logger.info("twitter_oauth_no_tweets", user_id=platform_user_id)
            return []

        posts: list[FeedPost] = []
        for tweet in tweets:
            tweet_id = tweet.get("id", "")
            text = tweet.get("text", "")

            try:
                posted_at = datetime.fromisoformat(tweet["created_at"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                posted_at = datetime.now(timezone.utc)

            posts.append(
                FeedPost(
                    platform_post_id=tweet_id,
                    author_name=username,
                    author_username=username,
                    author_avatar_url=None,
                    content=text,
                    post_url=f"https://x.com/{username}/status/{tweet_id}",
                    posted_at=posted_at,
                )
            )

        logger.info("twitter_oauth_ok", username=username, tweets=len(posts))
        return posts

    except httpx.HTTPStatusError as e:
        logger.warning("twitter_oauth_http_error", status=e.response.status_code, user_id=platform_user_id)
        return []
    except httpx.HTTPError as e:
        logger.warning("twitter_oauth_network_error", error=str(e))
        return []


# ── OAuth: fetch list of accounts the user follows ──

async def fetch_following_list_oauth(
    access_token: str, platform_user_id: str, *, limit: int = 50
) -> list[dict]:
    """Fetch the list of accounts the authenticated user follows via Twitter API v2.

    Twitter Free tier: GET /2/users/:id/following may be restricted.
    Twitter Basic ($100/mo) tier: allowed.

    Returns:
        List of dicts with 'id', 'name', 'username' for each followed account.
    """
    if not access_token or not platform_user_id:
        return []

    url = f"https://api.twitter.com/2/users/{platform_user_id}/following"
    params = {
        "max_results": min(limit, 1000),
        "user.fields": "name,username,profile_image_url",
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers, params=params)

            if resp.status_code == 403:
                logger.warning(
                    "twitter_following_list_forbidden",
                    hint="Free tier may not support /following endpoint",
                )
                return []

            resp.raise_for_status()
            data = resp.json()

        users = data.get("data", [])
        logger.info("twitter_following_list_ok", count=len(users))
        return [
            {
                "id": u.get("id", ""),
                "name": u.get("name", ""),
                "username": u.get("username", ""),
                "profile_image_url": u.get("profile_image_url", ""),
            }
            for u in users
        ]

    except httpx.HTTPStatusError as e:
        logger.warning(
            "twitter_following_list_http_error",
            status=e.response.status_code,
        )
        return []
    except httpx.HTTPError as e:
        logger.warning("twitter_following_list_network_error", error=str(e))
        return []
