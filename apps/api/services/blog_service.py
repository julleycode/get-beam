"""Blog CMS business logic: slugs, reading time, SEO meta fallbacks.

Pure helpers + DB-aware slug uniqueness. No external API calls.
"""

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.blog_post import BlogPost

_WORDS_PER_MINUTE = 200
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_TAG_STRIP = re.compile(r"<[^>]+>")


def slugify(value: str) -> str:
    """Lowercase, hyphenate, strip non-alphanumerics. Empty → 'post'."""
    slug = _SLUG_STRIP.sub("-", value.strip().lower()).strip("-")
    return slug or "post"


async def unique_slug(
    db: AsyncSession, base: str, *, exclude_id: uuid.UUID | None = None
) -> str:
    """Return `base`, or `base-2`, `base-3`, ... until unused.

    `exclude_id` lets an update keep its own slug without colliding with itself.
    """
    candidate = base
    suffix = 2
    while True:
        stmt = select(BlogPost.id).where(BlogPost.slug == candidate)
        if exclude_id is not None:
            stmt = stmt.where(BlogPost.id != exclude_id)
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing is None:
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


def reading_time_minutes(body_markdown: str) -> int:
    """Estimate reading time in minutes (~200 wpm), floor of 1."""
    words = len(body_markdown.split())
    return max(1, round(words / _WORDS_PER_MINUTE)) if words else 1


def _plain_excerpt(body_markdown: str, limit: int = 155) -> str:
    """Crude meta-description fallback: strip tags, collapse whitespace, clip."""
    text = _TAG_STRIP.sub(" ", body_markdown)
    text = " ".join(text.split())
    return text[:limit].rstrip()


def resolve_seo_meta(
    *,
    title: str,
    excerpt: str | None,
    body_markdown: str,
    meta_title: str | None,
    meta_description: str | None,
    og_image_url: str | None,
    cover_image_url: str | None,
) -> tuple[str, str | None, str | None]:
    """Compute (meta_title, meta_description, og_image_url) with fallbacks."""
    resolved_title = (meta_title or title)[:255]
    resolved_desc = meta_description or excerpt or _plain_excerpt(body_markdown) or None
    if resolved_desc:
        resolved_desc = resolved_desc[:320]
    resolved_og = og_image_url or cover_image_url
    return resolved_title, resolved_desc, resolved_og


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
