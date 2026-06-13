"""Pydantic schemas for the blog CMS (`/api/v1/blog`)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class BlogPostCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body_markdown: str = Field(default="", max_length=200_000)
    excerpt: str | None = Field(default=None, max_length=1000)
    author_name: str | None = Field(default=None, max_length=255)
    cover_image_url: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None)
    slug: str | None = Field(default=None, max_length=255)
    # SEO overrides — fall back to title/excerpt/cover when omitted.
    meta_title: str | None = Field(default=None, max_length=255)
    meta_description: str | None = Field(default=None, max_length=320)
    canonical_url: str | None = Field(default=None, max_length=2000)
    og_image_url: str | None = Field(default=None, max_length=2000)


class BlogPostUpdate(BaseModel):
    """All fields optional — partial update."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    body_markdown: str | None = Field(default=None, max_length=200_000)
    excerpt: str | None = Field(default=None, max_length=1000)
    author_name: str | None = Field(default=None, max_length=255)
    cover_image_url: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None)
    slug: str | None = Field(default=None, max_length=255)
    meta_title: str | None = Field(default=None, max_length=255)
    meta_description: str | None = Field(default=None, max_length=320)
    canonical_url: str | None = Field(default=None, max_length=2000)
    og_image_url: str | None = Field(default=None, max_length=2000)


class BlogPostOut(BaseModel):
    """Public-facing post. Excludes status / site_id / updated_at."""

    id: uuid.UUID
    slug: str
    title: str
    excerpt: str | None
    body_markdown: str
    author_name: str
    cover_image_url: str | None
    tags: list[str] | None
    meta_title: str | None
    meta_description: str | None
    canonical_url: str | None
    og_image_url: str | None
    reading_time_minutes: int | None
    published_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BlogPostAdminOut(BlogPostOut):
    """Admin view — adds lifecycle + tenant fields."""

    status: str
    site_id: uuid.UUID | None
    updated_at: datetime | None
    scheduled_for: datetime | None


class BlogPostSchedule(BaseModel):
    """Schedule a post to auto-publish at a future time."""

    scheduled_for: datetime


class BlogPostListResponse(BaseModel):
    posts: list[BlogPostOut]
    total: int


class BlogPostAdminListResponse(BaseModel):
    posts: list[BlogPostAdminOut]
    total: int
