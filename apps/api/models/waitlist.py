"""WaitlistSignup model — stores private beta waitlist signups."""

import uuid

from sqlalchemy import String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from apps.api.models.database import Base


class WaitlistSignup(Base):
    __tablename__ = "waitlist_signups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    site_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/approved/rejected
    invite_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[None] = mapped_column(DateTime(timezone=True), nullable=True)
