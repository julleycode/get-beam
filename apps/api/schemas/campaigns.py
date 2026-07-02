import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


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


class CampaignTestSendRequest(BaseModel):
    email: EmailStr


class ReturnedVisitor(BaseModel):
    visitor_id: str
    full_name: str | None
    email_masked: str | None
    opened_at: datetime | None
    clicked_at: datetime | None
    last_visit_at: datetime | None
    pageviews_after: int


class CampaignStatsResponse(BaseModel):
    sent: int
    opened: int
    clicked: int
    open_rate: float
    click_rate: float
    returned_visitors: list[ReturnedVisitor]
