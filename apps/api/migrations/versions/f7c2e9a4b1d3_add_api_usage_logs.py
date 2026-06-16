"""add api_usage_logs ledger (and merge the 3 divergent migration heads)

Revision ID: f7c2e9a4b1d3
Revises: d5a2b7c1e9f3, e7b4c2f9a1d8, f1a9c4d7e2b8
Create Date: 2026-06-16

Phase 2 of the API-cost-dashboard plan. Unified per-call cost ledger that the
costs dashboard reads (identity / enrichment / email / ai / osint).

This is ALSO a merge revision: three migrations had forked off b7e1a2c9d4f0
(c3f8a1d6e2b4→d5a2b7c1e9f3, e6b3c2a9f1d7→e7b4c2f9a1d8, f1a9c4d7e2b8), leaving
three heads. `alembic upgrade head` errors on multiple heads, which would break
the Dockerfile deploy step. Joining all three here collapses them to one head.

Backfills existing resolution_logs (identity spend) into the ledger so the
dashboard keeps historical identity costs after switching its data source.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f7c2e9a4b1d3"
down_revision: Union[str, Sequence[str], None] = (
    "d5a2b7c1e9f3",
    "e7b4c2f9a1d8",
    "f1a9c4d7e2b8",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_usage_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", sa.String(length=50), nullable=True),
        sa.Column("visitor_id", sa.String(length=100), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("operation", sa.String(length=50), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("units", sa.Integer(), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_api_usage_site_created", "api_usage_logs", ["site_id", "created_at"]
    )
    op.create_index(
        "idx_api_usage_category_created", "api_usage_logs", ["category", "created_at"]
    )
    op.create_index("idx_api_usage_provider", "api_usage_logs", ["provider"])
    op.create_index("ix_api_usage_logs_site_id", "api_usage_logs", ["site_id"])

    # One-time backfill: existing identity-resolution spend → unified ledger so
    # the dashboard keeps history after it switches to read api_usage_logs.
    # gen_random_uuid() is in Postgres core (>=13). Going forward identity
    # dual-writes both tables, so this never double-counts.
    op.execute(
        """
        INSERT INTO api_usage_logs
            (id, site_id, visitor_id, provider, category, success, cost_usd,
             response_time_ms, created_at)
        SELECT gen_random_uuid(), site_id, visitor_id, provider, 'identity',
               success, cost_usd, response_time_ms, created_at
        FROM resolution_logs
        """
    )


def downgrade() -> None:
    op.drop_index("ix_api_usage_logs_site_id", table_name="api_usage_logs")
    op.drop_index("idx_api_usage_provider", table_name="api_usage_logs")
    op.drop_index("idx_api_usage_category_created", table_name="api_usage_logs")
    op.drop_index("idx_api_usage_site_created", table_name="api_usage_logs")
    op.drop_table("api_usage_logs")
