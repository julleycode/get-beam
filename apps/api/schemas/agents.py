import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AgentOut(BaseModel):
    """List-row projection of an AgentVisit (SPEC D1 — agent traffic surface,
    structurally separate from human Visitor/Event data)."""

    id: uuid.UUID
    site_id: str
    vendor: str
    product_or_ua_token: str
    # One of "ua-only" | "ip-verified" | "rdns-verified" (AgentVisit default "ua-only").
    verification_method: str
    last_seen_at: datetime
    visit_count: int

    model_config = {"from_attributes": True}


class AgentDetailOut(AgentOut):
    first_seen_at: datetime
    ip_address: str | None = None
    page_paths: list[str]
    resolved_company_id: uuid.UUID | None = None


class AgentListResponse(BaseModel):
    agents: list[AgentOut]
    total: int
    page: int
    page_size: int


class AgentStatsResponse(BaseModel):
    total_visits: int
    distinct_vendors: int
    by_vendor: dict[str, int]


class TopPageEntry(BaseModel):
    path: str
    count: int


class RecentAiResearchEntry(BaseModel):
    """A company that appeared shortly after an AI agent fetched a commercial page
    (Handoff Detection H3, AC-H3-3). Pure read-only metadata — company/site level
    only, NEVER a person-level claim, NEVER an outreach target."""

    company_name: str
    domain: str | None = None
    matched_page: str
    researched_at: datetime


class FetchBeaconIn(BaseModel):
    """Server-side AI-fetch beacon payload (Handoff Detection H5).

    Posted by the getbeam.fyi edge middleware when an on-demand AI-fetcher UA
    hits a top-level document. Authenticated via the ``X-Beam-Fetch-Secret``
    header (NOT in this body). ``token`` is present only when ``path`` matches
    ``/pricing-overview/{token}`` — it decodes to the page's mint timestamp."""

    site_id: str
    user_agent: str
    path: str
    token: str | None = None
    # Per-fetch token the edge stamped onto the same-host links in the HTML it
    # served for this fetch. Optional: every pre-existing edge build omits it,
    # and a beacon without one is still a valid beacon. Length-capped to the
    # column so an oversized value is rejected here rather than at the INSERT.
    marker: str | None = Field(None, max_length=32)


class FetchBeaconAck(BaseModel):
    """Minimal ack for the fetch beacon. ``status`` is one of
    ``"written"`` | ``"noop"`` — the endpoint also maps these to 202/204."""

    status: str


class AgentAnalyticsResponse(BaseModel):
    """Read-only GEO/AEO analytics snapshot over AgentVisit rows (SPEC AC11).

    Built from the dict returned by ``aggregate_agent_analytics`` — plain
    BaseModel (not from_attributes), not projected directly from an ORM row."""

    by_vendor: dict[str, int]
    top_pages: list[TopPageEntry]
    by_verification: dict[str, int]
    # Handoff Detection H2 (AC-H2-4): count of fetch↔click handoff links for the
    # site — how many agent fetches were correlated to a human AI-referral click.
    handoff_links_count: int
    # Context that makes a handoff count of 0 readable. The split separates exact
    # near-instant matches ("high") from looser in-window ones ("medium"); the
    # denominator is how many on-demand fetches could have produced a link at all,
    # so "no agent traffic" is distinguishable from "traffic but no human click".
    handoff_confidence: dict[str, int] = {}
    on_demand_fetch_count: int = 0
    # Handoff Detection H3 (AC-H3-3): companies that appeared shortly after an AI
    # agent fetched a commercial page. Read-only metadata, never an outreach feed.
    recent_ai_researched_companies: list[RecentAiResearchEntry] = []
