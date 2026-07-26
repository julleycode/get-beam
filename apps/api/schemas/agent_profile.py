"""Pydantic shapes for the authed AgentProfile CRUD surface.

These are the CUSTOMER-facing (dashboard) shapes. The public agent-facing
shapes live in ``schemas/agent_gateway.py`` and deliberately expose a narrower
set of fields — never ``id``, never ``user_id``, never any operational column.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# Closed allowlist. Adding a capability here is an explicit, deliberate act —
# the action endpoint that honors these arrives in Phase 3.
AGENT_CAPABILITIES = {
    "request_demo",
    "get_quote",
    "join_waitlist",
    "start_checkout",
}

MAX_OFFERS = 100


class AgentOffer(BaseModel):
    """One sellable thing. Mirrors the ACP feed vocabulary loosely enough to
    map cleanly in ``services/agent_gateway.py`` without locking the customer
    into ACP's exact field names in the dashboard."""

    name: str = Field(..., min_length=1, max_length=200)
    price: str | None = Field(default=None, max_length=50)
    currency: str | None = Field(default=None, max_length=10)
    billing_period: str | None = Field(default=None, max_length=50)
    availability: str | None = Field(default=None, max_length=50)
    url: str | None = Field(default=None, max_length=500)


class AgentProfileUpdate(BaseModel):
    """Partial upsert. Only set fields are applied (PATCH-like PUT semantics)."""

    enabled: bool | None = None
    tagline: str | None = Field(default=None, max_length=300)
    long_description: str | None = None
    offers: list[AgentOffer] | None = None
    capabilities: list[str] | None = None
    primary_cta: str | None = Field(default=None, max_length=500)
    privacy_policy_url: str | None = Field(default=None, max_length=500)
    tos_url: str | None = Field(default=None, max_length=500)
    contact_email: str | None = Field(default=None, max_length=320)

    @field_validator("capabilities")
    @classmethod
    def _valid_capabilities(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        unknown = [c for c in v if c not in AGENT_CAPABILITIES]
        if unknown:
            raise ValueError(
                f"unknown capabilities {sorted(unknown)}; "
                f"allowed: {sorted(AGENT_CAPABILITIES)}"
            )
        # De-dup, preserve order.
        return list(dict.fromkeys(v))

    @field_validator("offers")
    @classmethod
    def _bounded_offers(cls, v: list[AgentOffer] | None) -> list[AgentOffer] | None:
        if v is not None and len(v) > MAX_OFFERS:
            raise ValueError(f"at most {MAX_OFFERS} offers")
        return v


class AgentProfileOut(BaseModel):
    site_id: str
    enabled: bool
    tagline: str | None
    long_description: str | None
    offers: list[AgentOffer]
    capabilities: list[str]
    primary_cta: str | None
    privacy_policy_url: str | None
    tos_url: str | None
    contact_email: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
