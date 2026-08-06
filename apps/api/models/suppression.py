import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class SuppressionEntry(Base):
    """Privacy suppression list (GDPR / CCPA opt-out).

    An entry means: do not resolve / sell / email this person, per their
    opt-out request. Keyed by a blind index (HMAC of the email) so we never
    store a second plaintext copy of the address.

    Scope:
    - "all"            — full opt-out (blocks resolve + sell + email)
    - "do_not_process" — GDPR: do not resolve/enrich
    - "do_not_sell"    — CCPA: do not export to ad audiences
    - "do_not_email"   — do not send marketing email
    - "erased"         — graph erasure tombstone; blocks any future cross-tenant
                         graph write. Written by the erasure sweep
                         (services/graph_erasure.py) using the stored blind
                         index directly as email_hash, so no plaintext is ever
                         needed. Durable audit marker: it records that a
                         person's shared-graph rows were hard-deleted.
    """

    __tablename__ = "suppression_list"
    __table_args__ = (
        Index("uq_suppression_hash_scope", "email_hash", "scope", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="all")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
