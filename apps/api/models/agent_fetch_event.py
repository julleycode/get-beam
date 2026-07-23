"""Append-only per-hit AI-agent fetch event (Handoff Detection H1).

One row per recognized AI-agent hit — distinct from the ``agent_visits`` rollup
upsert. This is the raw, timestamped, tier-tagged event stream every downstream
handoff phase (H2 fetch↔click correlation, H3 live alerts, optional daily
timeseries) reads from.

Structurally separate from Visitor/Event (SPEC D1) — agent traffic never touches
human visitor data. Logically append-only (no upsert), though the shared ``Base``
provides an ``updated_at`` column; that is accepted, not fought.
"""

from sqlalchemy import String, Index
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class AgentFetchEvent(Base):
    """One append-only per-hit agent fetch event, tagged on-demand vs index.

    ``id``/``created_at``/``updated_at`` are provided by ``Base``. No
    ``ForeignKey()`` is declared on ``site_id`` — the model-family house
    convention (see ``AgentVisit.resolved_company_id``) keeps cross-table FKs at
    the DB layer, not the ORM layer.
    """

    __tablename__ = "agent_fetch_events"
    __table_args__ = (
        Index("idx_agent_fetch_events_site_created", "site_id", "created_at"),
        Index(
            "idx_agent_fetch_events_site_path_tier_created",
            "site_id", "page_path", "tier", "created_at",
        ),
    )

    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    vendor: Mapped[str] = mapped_column(String(30), nullable=False)
    raw_ua_token: Mapped[str] = mapped_column(String(50), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    page_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    verification_method: Mapped[str] = mapped_column(String(20), nullable=False, default="ua-only")
