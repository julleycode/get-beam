from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from apps.api.models.social_account import Platform


class PostResponse(BaseModel):
    id: str
    platform: Platform
    author_name: str
    author_username: str
    author_avatar_url: Optional[str] = None
    content: Optional[str] = None
    media_urls: Optional[list[str]] = None
    post_url: Optional[str] = None
    source: str = "following"
    commented: bool
    posted_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class PostListResponse(BaseModel):
    posts: list[PostResponse]
    total: int
    page: int
    per_page: int


class ImportPostRequest(BaseModel):
    """Import a post by URL (e.g. paste a tweet link to reply to it)."""
    url: str
    platform: Platform
    content: str = ""  # Optional: user can paste the post text
    author_name: str = ""
    author_username: str = ""
