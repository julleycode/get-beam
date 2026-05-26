import uuid
from datetime import datetime

from pydantic import BaseModel


class CampaignOut(BaseModel):
    id: uuid.UUID
    site_id: str
    segment_id: uuid.UUID | None
    name: str
    campaign_type: str = "email"
    platform: str | None = None
    status: str
    plan: dict
    created_at: datetime
    approved_at: datetime | None
    started_at: datetime | None

    model_config = {"from_attributes": True}


class CampaignListResponse(BaseModel):
    campaigns: list[CampaignOut]
    total: int


class CampaignStatusUpdate(BaseModel):
    status: str
