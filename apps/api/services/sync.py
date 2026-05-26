"""Sync service: fetches new posts/messages from all connected platforms."""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.post import Post
from apps.api.models.social_account import SocialAccount
from apps.api.services.encryption import decrypt_token
from apps.api.services.platforms import get_platform_service

logger = structlog.get_logger()


async def sync_account_feed(
    db: AsyncSession, account: SocialAccount
) -> int:
    """Fetch new feed posts for a single social account.

    Returns the number of new posts added.
    """
    service = get_platform_service(account.platform)
    new_count = 0

    # Decrypt the stored token before using it
    access_token = decrypt_token(account.access_token)

    try:
        feed_posts = await service.fetch_feed(access_token, limit=20)
    except Exception:
        logger.exception(
            "sync_feed_failed",
            platform=account.platform.value,
            account_id=str(account.id),
        )
        return 0

    if not feed_posts:
        return 0

    # Batch-check which posts already exist instead of N individual SELECTs
    incoming_ids = [fp.platform_post_id for fp in feed_posts]
    existing_result = await db.execute(
        select(Post.platform_post_id).where(
            Post.platform_post_id.in_(incoming_ids)
        )
    )
    existing_ids = set(existing_result.scalars().all())

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
            posted_at=fp.posted_at,
        )
        db.add(post)
        new_count += 1

    if new_count > 0:
        await db.commit()
        logger.info(
            "sync_feed_complete",
            platform=account.platform.value,
            new_posts=new_count,
        )

    return new_count


async def sync_user_accounts(
    db: AsyncSession, user_id: uuid.UUID
) -> dict[str, int]:
    """Sync feed for a specific user's active accounts. Returns counts per platform."""
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
            # Error isolation: one account failure doesn't crash the rest
            logger.exception(
                "sync_account_error",
                platform=account.platform.value,
                account_id=str(account.id),
            )
            counts[f"{account.platform.value}:{account.username}"] = 0

    return counts


async def sync_all_accounts(db: AsyncSession) -> dict[str, int]:
    """Sync feed for every active social account. Returns counts per platform.

    Used by the background scheduler — syncs all users.
    """
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
            # Error isolation: one account failure doesn't crash the rest
            logger.exception(
                "sync_account_error",
                platform=account.platform.value,
                account_id=str(account.id),
            )
            counts[f"{account.platform.value}:{account.username}"] = 0

    return counts
