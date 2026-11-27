"""Daily per-ad performance rows pulled read-only from Meta / Google reporting
(ad-insights-seo-aeo_27-11-26).

One row per (connection, platform ad, day), upserted idempotently by
services/ad_insights_ingest.py. ``site_id`` is ``String(50)`` with NO FK —
matches ``models/ad_connection.py``; site deletion clears these rows
explicitly in ``routers/sites.py``. Ad copy is third-party text: it is never
logged and only reaches a prompt through ``agents/prompt_safety``.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Date, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class AdPerformanceDaily(Base):
    __tablename__ = "ad_performance_daily"
    __table_args__ = (
        UniqueConstraint(
            "connection_id", "platform_ad_id", "date", name="uq_ad_perf_conn_ad_date"
        ),
        Index("idx_ad_perf_site_date", "site_id", "date"),
    )

    site_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ad_connections.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    platform_ad_id: Mapped[str] = mapped_column(String(100), nullable=False)
    campaign_name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    headline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    landing_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    impressions: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    clicks: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    conversions: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
