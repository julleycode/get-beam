import uuid
from datetime import datetime

from sqlalchemy import Float, String, DateTime, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class CompanyGraphNode(Base):
    """Durable cross-tenant IP→company graph.

    Beam already pays for (or freely resolves) IP→company lookups once and
    throws the value away in a Redis-only 30d cache. This table makes every
    resolution a PERMANENT, cross-tenant asset: a resolution done for one
    customer's visitor is reused (free, no rDNS/provider call) for any other
    customer whose visitor shares the IP.

    Same cross-tenant posture as ``beam_identity_graph`` — no new consent
    surface, the data was already being resolved per-tenant; this only makes it
    durable and shared. Write-through on every successful free rDNS resolution
    (and, when the paid path is flag-enabled, on paid IP→company hits). Read at
    resolve time before a fresh rDNS lookup when a non-stale row exists.

    ``id`` / ``created_at`` / ``updated_at`` come from ``Base``.
    """

    __tablename__ = "company_graph"
    __table_args__ = (
        # Upsert key — mirrors the beam_identity_graph unique-index pattern so
        # write-through can use pg_insert(...).on_conflict_do_update(...) on it.
        UniqueConstraint("ip", "source", name="uq_company_graph_ip_source"),
        Index("idx_company_graph_ip", "ip"),
        Index("idx_company_graph_domain", "domain"),
    )

    # Resolved IP (nullable if resolved by domain only).
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    # Company root domain.
    domain: Mapped[str | None] = mapped_column(String(253), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Resolution source: "rdns" | "paid_ip" | future provider names.
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Bumped on every re-verification/upsert; drives read-time staleness check.
    last_verified: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
