"""WaitlistSignup model — stores private beta waitlist signups."""

import uuid
from datetime import datetime

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
    # X (Twitter) handle, normalized without the leading "@". Set ONLY when the
    # signup opts in by entering it — providing it is consent to appear on the
    # public Founders Wall. Never derived from email.
    x_handle: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # ── Private beta application fields (all nullable; legacy email-only rows read NULL) ──
    # Free text: UNTRUSTED applicant input. Sanitized on write with
    # apps.api.agents.prompt_safety.clean_text; rendered escaped (never dangerouslySetInnerHTML).
    business_description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    use_case: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Enum-ish buckets: validated against Python allow-lists on write (no DB CHECK constraint,
    # which would not be additive-nullable-safe on a table with existing rows).
    monthly_visitors: Mapped[str | None] = mapped_column(String(32), nullable=True)
    role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    company_size: Mapped[str | None] = mapped_column(String(32), nullable=True)
    plan_interest: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Set only when the extended application form is submitted; distinguishes an
    # application from a legacy email-only signup.
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/approved/rejected
    invite_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # One-use invite enforcement: set when the token is consumed at signup
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_by_clerk_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
