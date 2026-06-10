"""FeatureRequest models — requests (landing FAB + dashboard board) and upvotes."""

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class FeatureRequest(Base):
    __tablename__ = "feature_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    # nice | useful | critical  (nice to have / i'd use it / i'd pay for it)
    urgency: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    # light context for triage
    source: Mapped[str | None] = mapped_column(String(50), default="landing_fab")
    status: Mapped[str] = mapped_column(String(20), default="new")  # new | planned | shipped | closed
    admin_note: Mapped[str | None] = mapped_column(Text)
    # created_at / updated_at are provided by Base


class FeatureRequestVote(Base):
    """One upvote per (request, user) — the community feature board.

    Logged-in users toggle votes; the unique constraint makes double-voting
    impossible even under concurrent requests.
    """

    __tablename__ = "feature_request_votes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    feature_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("feature_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("feature_request_id", "user_id", name="uq_feature_vote_user"),
    )
