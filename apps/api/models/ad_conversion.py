"""Server-side conversion delivery outbox + per-site/platform conversion config.

``AdConversionDelivery`` is a durable outbox: one row per (site, platform,
dedup_id). The conversion sweep (services/ad_conversions.py) discovers Beam
outcomes, enqueues rows here, re-checks every consent gate at send time, then
sends via ``AdsProvider.send_conversions``. Rows NEVER hold plaintext PII —
only ids, a status vocabulary and a sanitized reason code in ``last_error``.

``AdConversionConfig`` maps Beam outcomes to platform conversion events and
carries the per-platform destination ids plus the discovery watermarks.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base

# Delivery status vocabulary (frozen public contract). Skips are terminal.
DELIVERY_STATUS_PENDING = "pending"
DELIVERY_STATUS_SENT = "sent"
DELIVERY_STATUS_FAILED = "failed"
SKIPPED_PREFIX = "skipped_"

CONVERSION_TYPE_LEAD = "lead"
CONVERSION_TYPE_GOAL = "goal"
CONVERSION_TYPES = frozenset({CONVERSION_TYPE_LEAD, CONVERSION_TYPE_GOAL})

CONVERSION_PLATFORMS = frozenset({"meta", "google", "linkedin"})


class AdConversionDelivery(Base):
    __tablename__ = "ad_conversion_deliveries"
    __table_args__ = (
        UniqueConstraint("site_id", "platform", "dedup_id", name="uq_ad_conv_delivery_dedup"),
        Index("idx_ad_conv_delivery_due", "status", "next_attempt_at"),
        Index("idx_ad_conv_delivery_site_visitor", "site_id", "visitor_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("sites.site_id", ondelete="CASCADE"), nullable=False
    )
    visitor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    conversion_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Goal id (str UUID) for `goal` conversions — selects the platform event via
    # AdConversionConfig.goal_event_map. NULL for `lead`.
    goal_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # lead -> IdentifiedVisitor.id ; goal -> Conversion.id (E11).
    dedup_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # When the conversion happened (Meta event_time / Google eventTimestamp).
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default=DELIVERY_STATUS_PENDING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # reason code only, never PII
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AdConversionConfig(Base):
    __tablename__ = "ad_conversion_configs"
    __table_args__ = (
        UniqueConstraint("site_id", "platform", name="uq_ad_conv_config_site_platform"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("sites.site_id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    # {goal_id: platform_event}; key "lead" enables lead conversions.
    goal_event_map: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    # Meta
    meta_dataset_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    meta_test_event_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Google Data Manager destination
    google_operating_account_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    google_product_destination_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    validate_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    eea_consent_attested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    goal_watermark_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    lead_watermark_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
