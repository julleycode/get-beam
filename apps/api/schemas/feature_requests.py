import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class FeatureRequestCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    detail: str | None = Field(default=None, max_length=2000)
    urgency: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=255)


class FeatureRequestUpdate(BaseModel):
    status: str | None = Field(default=None, max_length=20)
    admin_note: str | None = Field(default=None, max_length=2000)


class FeatureRequestOut(BaseModel):
    id: uuid.UUID
    title: str
    detail: str | None
    urgency: str | None
    email: str | None
    source: str | None
    status: str
    admin_note: str | None
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class FeatureRequestListResponse(BaseModel):
    requests: list[FeatureRequestOut]
    total: int
