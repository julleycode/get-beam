import uuid
from datetime import datetime

from pydantic import BaseModel


class VisitorOut(BaseModel):
    id: uuid.UUID
    site_id: str
    visitor_id: str
    first_seen: datetime
    last_seen: datetime
    total_pageviews: int
    total_sessions: int
    avg_time_on_page: float
    max_scroll_depth: int
    pages_visited: list[str]
    top_referrer: str | None
    utm_source: str | None
    utm_medium: str | None
    country_code: str | None
    device_type: str | None
    intent_score: float
    identity_status: str
    enrichment_status: str

    model_config = {"from_attributes": True}


class VisitorDetailOut(VisitorOut):
    email: str | None = None
    full_name: str | None = None
    phone: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    job_title: str | None = None
    company_name: str | None = None
    industry: str | None = None
    linkedin_url: str | None = None
    twitter_handle: str | None = None
    linkedin_headline: str | None = None
    twitter_bio: str | None = None
    enrichment_completeness: float | None = None
    resolution_provider: str | None = None
    confidence_score: float | None = None
    social_context: dict | None = None
    auto_draft_count: int | None = None
    # Resolution observability — why is this visitor still anonymous?
    last_resolution_attempt: datetime | None = None
    resolution_providers_tried: list[str] | None = None
    resolution_skip_reason: str | None = None  # below_intent_threshold | no_ip_address | recently_attempted | daily_budget_exhausted | monthly_plan_limit_reached | awaiting_next_run


class VisitorStatsResponse(BaseModel):
    total_visitors: int
    identified: int
    enriched: int
    could_enrich_more: int
    # Count feeding the auto-segmentation trigger (enriched AND not yet segmented)
    enriched_unsegmented: int
    # Anonymous visitors at intent >= 40, waiting on the next resolution run
    eligible_for_resolution: int
    # Daily identification quota (limit is None for BYOK = unlimited)
    identify_used_today: int
    identify_daily_limit: int | None
    identify_is_byok: bool


class VisitorListResponse(BaseModel):
    visitors: list[VisitorOut]
    total: int
    page: int
    page_size: int


class ManualIdentifyRequest(BaseModel):
    email: str
    full_name: str | None = None
    company_name: str | None = None
    job_title: str | None = None
