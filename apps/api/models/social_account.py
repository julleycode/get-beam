import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.models.database import Base


class Platform(str, enum.Enum):
    facebook = "facebook"
    instagram = "instagram"
    linkedin = "linkedin"
    twitter = "twitter"
    tiktok = "tiktok"


class SocialAccount(Base):
    __tablename__ = "social_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    platform: Mapped[Platform] = mapped_column(Enum(Platform))
    platform_user_id: Mapped[str] = mapped_column(String(255))
    username: Mapped[str] = mapped_column(String(255))
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scopes: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(String), nullable=True
    )
    # Opaque reference to a LinkedIn session registered in the phantommm sidecar
    # (LinkedIn outreach automation). Beam NEVER stores the raw LinkedIn cookie —
    # that lives encrypted inside phantommm; this is just the id it hands back.
    # Nullable: only LinkedIn rows that opted into outreach have one.
    outreach_connection_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Last time an expiry nudge email was sent for this account — throttles the
    # hourly nudge job so a user isn't emailed more than once per window.
    last_expiry_alert_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="social_accounts")
    posts = relationship("Post", back_populates="social_account", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="social_account", cascade="all, delete-orphan")
