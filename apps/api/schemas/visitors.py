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


class VisitorListResponse(BaseModel):
    visitors: list[VisitorOut]
    total: int
    page: int
    page_size: int
