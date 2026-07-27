"""add request_logs — admin request/response debug capture

Revision ID: a2f8d61c9e37
Revises: f3a7c9e21b48
Create Date: 2026-07-27

Additive only: one new table, no column added to and no constraint placed on any
existing table. Nothing reads or writes it until `request_log_enabled` is turned
on (default False), so applying this migration is a no-behavior-change step.

Bodies land here already redacted (services/log_redaction.py) — emails are
domain-only, credential-shaped keys are "***". The table carries a 7-day purge
(services/retention.py) rather than the 90-day raw-event window, because these
rows hold richer per-request detail.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a2f8d61c9e37"
down_revision: Union[str, None] = "f3a7c9e21b48"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "request_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("query_params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("reason_detail", sa.Text(), nullable=True),
        sa.Column("site_id", sa.String(length=50), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("client_ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("request_headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("request_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_request_logs_created", "request_logs", ["created_at"])
    op.create_index("idx_request_logs_reason_created", "request_logs", ["reason", "created_at"])
    op.create_index("idx_request_logs_site_created", "request_logs", ["site_id", "created_at"])
    op.create_index("idx_request_logs_status_created", "request_logs", ["status_code", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_request_logs_status_created", table_name="request_logs")
    op.drop_index("idx_request_logs_site_created", table_name="request_logs")
    op.drop_index("idx_request_logs_reason_created", table_name="request_logs")
    op.drop_index("idx_request_logs_created", table_name="request_logs")
    op.drop_table("request_logs")
