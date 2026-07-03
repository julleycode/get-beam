import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.models.database import Base
from apps.api.models.social_account import Platform


class DraftType(str, enum.Enum):
    reply = "reply"
    comment = "comment"


class DraftStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    sent = "sent"
    failed = "failed"


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    type: Mapped[DraftType] = mapped_column(Enum(DraftType))
    message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    post_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"), nullable=True
    )
    platform: Mapped[Platform] = mapped_column(Enum(Platform))
    ai_content: Mapped[str] = mapped_column(Text)
    edited_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[DraftStatus] = mapped_column(
        Enum(DraftStatus), default=DraftStatus.pending
    )
    strategy: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Plain-language reason a send failed (shown on the failed draft card so the
    # user knows why + what to do). Cleared on a successful (re)send.
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Auto-generation fields (set when draft is created from visitor social context)
    auto_generated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    visitor_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    context_summary: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="drafts")
    message = relationship("Message", back_populates="drafts")
    post = relationship("Post", back_populates="drafts")
