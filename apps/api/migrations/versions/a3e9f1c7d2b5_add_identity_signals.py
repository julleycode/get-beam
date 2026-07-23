"""add identity_signals table

Revision ID: a3e9f1c7d2b5
Revises: f8a2c1d9b3e7
Create Date: 2026-07-23

Owned identity data layer — Phase 2. Purely additive, non-destructive.

NEW ``identity_signals`` table — one row per corroborating engagement event
(SendGrid open/click). Strictly CORROBORATING: consumed only to bump confidence
on an already-matched identity, never to create/upgrade an IdentifiedVisitor.
Email stored ciphertext + blind index only (same PII pattern as
beam_identity_graph) — never plaintext.

Chained after f8a2c1d9b3e7 (Phase 1 company_graph migration). Docker-gated:
never applied against a live Postgres in the build sandbox.

See:
process/features/visitors-identity/active/owned-data-layer_23-07-26/owned-data-layer_PLAN_23-07-26.md
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a3e9f1c7d2b5"
down_revision: Union[str, None] = "f8a2c1d9b3e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "identity_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("site_id", sa.String(50), nullable=False),
        sa.Column("ip", sa.String(45), nullable=False),
        sa.Column("email_ciphertext", sa.Text, nullable=True),
        sa.Column("email_bidx", sa.String(64), nullable=True),
        sa.Column("signal_type", sa.String(30), nullable=False),
        sa.Column("base_confidence", sa.Float, nullable=False, server_default="0"),
    )
    op.create_index("idx_identity_signals_ip", "identity_signals", ["ip"])
    op.create_index("idx_identity_signals_email_bidx", "identity_signals", ["email_bidx"])


def downgrade() -> None:
    op.drop_index("idx_identity_signals_email_bidx", table_name="identity_signals")
    op.drop_index("idx_identity_signals_ip", table_name="identity_signals")
    op.drop_table("identity_signals")
