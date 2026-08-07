"""Identity co-op substrate — contribution events, credit ledger, consent trail.

identity-coop Phase 1 (visitors-identity, 07-08-26). Three append-only tables that
turn the implicit cross-tenant identity graph into an opt-in data co-op with a
spendable credit balance. Nothing here is read or written unless BOTH
``settings.identity_coop_enabled`` AND the per-site ``Site.contribution_enabled``
are True — both default False.

PII posture (locked constraint): a contribution event keys on ``email_bidx``, the
blind index from ``pii_crypto.email_hash`` — NEVER a plaintext email, never a
ciphertext column. There is no decrypt path out of these tables by design.

Privacy invariant (D-B): a row bearing an ``email_bidx`` may exist here ONLY for a
person whose ``beam_identity_graph`` write actually succeeded. The hook that writes
these rows is gated on ``_upsert_beam_identity``'s ``bool`` return, so a blocked
graph write (missing fingerprint, ``do_not_resolve``, or an ``erased`` /
``do_not_process`` / ``all`` tombstone) produces NOTHING here — not even an
excluded-reason row. That is why the co-op tables' absence from
``erasure_request.ERASURE_TARGETS`` is harmless rather than a privacy hole: no
record of an erased person can be created here after their erasure.

Balance is DERIVED (``SUM(amount)`` over unexpired, past-hold rows), never a
mutable column — same read-time-computation precedent as
``identity_signals.decay_confidence()``.

``id`` / ``created_at`` / ``updated_at`` come from ``Base``.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base

# excluded_reason vocabulary (D-B + D-C settled it to exactly these two + NULL):
#   'fraud_flagged' — is_abuse_flagged OR is_bot_suspect was set (AC-9)
#   'duplicate'     — this (site_id, email_bidx) already accrued once, ever (D-E)
#   NULL            — accrued normally
# 'abuse_flagged' is subsumed by 'fraud_flagged'; 'erased' is retired because no
# row is ever written for a blocked graph write (D-B).
EXCLUDED_REASONS = ("fraud_flagged", "duplicate")

# entry_type vocabulary. Phase 1 only ever writes ACCRUE; SPEND/EXPIRE land in
# Phase 2 (spend gate + expiry sweep) against this same frozen schema.
LEDGER_ENTRY_TYPES = ("ACCRUE", "SPEND", "EXPIRE")


class ContributionEvent(Base):
    """One audit row per (site, identity, day) contribution attempt.

    Append-only. ``uq_coop_contrib_site_email_day`` is the merge-awareness
    mechanism (AC-3): the same person resolved twice under two different
    ``visitor_id``s on the same day collapses to ONE row via
    ``ON CONFLICT DO NOTHING``. It keys on neither ``visitor_id`` nor the graph
    row id, so merged-duplicate visitors are structurally irrelevant here.

    ``uq_coop_accrued_site_email`` is the stricter ACCRUAL rule (D-E): a site
    earns at most ONE credit per identity for all time. A repeat resolve on a
    later day still records an event row for auditability, but with
    ``accrued=False, excluded_reason='duplicate'`` and no ledger row. Enforced as
    a DB partial unique index, not only in service code, so a concurrent race
    cannot mint a second credit.
    """

    __tablename__ = "identity_contribution_events"
    __table_args__ = (
        UniqueConstraint(
            "site_id",
            "email_bidx",
            "contributed_on",
            name="uq_coop_contrib_site_email_day",
        ),
        Index(
            "uq_coop_accrued_site_email",
            "site_id",
            "email_bidx",
            unique=True,
            postgresql_where=text("accrued IS TRUE"),
        ),
        Index("idx_coop_contrib_email_bidx", "email_bidx"),
        Index("idx_coop_contrib_site_id", "site_id"),
    )

    # Attribution unit — matches beam_identity_graph.source_site_id's shape.
    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    # Blind index ONLY (pii_crypto.email_hash). Never a plaintext email.
    email_bidx: Mapped[str] = mapped_column(String(64), nullable=False)
    contributed_on: Mapped[date] = mapped_column(Date, nullable=False)
    source_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    accrued: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    excluded_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)


class CreditLedgerEntry(Base):
    """Append-only, lot-based credit ledger. Balance is never stored (AC-8).

    Scoped to ``site_id`` only, with NO ``user_id`` column (D-D): ``site_id`` is
    the attribution unit, and ``user_id`` is always derivable via
    ``Site.user_id``, so storing it would be denormalized state that goes stale
    if a site is ever reassigned. Phase 2's spend gate therefore aggregates
    ACROSS a user's sites by joining
    ``identity_credit_ledger.site_id -> sites.site_id -> sites.user_id`` before
    applying the balance at ``billing.check_usage_allowed(db, user_id)``. Phase 2
    MUST NOT add a ``user_id`` column to this frozen schema.

    Each ACCRUE row is its own lot (``lot_id`` = own id) carrying a provisional
    hold (``spendable_at``) and an expiry (``expires_at``). SPEND/EXPIRE rows
    (Phase 2) carry a negative ``amount`` and point ``lot_id`` at the ACCRUE lot
    they draw from, which keeps expiry an explicit auditable event rather than a
    silent read-time disappearance.
    """

    __tablename__ = "identity_credit_ledger"
    __table_args__ = (
        Index("idx_coop_ledger_site_id", "site_id"),
        Index("idx_coop_ledger_lot_id", "lot_id"),
        Index("idx_coop_ledger_expires_at", "expires_at"),
    )

    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    # 'ACCRUE' | 'SPEND' | 'EXPIRE' (LEDGER_ENTRY_TYPES)
    entry_type: Mapped[str] = mapped_column(String(10), nullable=False)
    # Positive for ACCRUE; negative for SPEND and EXPIRE.
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    # ACCRUE: own id. SPEND/EXPIRE: the ACCRUE lot drawn from.
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    # ACCRUE only — created_at + coop_credit_hold_hours (provisional hold).
    spendable_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # ACCRUE only — created_at + coop_credit_expiry_days.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # ACCRUE only — provenance back to the contribution event.
    contribution_event_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )


class ContributionConsentAcceptance(Base):
    """Append-only audit trail of co-op terms acceptance (AC-10).

    The flag (``Site.contribution_enabled``) is mutable and can be toggled off
    and on; this trail is NOT — there is no update or delete path. The flag
    cannot flip ON via the API without an acceptance row written in the SAME
    transaction.

    ``terms_version`` is an immutable snapshot hash of the exact policy text (a
    64-char lowercase hex digest), never a live pointer to editable copy — so an
    acceptance recorded today cannot be retroactively re-pointed at reworded
    terms.
    """

    __tablename__ = "identity_contribution_consent_acceptances"
    __table_args__ = (Index("idx_coop_consent_site_id", "site_id"),)

    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    terms_version: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    accepted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
