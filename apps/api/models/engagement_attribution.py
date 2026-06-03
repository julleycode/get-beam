"""Engagement attribution model — tracks which Beam engagements drive new visitors."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class EngagementAttribution(Base):
    __tablename__ = "engagement_attributions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    draft_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("drafts.id", ondelete="SET NULL"), nullable=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    engagement_type: Mapped[str] = mapped_column(String(20), nullable=False)  # comment, dm, like
    target_post_url: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    utm_tag: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    # Attribution results — updated when visitors arrive with matching UTM
    new_visitors_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    new_identified_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    engaged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
