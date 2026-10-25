"""add paid_requests (InFlow x402 seller ledger)

Additive only. One row per distinct x402 payment payload presented to
/api/v1/paid/*; UNIQUE payment_hash backs replay protection, the remaining
columns back reconciliation against the InFlow ledger. Dormant until
INFLOW_X402_ENABLED is flipped on.

Revision ID: d3f8a2c61b47
Revises: c5a91f3e07d4
Create Date: 2026-10-25

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d3f8a2c61b47"
down_revision = "c5a91f3e07d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paid_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("payment_hash", sa.String(length=64), nullable=False),
        sa.Column("route_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("scheme", sa.String(length=32), nullable=True),
        sa.Column("network", sa.String(length=64), nullable=True),
        sa.Column("asset", sa.String(length=128), nullable=True),
        sa.Column("amount", sa.String(length=80), nullable=True),
        sa.Column("payer", sa.String(length=256), nullable=True),
        sa.Column("transaction", sa.String(length=256), nullable=True),
        sa.Column("error_reason", sa.String(length=256), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
        sa.Column("payment_response_header", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.UniqueConstraint("payment_hash", name="paid_requests_payment_hash_key"),
    )
    op.create_index("ix_paid_requests_route_id", "paid_requests", ["route_id"])


def downgrade() -> None:
    op.drop_index("ix_paid_requests_route_id", table_name="paid_requests")
    op.drop_table("paid_requests")
