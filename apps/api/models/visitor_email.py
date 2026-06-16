import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class VisitorEmail(Base):
    """Maps a captured email address to a visitor cookie ID.

    Sources:
    - "form"   — email extracted from a form submit event on the customer site
    - "utm"    — email decoded from a _bid= UTM parameter in the page URL
    - "manual" — manually linked by the site operator
    """

    __tablename__ = "visitor_emails"
    __table_args__ = (
        UniqueConstraint("site_id", "visitor_id", "email", name="uq_visitor_email_site_vid_email"),
        Index("idx_visitor_emails_site_visitor", "site_id", "visitor_id"),
        Index("idx_visitor_emails_email", "email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    visitor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="form")
    # Phase 05 (encrypt PII at rest) — added nullable, not yet read/written.
    # email_ciphertext holds the Fernet-encrypted address; email_bidx is the
    # HMAC blind index used for equality/uniqueness lookups once we cut over.
    email_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_bidx: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
