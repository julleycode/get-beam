import uuid
from datetime import datetime

from pydantic import BaseModel


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
