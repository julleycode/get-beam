"""Cross-tenant campaign performance benchmark — pooled, k-anonymous aggregates.

PRIVACY SHAPE IS THE WHOLE DESIGN (marketing-claims-gap Phase 3, D1). A row is
``(category_normalized, period, sends, opens, clicks, conversions, site_count)``
and nothing else:

* **No site identifier, no visitor reference, no email, no tenant free text.**
  ``category_normalized`` is a value from the closed controlled vocabulary in
  ``services/campaign_benchmark.py`` — never a tenant-authored string.
* Because no row references a person or a tenant, GDPR erasure is moot BY
  CONSTRUCTION: ``services/graph_erasure.py`` has nothing here to sweep. The
  accepted tradeoff is that a published aggregate is irreversible — a conversion
  already summed cannot be un-counted.
* A row is written only when at least ``BENCHMARK_K_FLOOR`` distinct opted-in
  sites contributed to it, so no single tenant's numbers are readable back.

The only statistic this schema supports is a pooled ratio — a category AVERAGE
(mean). Sums plus a tenant count cannot yield a median, so surfaces say
"category average" and the word "median" is banned.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class CampaignBenchmark(Base):
    __tablename__ = "campaign_benchmarks"
    __table_args__ = (
        UniqueConstraint(
            "category_normalized",
            "period",
            name="uq_campaign_benchmarks_category_period",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # A value from the closed vocabulary (services/campaign_benchmark.py).
    # NEVER raw `sites.category` — that column is free String(100).
    category_normalized: Mapped[str] = mapped_column(String(50), nullable=False)
    # ISO week label of the aggregated window, e.g. "2026-W33".
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    sends: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    opens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conversions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Number of distinct opted-in sites pooled into this row. Enforces the
    # k-floor at write time and MUST NOT be exposed on any tenant-visible
    # surface (it is an anonymity parameter, not a stat).
    site_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
