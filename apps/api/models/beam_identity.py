import uuid
from datetime import datetime

from sqlalchemy import Float, String, Text, DateTime, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class BeamIdentityNode(Base):
    """Cross-customer identity graph.

    Every successful identification writes a (fingerprint, email) pair here.
    Before calling external providers, the resolver checks this table —
    if the same fingerprint was identified on ANY Beam customer's site,
    we reuse that identity instantly (free, no API cost).
    """

    __tablename__ = "beam_identity_graph"
    __table_args__ = (
        Index("idx_beam_identity_fingerprint", "fingerprint"),
        Index(
            "uq_beam_identity_fp_email",
            "fingerprint",
            "email",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    full_name: Mapped[str | None] = mapped_column(String(200))
    # Phase 05 (encrypt PII at rest) — added nullable, not yet read/written.
    email_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_bidx: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    full_name_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    source_site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    source_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
