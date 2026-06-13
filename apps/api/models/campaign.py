import enum
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, Enum, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class CampaignType(str, enum.Enum):
    email = "email"
    social_reply = "social_reply"
    social_dm = "social_dm"
    paid_ads = "paid_ads"


class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        Index("idx_campaigns_site", "site_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    segment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("segments.id"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    campaign_type: Mapped[str] = mapped_column(String(20), default="email")
    platform: Mapped[str | None] = mapped_column(String(20), nullable=True)  # twitter, linkedin, etc.
    status: Mapped[str] = mapped_column(String(20), default="draft")
    plan: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)


class CampaignTouchpoint(Base):
    __tablename__ = "campaign_touchpoints"
    __table_args__ = (
        Index("idx_campaign_touchpoints_campaign", "campaign_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    visitor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    touchpoint_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime)
