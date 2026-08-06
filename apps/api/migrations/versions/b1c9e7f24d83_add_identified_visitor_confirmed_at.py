"""add confirmed_at to identified_visitors

Identity-honesty Phase 1. Graph-sourced matches (RB2B / Leadpipe / Capturify /
beam_identity_network) now land on ``Visitor.identity_status = "candidate"``
instead of a flat "identified". A human promotes a candidate via the
confirm-candidate endpoint; ``confirmed_at`` is the timestamp of that human act.

Deliberately a NEW column rather than reusing ``resolved_at``: ``resolved_at`` is
set once at INSERT (``server_default=func.now()``) and means "when this row was
first created" — the fingerprint-match query orders by it — so stamping a later
confirmation into it would silently corrupt that meaning.

Additive and fully reversible: one nullable column, no default, no backfill, no
constraint, no index. Existing rows keep NULL, which reads correctly as "never
went through the candidate → confirm flow".

Revision ID: b1c9e7f24d83
Revises: a7d419e6c052
Create Date: 2026-08-04

"""
from alembic import op
import sqlalchemy as sa

revision = "b1c9e7f24d83"
down_revision = "a7d419e6c052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "identified_visitors",
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("identified_visitors", "confirmed_at")
