"""Company model — stores company-level data resolved from visitor IPs."""

import uuid
from datetime import datetime

from sqlalchemy import Float, Index, Integer, String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        Index("uq_companies_site_domain", "site_id", "domain", unique=True),
        Index("ix_companies_site_intent", "site_id", "intent_score"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    domain: Mapped[str] = mapped_column(String(253), nullable=False)
    name: Mapped[str | None] = mapped_column(String(300))
    industry: Mapped[str | None] = mapped_column(String(200))
    employee_count: Mapped[str | None] = mapped_column(String(50))  # e.g. "51-200"
    city: Mapped[str | None] = mapped_column(String(200))
    country: Mapped[str | None] = mapped_column(String(5))
    total_visitors: Mapped[int] = mapped_column(Integer, default=1)
    total_sessions: Mapped[int] = mapped_column(Integer, default=1)
    total_pageviews: Mapped[int] = mapped_column(Integer, default=0)
    intent_score: Mapped[float] = mapped_column(Float, default=0.0)
    first_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
