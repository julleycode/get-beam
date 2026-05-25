import uuid
from datetime import datetime

from pydantic import BaseModel


class SegmentOut(BaseModel):
    id: uuid.UUID
    site_id: str
    name: str
    description: str | None
    characteristics: dict
    recommended_channels: list[str]
    messaging_angle: str | None
    priority: str
    visitor_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SegmentListResponse(BaseModel):
    segments: list[SegmentOut]
    total: int
