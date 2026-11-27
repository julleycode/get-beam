"""Per-CTA-type click attribution (signal-creative-cta).

One append-only row per ``/c/{site_id}?ct=<type>`` hit — with or without a
recipient token, no dedupe. Deliberately carries NO PII: no email, no IP, no
visitor id. Click-level counts only, never conversions.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class CtaClickEvent(Base):
    __tablename__ = "cta_click_events"
    __table_args__ = (
        Index("idx_cta_click_events_site_type", "site_id", "cta_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    site_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("sites.site_id", ondelete="CASCADE"), nullable=False
    )
    cta_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # Soft reference (no FK): parsed from the public click URL, stored only.
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
