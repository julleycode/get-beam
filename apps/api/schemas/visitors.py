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
    # Pulled from the identity table (1:1) when the visitor has been resolved.
    # Lets the list show a real email/name instead of the opaque visitor_id.
    email: str | None = None
    full_name: str | None = None
    # 'person' = the actual visitor (captured email / person-graph match).
    # 'company' = an arbitrary employee guessed from the visitor's IP→company
    # domain (Hunter/Apollo) — NOT the real person. None = no identity yet.
    identity_level: str | None = None
    # True when this visitor's email matches the site owner's uploaded
    # known-contacts list (existing customer / prior lead). Matched by hash.
    is_known: bool = False
    known_source: str | None = None  # "csv" | "crm" | ...
    # One-line "why this person matters" — derived from behaviour (+ enrichment
    # on the detail view). None when there's no signal worth surfacing.
    conviction: str | None = None

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
    resolution_skip_reason: str | None = None  # below_intent_threshold | no_ip_address | recently_attempted | daily_budget_exhausted | monthly_plan_limit_reached | privacy_opt_out | awaiting_next_run
    coverage_note: str | None = None  # set for 'unresolvable' visitors the US-only provider stack structurally can't match (e.g. non-US residential)


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


class VisitorCountryOut(BaseModel):
    """One row of the country filter dropdown: a country and how many of this
    site's visitors came from it (GeoIP-derived country_code on Visitor)."""

    country_code: str
    count: int


class ManualIdentifyRequest(BaseModel):
    email: str
    full_name: str | None = None
    company_name: str | None = None
    job_title: str | None = None
