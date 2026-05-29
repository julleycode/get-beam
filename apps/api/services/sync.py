"""Sync service: fetches posts for the engagement feed.

Waterfall strategy:
1. **OAuth API** — uses the user's own Twitter access token (best for own tweets)
2. **Syndication scraper** — public endpoint, no auth, fast (for public profiles)
3. **Playwright fallback** — browser scraping with saved cookies (if available)

Feed sources:
- **visitors**: tweets from people identified by EasyTrack (enrichment → twitter_handle)
- **following**: tweets from people the user follows (Playwright only — needs cookies)
- **my_posts**: the user's own tweets
"""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.post import Post
from apps.api.models.site import Site
from apps.api.models.social_account import Platform, SocialAccount
from apps.api.services.platforms.twitter_scraper import (
    fetch_user_tweets,
    fetch_multiple_users_tweets,
    fetch_own_tweets_oauth,
    fetch_following_list_oauth,
)

logger = structlog.get_logger()


# ── Token helpers ──

def _decrypt_access_token(account: SocialAccount) -> str | None:
    """Decrypt the OAuth access token from a social account (no refresh)."""
    if not account.access_token:
        return None
    try:
        from apps.api.services.encryption import decrypt_token
        return decrypt_token(account.access_token)
    except Exception:
        logger.warning("decrypt_token_failed", account=account.username)
        return None


async def _get_fresh_token(db: AsyncSession, account: SocialAccount) -> str | None:
    """Get a valid access token, refreshing if expired."""
    if not account.access_token:
        return None
    try:
        from apps.api.services.sender import _refresh_if_expired
        return await _refresh_if_expired(db, account)
    except Exception:
        logger.warning("token_refresh_failed_in_sync", account=account.username)
        return _decrypt_access_token(account)


# ── Playwright helpers (lazy import, graceful if unavailable) ──

async def _playwright_fetch_timeline(limit: int = 20):
    """Try Playwright browser scraping. Returns posts or empty list."""
    try:
        from apps.api.services.platforms.twitter_browser import (
            TwitterBrowserPoster,
            TwitterBrowserError,
        )
        poster = TwitterBrowserPoster()
        posts = await poster.fetch_timeline(limit=limit)
        logger.info("playwright_timeline_ok", count=len(posts))
        return posts
    except ImportError:
        logger.debug("playwright_not_installed")
        return []
    except Exception as exc:
        logger.warning("playwright_timeline_failed", error=str(exc))
        return []


async def _playwright_fetch_user_tweets(username: str, limit: int = 20):
    """Fallback: use Playwright to scrape a specific user's profile page."""
    try:
        from apps.api.services.platforms.twitter_browser import (
            TwitterBrowserPoster,
            TwitterBrowserError,
        )
        poster = TwitterBrowserPoster()
        # Playwright fetches /home timeline, not a specific user.
        # For user-specific, syndication is better. Only use Playwright
        # as timeline fallback.
        return []
    except Exception:
        return []


# ── Visitor posts: tweets from enriched visitors ──────────

async def sync_visitor_posts(
    db: AsyncSession, account: SocialAccount
) -> int:
    """Fetch recent tweets from identified visitors' Twitter handles.

    Waterfall: syndication scraper (per handle) → done.
    Playwright can't search by handle, so no fallback here.
    """
    if account.platform != Platform.twitter:
        return 0

    result = await db.execute(
        select(EnrichmentProfile.twitter_handle)
        .join(Site, Site.site_id == EnrichmentProfile.site_id)
        .where(
            Site.user_id == account.user_id,
            EnrichmentProfile.twitter_handle.isnot(None),
            EnrichmentProfile.twitter_handle != "",
        )
        .limit(50)
    )
    handles = [row[0] for row in result.all() if row[0]]

    if not handles:
        logger.info("sync_visitor_posts_no_handles", account=account.username)
        return 0

    try:
        feed_posts = await fetch_multiple_users_tweets(
            handles, limit_per_user=5, total_limit=30
        )
    except Exception:
        logger.exception("sync_visitor_posts_failed", handles_count=len(handles))
        return 0

    return await _save_posts(db, account, feed_posts, source="visitors")


# ── Following feed: tweets from people the user follows ───

async def sync_following_feed(
    db: AsyncSession, account: SocialAccount
) -> int:
    """Fetch tweets from accounts the user follows.

    Waterfall:
    1. OAuth API to get following list → syndication scraper for each handle
    2. Playwright timeline fallback (if cookies available)

    The OAuth approach works on Basic tier ($100/mo). On Free tier,
    /following endpoint may return 403 — falls through to Playwright.
    """
    if account.platform != Platform.twitter:
        return 0

    own_username = (account.username or "").lower()
    feed_posts: list = []

    # 1. Try OAuth: get following list → scrape each handle via syndication
    token = await _get_fresh_token(db, account)
    if token and account.platform_user_id:
        following_users = await fetch_following_list_oauth(
            access_token=token,
            platform_user_id=account.platform_user_id,
            limit=30,  # top 30 accounts user follows
        )
        if following_users:
            handles = [u["username"] for u in following_users if u.get("username")]
            logger.info(
                "sync_following_handles",
                count=len(handles),
                sample=handles[:5],
            )
            try:
                feed_posts = await fetch_multiple_users_tweets(
                    handles, limit_per_user=3, total_limit=50
                )
            except Exception:
                logger.exception("sync_following_scrape_failed")
                feed_posts = []

    # 2. Fallback: Playwright timeline (needs browser cookies)
    if not feed_posts:
        feed_posts = await _playwright_fetch_timeline(limit=20)

    if not feed_posts:
        return 0

    # Filter out own tweets — those go to my_posts
    following_posts = [
        fp for fp in feed_posts
        if fp.author_username.lower() != own_username
    ]

    return await _save_posts(db, account, following_posts, source="following")


