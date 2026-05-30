"""FeatureRequest model — stores feature requests submitted from the landing page FAB."""

import uuid

from sqlalchemy import String, Text
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
    # created_at / updated_at are provided by Base
