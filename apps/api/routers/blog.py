"""Blog CMS — public read (published only) + admin CRUD/publish.

Backend for getbeam.fyi/blog. Public endpoints are unauthenticated and only
expose published posts. Write + draft access requires admin.
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import require_admin
from apps.api.models.blog_post import BlogPost
from apps.api.models.database import get_db
from apps.api.models.user import User
from apps.api.schemas.blog import (
    BlogPostAdminListResponse,
    BlogPostAdminOut,
    BlogPostCreate,
    BlogPostListResponse,
    BlogPostOut,
    BlogPostSchedule,
    BlogPostUpdate,
)
from apps.api.services import blog_service, blog_storage

logger = structlog.get_logger()

router = APIRouter(tags=["blog"])


def _apply_seo_meta(post: BlogPost) -> None:
    """Populate meta_title / meta_description / og_image_url with fallbacks."""
    post.meta_title, post.meta_description, post.og_image_url = (
        blog_service.resolve_seo_meta(
            title=post.title,
            excerpt=post.excerpt,
            body_markdown=post.body_markdown or "",
            meta_title=post.meta_title,
            meta_description=post.meta_description,
            og_image_url=post.og_image_url,
            cover_image_url=post.cover_image_url,
        )
    )


# ── Public ─────────────────────────────────────────────────────────────


@router.get("/posts", response_model=BlogPostListResponse)
async def list_published_posts(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    tag: str | None = Query(default=None),
) -> BlogPostListResponse:
    """Published posts, newest first. Optionally filtered to a single tag."""
    conds = [BlogPost.status == "published"]
    if tag:
        conds.append(BlogPost.tags.contains([tag]))
    total = (
        await db.execute(select(func.count()).select_from(BlogPost).where(*conds))
    ).scalar_one()
    rows = (
        await db.execute(
            select(BlogPost)
            .where(*conds)
            .order_by(desc(BlogPost.published_at))
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return BlogPostListResponse(
        posts=[BlogPostOut.model_validate(p) for p in rows], total=total
    )


@router.get("/posts/{slug}", response_model=BlogPostOut)
async def get_published_post(
    slug: str, db: AsyncSession = Depends(get_db)
) -> BlogPostOut:
    """Fetch a single published post by slug. 404 if missing or not published."""
    post = (
        await db.execute(
            select(BlogPost).where(
                BlogPost.slug == slug, BlogPost.status == "published"
            )
        )
    ).scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    return BlogPostOut.model_validate(post)


# ── Admin ──────────────────────────────────────────────────────────────


@router.get("/admin/posts", response_model=BlogPostAdminListResponse)
async def list_all_posts(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> BlogPostAdminListResponse:
    """All posts (any status), newest first. Admin only."""
    total = (
        await db.execute(select(func.count()).select_from(BlogPost))
    ).scalar_one()
    rows = (
        await db.execute(
            select(BlogPost)
            .order_by(desc(BlogPost.created_at))
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return BlogPostAdminListResponse(
        posts=[BlogPostAdminOut.model_validate(p) for p in rows], total=total
    )


@router.post("/posts", response_model=BlogPostAdminOut, status_code=status.HTTP_201_CREATED)
async def create_post(
    payload: BlogPostCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> BlogPostAdminOut:
    """Create a new draft post."""
    base = blog_service.slugify(payload.slug or payload.title)
    slug = await blog_service.unique_slug(db, base)

    post = BlogPost(
        slug=slug,
        title=payload.title,
        body_markdown=payload.body_markdown or "",
        excerpt=payload.excerpt,
        author_name=payload.author_name or "Beam",
        cover_image_url=payload.cover_image_url,
        tags=payload.tags,
        focus_keyword=payload.focus_keyword,
        meta_title=payload.meta_title,
        meta_description=payload.meta_description,
        canonical_url=payload.canonical_url,
        og_image_url=payload.og_image_url,
        status="draft",
    )
    post.reading_time_minutes = blog_service.reading_time_minutes(post.body_markdown)
    _apply_seo_meta(post)

    db.add(post)
    await db.commit()
    await db.refresh(post)
    logger.info("blog_post_created", post_id=str(post.id), slug=post.slug)
    return BlogPostAdminOut.model_validate(post)


async def _get_or_404(db: AsyncSession, post_id: uuid.UUID) -> BlogPost:
    post = (
        await db.execute(select(BlogPost).where(BlogPost.id == post_id))
    ).scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    return post


@router.put("/posts/{post_id}", response_model=BlogPostAdminOut)
async def update_post(
    post_id: uuid.UUID,
    payload: BlogPostUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> BlogPostAdminOut:
    """Partial update. Re-slugs only if slug/title explicitly changed."""
    post = await _get_or_404(db, post_id)
    data = payload.model_dump(exclude_unset=True)

    if "slug" in data and data["slug"]:
        base = blog_service.slugify(data.pop("slug"))
        post.slug = await blog_service.unique_slug(db, base, exclude_id=post.id)
    elif "title" in data and data["title"] and not post.slug:
        post.slug = await blog_service.unique_slug(
            db, blog_service.slugify(data["title"]), exclude_id=post.id
        )

    for field, value in data.items():
        setattr(post, field, value)

    post.reading_time_minutes = blog_service.reading_time_minutes(post.body_markdown or "")
    _apply_seo_meta(post)

    await db.commit()
    await db.refresh(post)
    logger.info("blog_post_updated", post_id=str(post.id), slug=post.slug)
    return BlogPostAdminOut.model_validate(post)


@router.post("/posts/{post_id}/publish", response_model=BlogPostAdminOut)
async def publish_post(
    post_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> BlogPostAdminOut:
    """Set status=published. Stamp published_at only on first publish."""
    post = await _get_or_404(db, post_id)
    post.status = "published"
    post.scheduled_for = None
    if post.published_at is None:
        post.published_at = blog_service.now_utc()
    await db.commit()
    await db.refresh(post)
    logger.info("blog_post_published", post_id=str(post.id), slug=post.slug)
    return BlogPostAdminOut.model_validate(post)


@router.post("/posts/{post_id}/unpublish", response_model=BlogPostAdminOut)
async def unpublish_post(
    post_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> BlogPostAdminOut:
    """Revert to draft. Keeps published_at for audit history."""
    post = await _get_or_404(db, post_id)
    post.status = "draft"
    post.scheduled_for = None
    await db.commit()
    await db.refresh(post)
    logger.info("blog_post_unpublished", post_id=str(post.id), slug=post.slug)
    return BlogPostAdminOut.model_validate(post)


@router.post("/posts/{post_id}/schedule", response_model=BlogPostAdminOut)
async def schedule_post(
    post_id: uuid.UUID,
    payload: BlogPostSchedule,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> BlogPostAdminOut:
    """Schedule a post to auto-publish at a future time.

    The `publish_due_posts` background job flips it to published once the time
    passes. Scheduling a time in the past publishes on the job's next run.
    """
    post = await _get_or_404(db, post_id)
    post.status = "scheduled"
    post.scheduled_for = payload.scheduled_for
    await db.commit()
    await db.refresh(post)
    logger.info(
        "blog_post_scheduled",
        post_id=str(post.id),
        slug=post.slug,
        scheduled_for=payload.scheduled_for.isoformat(),
    )
    return BlogPostAdminOut.model_validate(post)


@router.post("/upload")
async def upload_blog_image(
    file: UploadFile = File(...),
    _admin: User = Depends(require_admin),
) -> dict[str, str]:
    """Upload a blog image to Supabase Storage. Returns its public URL."""
    data = await file.read()
    try:
        url = await blog_storage.upload_image(data, file.content_type or "")
    except blog_storage.UploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {"url": url}


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    post_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> None:
    """Hard delete a post."""
    post = await _get_or_404(db, post_id)
    await db.delete(post)
    await db.commit()
    logger.info("blog_post_deleted", post_id=str(post_id))