# ── My posts: the user's own tweets ──────────────────────

async def sync_my_posts(
    db: AsyncSession, account: SocialAccount
) -> int:
    """Fetch the user's own tweets.

    Waterfall:
    1. OAuth API (user's own access token — works on Free tier for own tweets)
    2. Syndication scraper (public endpoint — works for large/public accounts)
    3. Playwright fallback (browser scraping — needs cookies)
    """
    if account.platform != Platform.twitter:
        return 0

    own_username = account.username or ""
    if not own_username:
        return 0

    feed_posts: list = []

    # 1. Try OAuth API (best — uses the user's own token, auto-refreshed)
    token = await _get_fresh_token(db, account)
    if token and account.platform_user_id:
        try:
            feed_posts = await fetch_own_tweets_oauth(
                access_token=token,
                platform_user_id=account.platform_user_id,
                username=own_username,
                limit=20,
            )
        except Exception:
            logger.warning("sync_my_posts_oauth_failed", account=own_username)
            feed_posts = []

    # 2. Fallback: syndication scraper (fast, no auth, public profiles only)
    if not feed_posts:
        try:
            feed_posts = await fetch_user_tweets(own_username, limit=20)
        except Exception:
            logger.warning("sync_my_posts_scraper_failed", account=own_username)
            feed_posts = []

    # 3. Fallback: Playwright (slower, needs cookies)
    if not feed_posts:
        logger.info("sync_my_posts_trying_playwright", account=own_username)
        all_timeline = await _playwright_fetch_timeline(limit=30)
        feed_posts = [
            fp for fp in all_timeline
            if fp.author_username.lower() == own_username.lower()
        ]

    return await _save_posts(db, account, feed_posts, source="my_posts")


# ── Shared helpers ────────────────────────────────────────

async def _save_posts(
    db: AsyncSession,
    account: SocialAccount,
    feed_posts: list,
    source: str,
) -> int:
    """Deduplicate and save posts to DB. Returns count of new posts."""
    if not feed_posts:
        return 0

    incoming_ids = [fp.platform_post_id for fp in feed_posts]
    existing_result = await db.execute(
        select(Post.platform_post_id).where(
            Post.platform_post_id.in_(incoming_ids)
        )
    )
    existing_ids = set(existing_result.scalars().all())

    new_count = 0
    for fp in feed_posts:
        if fp.platform_post_id in existing_ids:
            continue

        post = Post(
            id=uuid.uuid4(),
            social_account_id=account.id,
            platform=account.platform,
            platform_post_id=fp.platform_post_id,
            author_name=fp.author_name,
            author_username=fp.author_username,
            author_avatar_url=fp.author_avatar_url,
            content=fp.content,
            media_urls=fp.media_urls or None,
            post_url=fp.post_url,
            source=source,
            posted_at=fp.posted_at,
        )
        db.add(post)
        new_count += 1

    if new_count > 0:
        await db.commit()
        logger.info(
            "sync_posts_saved",
            platform=account.platform.value,
            source=source,
            new_posts=new_count,
        )

    return new_count


async def sync_account_feed(
    db: AsyncSession, account: SocialAccount
) -> int:
    """Sync all feed sources for one account."""
    total = 0

    # 1. Visitor posts (syndication scraper)
    total += await sync_visitor_posts(db, account)

    # 2. Following feed (Playwright only — if cookies available)
    total += await sync_following_feed(db, account)

    # 3. Own posts (syndication → Playwright fallback)
    total += await sync_my_posts(db, account)

    return total


async def sync_user_accounts(
    db: AsyncSession, user_id: uuid.UUID
) -> dict[str, int]:
    """Sync feed for a specific user's active accounts."""
    result = await db.execute(
        select(SocialAccount).where(
            SocialAccount.user_id == user_id,
            SocialAccount.is_active.is_(True),
        )
    )
    accounts = result.scalars().all()

    counts: dict[str, int] = {}
    for account in accounts:
        try:
            n = await sync_account_feed(db, account)
            key = f"{account.platform.value}:{account.username}"
            counts[key] = n
        except Exception:
            logger.exception(
                "sync_account_error",
                platform=account.platform.value,
                account_id=str(account.id),
            )
            counts[f"{account.platform.value}:{account.username}"] = 0

    return counts


async def sync_all_accounts(db: AsyncSession) -> dict[str, int]:
    """Sync feed for every active social account (background scheduler)."""
    result = await db.execute(
        select(SocialAccount).where(SocialAccount.is_active.is_(True))
    )
    accounts = result.scalars().all()

    counts: dict[str, int] = {}
    for account in accounts:
        try:
            n = await sync_account_feed(db, account)
            key = f"{account.platform.value}:{account.username}"
            counts[key] = n
        except Exception:
            logger.exception(
                "sync_account_error",
                platform=account.platform.value,
                account_id=str(account.id),
            )
            counts[f"{account.platform.value}:{account.username}"] = 0

    return counts
