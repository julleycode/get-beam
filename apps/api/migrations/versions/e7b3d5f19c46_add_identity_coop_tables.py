"""add identity co-op tables (contribution events, credit ledger, consent trail)

identity-coop Phase 1 (visitors-identity, 07-08-26), steps A2/A4.
Additive-only, NON-DESTRUCTIVE: three new tables plus their indexes. No existing
table, column, or constraint is touched, so reverting the code leaves the tables
as harmless orphans.

The tables are plaintext-free by construction: contribution events store the
``email_bidx`` blind index (pii_crypto.email_hash) and never an email address.
There is no ciphertext column and no decrypt path.

Two DISTINCT uniqueness rules, both required and NOT redundant:

* ``uq_coop_contrib_site_email_day`` on (site_id, email_bidx, contributed_on) —
  the AUDIT/merge-awareness key (AC-3). Collapses the same person resolved twice
  under two visitor_ids on the same day into one event row.
* ``uq_coop_accrued_site_email`` — a PARTIAL unique index on
  (site_id, email_bidx) WHERE accrued IS TRUE — the ACCRUAL key (D-E). A site
  earns at most ONE credit per identity for all time. A repeat resolve on a later
  day still records an event row (accrued=False, excluded_reason='duplicate') but
  mints no credit. This lives in the DB, not only in service code, so a
  concurrent race cannot double-credit. Partial indexes cannot be expressed as a
  UniqueConstraint, hence op.create_index(..., postgresql_where=...).

Chained on d1a6c4e93f27 (add_erasure_requests) — confirmed the live single head
via `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` immediately
before this file was written. Never hardcode a head; re-run `heads` before
applying, since concurrent programs advance it.

Revision ID: e7b3d5f19c46
Revises: d1a6c4e93f27
Create Date: 2026-08-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7b3d5f19c46"
down_revision: Union[str, None] = "d1a6c4e93f27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "identity_contribution_events",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("site_id", sa.String(length=50), nullable=False),
        sa.Column("email_bidx", sa.String(length=64), nullable=False),
        sa.Column("contributed_on", sa.Date(), nullable=False),
        sa.Column("source_provider", sa.String(length=50), nullable=True),
        sa.Column(
            "accrued", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("excluded_reason", sa.String(length=30), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "site_id",
            "email_bidx",
            "contributed_on",
            name="uq_coop_contrib_site_email_day",
        ),
    )
    op.create_index(
        "idx_coop_contrib_email_bidx",
        "identity_contribution_events",
        ["email_bidx"],
    )
    op.create_index(
        "idx_coop_contrib_site_id", "identity_contribution_events", ["site_id"]
    )
    # D-E: at most one ACCRUED event per (site, identity), for all time.
    op.create_index(
        "uq_coop_accrued_site_email",
        "identity_contribution_events",
        ["site_id", "email_bidx"],
        unique=True,
        postgresql_where=sa.text("accrued IS TRUE"),
    )

    op.create_table(
        "identity_credit_ledger",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("site_id", sa.String(length=50), nullable=False),
        sa.Column("entry_type", sa.String(length=10), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=False),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("spendable_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "contribution_event_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )
    op.create_index("idx_coop_ledger_site_id", "identity_credit_ledger", ["site_id"])
    op.create_index("idx_coop_ledger_lot_id", "identity_credit_ledger", ["lot_id"])
    op.create_index(
        "idx_coop_ledger_expires_at", "identity_credit_ledger", ["expires_at"]
    )

    op.create_table(
        "identity_contribution_consent_acceptances",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("site_id", sa.String(length=50), nullable=False),
        sa.Column("terms_version", sa.String(length=64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "accepted_by_user_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_coop_consent_site_id",
        "identity_contribution_consent_acceptances",
        ["site_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_coop_consent_site_id",
        table_name="identity_contribution_consent_acceptances",
    )
    op.drop_table("identity_contribution_consent_acceptances")

    op.drop_index("idx_coop_ledger_expires_at", table_name="identity_credit_ledger")
    op.drop_index("idx_coop_ledger_lot_id", table_name="identity_credit_ledger")
    op.drop_index("idx_coop_ledger_site_id", table_name="identity_credit_ledger")
    op.drop_table("identity_credit_ledger")

    op.drop_index(
        "uq_coop_accrued_site_email", table_name="identity_contribution_events"
    )
    op.drop_index(
        "idx_coop_contrib_site_id", table_name="identity_contribution_events"
    )
    op.drop_index(
        "idx_coop_contrib_email_bidx", table_name="identity_contribution_events"
    )
    op.drop_table("identity_contribution_events")
