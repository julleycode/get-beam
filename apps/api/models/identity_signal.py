import uuid
from datetime import datetime

from sqlalchemy import Float, String, Text, DateTime, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class IdentitySignal(Base):
    """Corroborating engagement signal (SendGrid open/click) — owned-data-layer.

    One row per corroborating event (NOT per identity — different cardinality/
    lifecycle from beam_identity_graph, hence a separate table). Strictly
    CORROBORATING: consumed only by ``corroborate_identity()`` to bump confidence
    on an ALREADY-matched identity. It NEVER independently creates or upgrades an
    IdentifiedVisitor — the ``identity_signals`` service imports zero
    IdentifiedVisitor write paths, structurally enforcing that invariant.

    PII: email is stored ciphertext + blind index only (same pattern as
    beam_identity_graph) — never plaintext. Decay is computed at READ time from
    ``created_at``; ``base_confidence`` is set once at write time and never mutated.

    ``id`` / ``created_at`` / ``updated_at`` come from ``Base``.
    """

    __tablename__ = "identity_signals"
    __table_args__ = (
        Index("idx_identity_signals_ip", "ip"),
        Index("idx_identity_signals_email_bidx", "email_bidx"),
    )

    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    ip: Mapped[str] = mapped_column(String(45), nullable=False)
    email_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_bidx: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # "sendgrid_open" | "sendgrid_click"
    signal_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # Set at write time (0.4-0.5 open, 0.6 click); decayed at read time, never here.
    base_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
