"""Platform-level erasure queue (cross-tenant identity graph).

A per-visitor deletion request on one tenant's site deletes that tenant's own
rows synchronously, but the shared ``beam_identity_graph`` is cross-tenant: the
row that must go may carry ANY site's ``source_site_id``. Doing that work inside
the request would also turn the endpoint into an existence oracle (a tenant
could probe whether an arbitrary person is in the shared graph). So the endpoint
becomes a *producer*: it enqueues a row here and returns immediately, and an
APScheduler sweep drains the queue out of band.

PLAINTEXT-FREE BY CONSTRUCTION. The queue stores only the blind index
(``email_hash`` = HMAC of the normalised email, see ``services/pii_crypto.py``)
and browser fingerprints — never an address. This is why the sweep can never
call ``suppression._cascade_suppress`` (which needs plaintext throughout): the
tombstones it writes reuse the stored blind index directly as
``SuppressionEntry.email_hash``, which is valid because both are the same HMAC
under the same key.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base

# Extensible fan-out target list. Adding "company_graph" later once the legal
# read lands (KG-3) is a one-constant change with no schema migration.
# "identity_signals" (H6): the corroborating-signal table holds decryptable
# email_ciphertext keyed by the same blind index this queue already carries, so
# it must be erased in the same sweep — otherwise decryptable PII for an erased
# person survives the erasure.
ERASURE_TARGETS: tuple[str, ...] = ("beam_identity_graph", "identity_signals")

ERASURE_STATUSES: tuple[str, ...] = ("pending", "processing", "done", "failed")


class ErasureRequest(Base):
    """One queued cross-tenant erasure, in state pending → processing → done|failed.

    The claim (``status='processing'`` + ``attempts`` increment) commits in its
    OWN transaction, separate from the destructive work — otherwise a crash
    mid-row rolls the attempts increment back too, ``attempts >= max_attempts``
    can never trip, and a permanently-failing request is indistinguishable from
    one never attempted (a silent infinite retry on a GDPR clock).
    """

    __tablename__ = "erasure_requests"
    __table_args__ = (
        Index("idx_erasure_requests_status_created", "status", "created_at"),
        Index("idx_erasure_requests_site", "requesting_site_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Audit: which tenant asked. Matching into the shared graph deliberately
    # ignores source_site_id, so this is the only record of who requested it.
    requesting_site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    visitor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Match keys, collected BEFORE the tenant's own DELETE loop destroys the
    # rows they come from. Blind indexes only — never a plaintext address.
    email_bidx_list: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(64)), nullable=True
    )
    fingerprint_list: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(64)), nullable=True
    )
    targets: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)), nullable=False, default=lambda: list(ERASURE_TARGETS)
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # FORENSIC MARKER ONLY (§4b option (b), C-14, KG-8). Set when the per-site
    # enqueue volume marker tripped. It records volumetric abuse for
    # after-the-fact human review and PREVENTS NOTHING: the row is still claimed
    # and processed identically to an unflagged one. It MUST NEVER appear in a
    # WHERE clause on any execution path — its sole reader is the operator
    # queue-health surface's throttle_flagged_count.
    throttle_flagged: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # MUST NEVER CONTAIN PII — sanitised at the write site (truncated to 500
    # chars, email-shaped substrings stripped).
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
