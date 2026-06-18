"""Blog CMS post model.

Distinct from `Post` (social-media posts in models/post.py). This is the
marketing blog at getbeam.fyi/blog — the content surface the SEO Command
Center audits and builds backlinks to.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base

# Status values for a blog post lifecycle.
POST_STATUSES = ("draft", "scheduled", "published", "archived")


class BlogPost(Base):
    """A marketing blog article. Inherits id / created_at / updated_at from Base."""

    __tablename__ = "blog_posts"

    # Platform-owned marketing blog → site is optional. Nullable FK keeps the
    # door open for per-site blogs later without forcing a tenant now.
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), nullable=True, index=True
    )

    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_markdown: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    author_name: Mapped[str] = mapped_column(String(255), default="Beam")
    cover_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    # SEO fields — the on-page auditor (P3) grades pages against these.
    # The phrase the post should rank for; also drives the editor's SEO checklist.
    focus_keyword: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(String(320), nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    og_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    reading_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # When set with status="scheduled", a background job publishes the post
    # once this time passes.
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
