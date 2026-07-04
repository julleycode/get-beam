import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


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
    # Conversion outcomes (campaign lifetime). Defaults keep older clients happy.
    converted: int = 0
    conversion_rate: float = 0.0
    revenue_cents: int = 0
    returned_visitors: list[ReturnedVisitor]


# Hard server-side cap on how many LinkedIn profiles one outreach run may target,
# independent of the per-request `limit`. Automating LinkedIn is high-risk; this
# bounds blast radius even if the client sends a large value.
MAX_LINKEDIN_OUTREACH_LIMIT = 50


class LinkedInOutreachRequest(BaseModel):
    """Start a LinkedIn outreach run for a campaign's LinkedIn step.

    dry_run defaults ON everywhere — a real (non-dry-run) send requires the
    caller to explicitly pass ``dry_run=false``.
    """

    dry_run: bool = True
    limit: int = Field(default=20, ge=1, le=MAX_LINKEDIN_OUTREACH_LIMIT)
    action: Literal["connect", "message"] = "connect"


class LinkedInOutreachResponse(BaseModel):
    job_id: str
    dry_run: bool
    total_targets: int
    audience_skipped_no_linkedin: int


class LinkedInOutreachJobResponse(BaseModel):
    status: str
    done: int
    total: int
    sent: int
    results: list[dict]


class LinkedInScheduleRequest(BaseModel):
    """Schedule a durable LinkedIn drip campaign for a campaign's LinkedIn step.

    Unlike the immediate outreach run, this schedules a persistent campaign on
    the phantommm sidecar that STARTS after the touchpoint's suggested delay,
    then sends within daily limits. dry_run defaults ON everywhere — a real
    schedule requires the caller to explicitly pass ``dry_run=false``.
    """

    dry_run: bool = True
    limit: int = Field(default=20, ge=1, le=MAX_LINKEDIN_OUTREACH_LIMIT)
    action: Literal["connect", "message"] = "connect"


class LinkedInScheduleResponse(BaseModel):
    # In dry-run phantommm may not return a campaignId → empty string.
    campaign_id: str
    scheduled_at: str | None
    delay_hours: int
    dry_run: bool
    total_targets: int
    audience_skipped_no_linkedin: int


class LinkedInCampaignDetailResponse(BaseModel):
    status_counts: dict[str, int]
    scheduled_at: str | None
    days: list[dict]
