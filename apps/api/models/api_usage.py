import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class ApiUsageLog(Base):
    """One row per billable external API call — the cost-tracking ledger.

    Unified across providers and categories so the costs dashboard reads ONE
    table (identity, enrichment, email, ai, osint). Identity resolution ALSO
    writes resolution_logs because the daily-budget meter counts those rows
    (usage_limits.get_resolution_attempts_today); this table is an additive
    mirror, not a replacement.

    Best-effort: an insert here must never break the API call it records — all
    writes go through services/usage_logger.log_api_call, which swallows errors.
    """

    __tablename__ = "api_usage_logs"
    __table_args__ = (
        Index("idx_api_usage_site_created", "site_id", "created_at"),
        Index("idx_api_usage_category_created", "category", "created_at"),
        Index("idx_api_usage_provider", "provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Nullable: account-wide calls without a site (e.g. AI/email) can still log.
    site_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    visitor_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    # identity | enrichment | email | ai | osint
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    operation: Mapped[str | None] = mapped_column(String(50), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Billable units (credits / tokens / emails) when relevant.
    units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
