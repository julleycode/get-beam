"""Schemas for the per-site company exclusion list."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ExclusionReason = Literal["customer", "competitor", "other"]


class ExclusionCreate(BaseModel):
    domain: str = Field(min_length=1, max_length=2048)
    company_name: str | None = Field(default=None, max_length=200)
    reason: ExclusionReason = "other"
    note: str | None = Field(default=None, max_length=500)


class ExclusionOut(BaseModel):
    id: uuid.UUID
    domain: str
    company_name: str | None = None
    reason: str
    note: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class ExclusionImportError(BaseModel):
    row: int
    error: str


class ExclusionImportResult(BaseModel):
    upserted: int
    errors: list[ExclusionImportError]
