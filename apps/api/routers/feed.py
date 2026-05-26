"""Feed router: unified view of posts from all connected platforms."""

import re
import uuid
from datetime import date, datetime, time, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_user
from apps.api.models.database import get_db
from apps.api.models.post import Post
from apps.api.models.social_account import Platform, SocialAccount
from apps.api.models.user import User
from apps.api.schemas.posts import ImportPostRequest, PostListResponse, PostResponse
from apps.api.services.sync import sync_user_accounts

router = APIRouter(prefix="/feed", tags=["feed"])


@router.get("", response_model=PostListResponse)
async def get_feed(
    platform: Optional[Platform] = None,
    date_from: Optional[date] = Query(None, description="Filter posts from this date (inclusive)"),
    date_to: Optional[date] = Query(None, description="Filter posts up to this date (inclusive)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get unified feed of posts from the authenticated user's connected platforms."""
    # Get user's account IDs for scoping
    acct_result = await db.execute(
        select(SocialAccount.id).where(
            SocialAccount.user_id == current_user.id,
            SocialAccount.is_active.is_(True),
        )
    )
    account_ids = [row[0] for row in acct_result.all()]

    query = select(Post).where(Post.social_account_id.in_(account_ids))
    count_query = select(func.count(Post.id)).where(Post.social_account_id.in_(account_ids))

    if platform:
        query = query.where(Post.platform == platform)
        count_query = count_query.where(Post.platform == platform)

    # Date range filter (inclusive on both ends)
    if date_from:
        dt_from = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        query = query.where(Post.posted_at >= dt_from)
        count_query = count_query.where(Post.posted_at >= dt_from)
    if date_to:
        dt_to = datetime.combine(date_to, time.max, tzinfo=timezone.utc)
        query = query.where(Post.posted_at <= dt_to)
        count_query = count_query.where(Post.posted_at <= dt_to)

    # Total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Paginated results
    query = query.order_by(desc(Post.posted_at))
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    posts = result.scalars().all()

    return PostListResponse(
        posts=[
            PostResponse(
                id=str(p.id),
                platform=p.platform,
                author_name=p.author_name,
                author_username=p.author_username,
                author_avatar_url=p.author_avatar_url,
                content=p.content,
                media_urls=p.media_urls,
                post_url=p.post_url,
                commented=p.commented,
                posted_at=p.posted_at,
                created_at=p.created_at,
            )
            for p in posts
        ],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post("/sync")
async def trigger_sync(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger a feed sync for the authenticated user's connected accounts."""
    counts = await sync_user_accounts(db, current_user.id)
    total = sum(counts.values())
    return {"message": f"Synced {total} new posts", "breakdown": counts}


def _extract_tweet_id(url: str) -> Optional[str]:
    """Extract tweet ID from a Twitter/X URL."""
    match = re.search(r"(?:twitter\.com|x\.com)/\w+/status/(\d+)", url)
    return match.group(1) if match else None


@router.post("/import", response_model=PostResponse)
async def import_post(
    body: ImportPostRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Import a post by URL so you can generate a reply to it."""
    # Find a connected account for this platform owned by the current user
    result = await db.execute(
        select(SocialAccount).where(
            SocialAccount.platform == body.platform,
            SocialAccount.user_id == current_user.id,
            SocialAccount.is_active == True,
        ).limit(1)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(
            status_code=400,
            detail=f"No {body.platform.value} account connected. Connect one first.",
        )

    # Extract platform post ID from URL
    platform_post_id = ""
    if body.platform == Platform.twitter:
        platform_post_id = _extract_tweet_id(body.url) or ""

    if not platform_post_id:
        platform_post_id = f"imported_{uuid.uuid4().hex[:12]}"

    # Check if already imported
    existing = await db.execute(
        select(Post).where(Post.platform_post_id == platform_post_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="This post is already in your feed.")

    post = Post(
        id=uuid.uuid4(),
        social_account_id=account.id,
        platform=body.platform,
        platform_post_id=platform_post_id,
        author_name=body.author_name or "Unknown",
        author_username=body.author_username or "unknown",
        content=body.content or "(no content provided)",
        post_url=body.url,
        posted_at=datetime.now(timezone.utc),
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)

    return PostResponse(
        id=str(post.id),
        platform=post.platform,
        author_name=post.author_name,
        author_username=post.author_username,
        author_avatar_url=post.author_avatar_url,
        content=post.content,
        media_urls=post.media_urls,
        post_url=post.post_url,
        commented=post.commented,
        posted_at=post.posted_at,
        created_at=post.created_at,
    )
