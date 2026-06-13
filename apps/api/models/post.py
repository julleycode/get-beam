import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.models.database import Base
from apps.api.models.social_account import Platform


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        Index("idx_posts_account_posted", "social_account_id", "posted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    social_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("social_accounts.id", ondelete="CASCADE")
    )
    platform: Mapped[Platform] = mapped_column(Enum(Platform))
    platform_post_id: Mapped[str] = mapped_column(
        String(255), unique=True, index=True
    )
    author_name: Mapped[str] = mapped_column(String(255))
    author_username: Mapped[str] = mapped_column(String(255))
    author_avatar_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    media_urls: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(String), nullable=True
    )
    post_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(
        String(20), default="following",
        doc="Where this post came from: 'visitors', 'following', 'my_posts'",
    )
    commented: Mapped[bool] = mapped_column(Boolean, default=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    social_account = relationship("SocialAccount", back_populates="posts")
    drafts = relationship("Draft", back_populates="post", cascade="all, delete-orphan")
