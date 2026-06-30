"""Pydantic schemas for the changelog (`/api/v1/changelog`)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["new", "improved", "fixed"]


class ChangelogEntryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(default="", max_length=2000)
    category: Category = "new"


class ChangelogEntryUpdate(BaseModel):
    """All fields optional — partial update."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    body: str | None = Field(default=None, max_length=2000)
    category: Category | None = None


class ChangelogEntryOut(BaseModel):
    """Public-facing entry. Excludes status / updated_at."""

    id: uuid.UUID
    title: str
    body: str
    category: str
    published_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChangelogEntryAdminOut(ChangelogEntryOut):
    """Admin view — adds lifecycle + provenance fields."""

    status: str
    updated_at: datetime | None
    source_ref: str | None


class ChangelogListResponse(BaseModel):
    entries: list[ChangelogEntryOut]
    total: int


class ChangelogAdminListResponse(BaseModel):
    entries: list[ChangelogEntryAdminOut]
    total: int


class ChangelogSyncResponse(BaseModel):
    """Result of a GitHub→Gemini sync run."""

    scanned: int  # merged PRs examined
    imported: int  # new published entries created
    skipped_internal: int  # PRs Gemini judged not customer-facing
    already_present: int  # PRs already imported on a prior run
