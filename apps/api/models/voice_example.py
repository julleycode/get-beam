"""VoiceExample model -- stores user's reply style examples for GBrain AI learning."""

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.models.database import Base
from apps.api.models.social_account import Platform


class FeedbackType(str, enum.Enum):
    approved = "approved"
    edited = "edited"
    rejected = "rejected"


class VoiceExample(Base):
    __tablename__ = "voice_examples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    platform: Mapped[Platform] = mapped_column(Enum(Platform))
    original_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_draft: Mapped[str] = mapped_column(Text)
    final_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    feedback_type: Mapped[FeedbackType] = mapped_column(Enum(FeedbackType))
    strategy: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="voice_examples")
