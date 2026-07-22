import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, Text, DateTime, Float, Integer, Index, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class Visitor(Base):
    __tablename__ = "visitors"
    __table_args__ = (
        Index("idx_visitors_site_intent", "site_id", "intent_score"),
        Index("idx_visitors_identity_status", "site_id", "identity_status"),
        Index("idx_visitors_site_enrichment", "site_id", "enrichment_status"),
        Index("uq_visitors_site_visitor", "site_id", "visitor_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    visitor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    total_pageviews: Mapped[int] = mapped_column(Integer, default=0)
    total_sessions: Mapped[int] = mapped_column(Integer, default=0)
    avg_time_on_page: Mapped[float] = mapped_column(Float, default=0.0)
    max_scroll_depth: Mapped[int] = mapped_column(Integer, default=0)
    pages_visited: Mapped[list[str]] = mapped_column(JSONB, default=list)
    top_referrer: Mapped[str | None] = mapped_column(String(500))
    utm_source: Mapped[str | None] = mapped_column(String(200))
    utm_medium: Mapped[str | None] = mapped_column(String(200))
    country_code: Mapped[str | None] = mapped_column(String(5))
    device_type: Mapped[str | None] = mapped_column(String(20))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    company_domain: Mapped[str | None] = mapped_column(String(253))
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canonical_visitor_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Durable server-set identity (_rta_svid HttpOnly cookie). When a returning
    # visitor's CLIENT id is wiped (Safari ITP caps client cookies/localStorage at
    # 7 days), the server cookie still carries the ORIGINAL visitor_id. Stored
    # write-once so the resolver can recover a prior identification for FREE
    # instead of re-paying a provider to re-identify someone we already own.
    server_visitor_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    intent_score: Mapped[float] = mapped_column(Float, default=0.0)
    identity_status: Mapped[str] = mapped_column(String(30), default="anonymous")
    enrichment_status: Mapped[str] = mapped_column(String(20), default="pending")
    segmented: Mapped[bool] = mapped_column(Boolean, default=False)
    # Privacy: visitor signaled GPC/DNT (or was added to a suppression list).
    # When true, identity resolution must NEVER run for this visitor. Sticky:
    # once set by any event, the aggregator keeps it true on recompute.
    do_not_resolve: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # EvalLayer Phase 05: True for a synthetic Visitor row created by the
    # agent-company-resolution sweep (visitor_id = f"agent:{agent_visit.id}").
    # Every human-facing query excludes these via human_only_visitor_filter()
    # (SPEC AC2) so agent-derived rows never pollute human visitor data, stats,
    # resolution eligibility, or segmentation.
    is_agent_derived: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class IdentifiedVisitor(Base):
    __tablename__ = "identified_visitors"
    __table_args__ = (
        Index("uq_identified_site_visitor", "site_id", "visitor_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    visitor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    full_name: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    city: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(5))
    gender: Mapped[str | None] = mapped_column(String(20))
    age_range: Mapped[str | None] = mapped_column(String(20))
    resolution_provider: Mapped[str | None] = mapped_column(String(50))
    confidence_score: Mapped[float | None] = mapped_column(Float)
    do_not_email: Mapped[bool] = mapped_column(default=False)
    # EvalLayer Phase 05 / Phase 07 guard: the unforgeable agent-origin marker.
    # Stored as the AgentVisit.id UUID *string* (matches the str | None signature
    # Phase 7's is_emailable_identity getattr + the C5 tripwire assume). Set
    # atomically at INSERT time by the agent-company-resolution sweep; NULL for
    # every human-resolved row. Any row carrying this can NEVER be an outreach
    # target (SPEC AC10).
    source_agent_visit_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Phase 05 (encrypt PII at rest) — added nullable, not yet read/written.
    email_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_bidx: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    full_name_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ResolutionLog(Base):
    __tablename__ = "resolution_logs"
    __table_args__ = (
        Index("idx_resolution_logs_site_created", "site_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    visitor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    success: Mapped[bool] = mapped_column(nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
