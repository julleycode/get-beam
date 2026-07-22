import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class AgentVisit(Base):
    """Aggregate rollup row for one (site, vendor, product_or_ua_token) tuple.

    Structurally separate from Visitor/Event (SPEC D1) — never mixed into
    human visitor data. Upserted by (site_id, vendor, product_or_ua_token)
    as new agent-visit events arrive (Phase 2 wires the upsert; this phase
    only defines the schema).
    """

    __tablename__ = "agent_visits"
    __table_args__ = (
        UniqueConstraint(
            "site_id", "vendor", "product_or_ua_token",
            name="uq_agent_visits_site_vendor_token",
        ),
        Index("idx_agent_visits_site_last_seen", "site_id", "last_seen_at"),
    )

    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    vendor: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    product_or_ua_token: Mapped[str] = mapped_column(String(50), nullable=False)
    verification_method: Mapped[str] = mapped_column(String(20), nullable=False, default="ua-only")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    # Bounded list of distinct page paths this vendor/token has visited on this
    # site. Phase 2 (ingest wiring) MUST cap this list (e.g. last 50 distinct
    # paths) when appending — no cap is enforced at the schema level here.
    page_paths: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    visit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # No FK constraint in Phase 1 (Phase 5 adds the FK once company-resolution
    # exists) — nullable loose reference only.
    resolved_company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
