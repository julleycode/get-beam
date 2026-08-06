import uuid
from datetime import datetime
from typing import Literal

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
    # AI answer-engine that referred this human click (chatgpt/perplexity/…).
    # Additive attribution only — never affects emailability. VisitorDetailOut
    # inherits it. None = not AI-referred (direct/search/social/own-domain).
    ai_source: str | None = None
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
    # Handoff Detection H2: confidence of the strongest fetch↔click handoff link
    # for this visitor ("high"/"medium"), or None when no link exists. List-row
    # pill only — PROBABILISTIC, never affects emailability.
    handoff_confidence: str | None = None
    # Cadence bot flag: the visitor's visit schedule looks cron-like AND their
    # sessions are pageview-only. VISIBILITY-ONLY badge — never affects
    # emailability, aggregates, or resolution. Batch-computed, default False.
    is_bot_suspect: bool = False
    # Outlier / internal-traffic damping. True when this visitor's event volume
    # is a statistical outlier for THIS site, sustained across days, with real
    # engagement. Inferred, never proven — UI copy must say "unusually high
    # activity" and must never assert the visitor's identity. Never affects
    # emailability; when the site opts in it damps aggregates + resolution order.
    is_internal_suspect: bool = False
    # The human's manual call: None / "internal" / "not_internal". Always wins
    # over the automatic scorer, in both directions.
    internal_override: str | None = None

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
    avatar_url: str | None = None
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
    # Provider outages (401/403/5xx/timeout/DNS) deliberately do NOT write
    # resolution_logs — counting them as attempts is what armed the 30-day retry
    # lock over vendor downtime. They are still recorded in api_usage_logs, and
    # surfaced here so "we tried, the vendor was down" stays visible in the UI
    # instead of looking like the visitor was never processed. Display only:
    # these never feed the cooldown calculation.
    outage_providers: list[str] | None = None
    last_outage_at: datetime | None = None
    # Handoff Detection H2 (SPEC AC-H2-1/4): the latest fetch↔click handoff link
    # for this visitor, if any. PROBABILISTIC attribution only — an AI agent
    # fetched this page shortly before the visit. Never a certainty assertion, and
    # NEVER affects emailability (separate write path from source_agent_visit_id).
    # All None = no handoff link.
    handoff_vendor: str | None = None
    handoff_confidence: str | None = None  # "high" | "medium" (low is never written)
    handoff_delta_seconds: int | None = None
    handoff_matched_page: str | None = None
    handoff_fetch_at: datetime | None = None


class VisitorStatsResponse(BaseModel):
    total_visitors: int
    # CONFIRMED identities only (identity_status == "identified").
    identified: int
    # Identity-honesty Phase 1: unconfirmed graph matches awaiting human
    # confirm/reject. Reported separately — never folded into `identified`.
    # Defaulted so existing constructors/consumers stay valid.
    candidates: int = 0
    enriched: int
    could_enrich_more: int
    # Count feeding the auto-segmentation trigger (enriched AND not yet segmented)
    enriched_unsegmented: int
    # Anonymous visitors that clear the resolution intent gate, waiting on the next run
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


class VisitorAiSourceOut(BaseModel):
    """One row of the Source (AI-referral) filter dropdown: an AI answer-engine
    label and how many of this site's visitors arrived via it."""

    ai_source: str
    count: int


class InternalOverrideRequest(BaseModel):
    """The human's call on whether a visitor is internal traffic.

    ``None`` clears the manual call and hands the visitor back to the automatic
    scorer. ``"internal"`` / ``"not_internal"`` are permanent until changed: the
    sweep skips any visitor with a non-NULL override, in BOTH directions.
    """

    override: Literal["internal", "not_internal"] | None = None


class ManualIdentifyRequest(BaseModel):
    email: str
    full_name: str | None = None
    company_name: str | None = None
    job_title: str | None = None
