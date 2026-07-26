"""Agent-facing site content — the customer-authored description of what a site
sells, rendered into the public agent gateway surface (manifest/offers/llms.txt/MCP).

One row per site. Purely customer-authored content: no PII, no operational
fields, nothing derived from visitor data. Everything here is intended to become
publicly readable once BOTH ``settings.agent_gateway_enabled`` (global) and
``AgentProfile.enabled`` (per-site) are true — so never store anything on this
model that should not be world-readable.
"""

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class AgentProfile(Base):
    """1:1 agent-facing profile for a Site.

    FK strategy (deliberate, see plan E5): this uses a REAL
    ``ForeignKey("sites.site_id")`` with ``unique=True`` rather than the soft
    ``site_id: str`` no-FK pattern used by ``agent_visit.py`` / ``campaign.py``.
    Both precedents exist in this repo; the hard FK is correct here because
    ``Site.site_id`` is itself DB-unique and ``AgentProfile`` is a genuine 1:1
    record, not an append-only rollup. Do not "fix" this to match the soft
    majority style.
    """

    __tablename__ = "agent_profiles"

    site_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("sites.site_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    # Per-site kill switch. Default OFF: a profile can be authored and saved
    # long before its content is exposed publicly. Both this AND the global
    # settings.agent_gateway_enabled must be true for any public endpoint to
    # answer with content; either off => 404 (endpoint not revealed).
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    tagline: Mapped[str | None] = mapped_column(String(300), nullable=True)
    long_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Array of {name, price, currency, billing_period, availability, url}.
    # Shape is validated at the schema layer (schemas/agent_profile.py), not here.
    offers: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Subset of request_demo|get_quote|join_waitlist|start_checkout this site
    # exposes. Phase 1+2 only publish these as declarations; the action endpoint
    # that honors them is Phase 3.
    capabilities: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    primary_cta: Mapped[str | None] = mapped_column(String(500), nullable=True)
    privacy_policy_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tos_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
