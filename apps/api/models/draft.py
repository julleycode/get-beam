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
    # Why a draft is `rejected`: "user_rejected" (the user clicked Reject) vs
    # "auto_rejected_sibling" (another draft for the same post was approved).
    # NULL for historical rows / non-rejected drafts. Lets the UI relabel
    # auto-rejected siblings as "Not used" instead of a blunt "Rejected".
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # Auto-generation fields (set when draft is created from visitor social context)
    auto_generated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    visitor_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    context_summary: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # ─── engage-learning-agent Phase 1 (signal acquisition) ───
    # The platform's own id for the reply we posted. Without it a sent reply is
    # unmeasurable afterwards: it is the join key for the reply-back correlation
    # sweep and the public-metrics poller. Persisted in the SAME transaction as
    # status=sent, but NEVER allowed to fail a successful post — a missing id
    # leaves this NULL and logs. INTERNAL: do not add to a response schema.
    platform_comment_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    # The site this draft is attributed to. `String(50)` referencing the unique
    # `sites.site_id` SLUG — NOT the UUID PK — matching every other site-keyed
    # consumer in the repo (visitors.site_id, events.site_id,
    # engagement_attributions.site_id). Downstream joins go to `sites.site_id`
    # directly, never `sites.id`.
    #
    # Nullable, and NULL is a real outcome rather than an error: one user may own
    # many sites, and the manual "Generate Reply" path carries no visitor_id to
    # disambiguate. Every consumer FAILS CLOSED on NULL (no attribution mint, no
    # autonomy eligibility, excluded from site aggregates) — see
    # `models/engage_outcome.py`. Historical rows stay NULL by design.
    # INTERNAL: do not add to a response schema.
    site_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("sites.site_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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
