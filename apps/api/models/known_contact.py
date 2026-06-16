import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class KnownContact(Base):
    """A person the site owner already knows (existing customer, prior lead, or
    a CRM export) — uploaded so Beam can flag matching identified visitors as
    "Known" and let the owner filter them out of net-new targeting.

    Keyed by a blind index (HMAC of the email, see services/known_hash.py) — the
    same privacy pattern as the suppression list. We never store a second
    plaintext copy of the customer's contact list; matching is hash-vs-hash.
    """

    __tablename__ = "known_contacts"
    __table_args__ = (
        Index("uq_known_site_hash", "site_id", "email_hash", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Where this entry came from — kept so a future CRM sync (Phase 3c) can reuse
    # this table with source="crm" without colliding with manual/csv uploads.
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="csv")
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
