import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class CrmClosedWonContact(Base):
    """One closed-won deal contact read back from a CRM, webhook, or CSV.

    closed-won-lookalikes: the seed for a lookalike audience. Email is stored
    ONLY as blind index (``email_bidx``) + Fernet ciphertext — never plaintext.
    It is decrypted in-process only to compute the SHA-256 that leaves Beam.
    Removed on site delete and by the graph-erasure sweep (by ``email_bidx``).
    """

    __tablename__ = "crm_closed_won_contacts"
    __table_args__ = (
        UniqueConstraint(
            "site_id", "external_deal_id", "email_bidx", name="uq_crm_closed_won_deal_email"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("sites.site_id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    external_deal_id: Mapped[str] = mapped_column(String(255), nullable=False)
    email_bidx: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    email_ciphertext: Mapped[str] = mapped_column(String, nullable=False)
    company_domain: Mapped[Optional[str]] = mapped_column(String(253), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    identified_visitor_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False)  # crm | csv | webhook
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
