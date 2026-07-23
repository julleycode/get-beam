"""add company_graph table + beam_identity_graph geo columns

Revision ID: f8a2c1d9b3e7
Revises: c4e8f1a9d2b7
Create Date: 2026-07-23

Owned identity data layer — Phase 1. Purely additive, non-destructive:

* NEW ``company_graph`` table — durable cross-tenant IP→company graph (one row
  per (ip, source)), so a resolution paid/resolved once is reused across
  tenants instead of expiring in the Redis-only 30d cache.
* ``beam_identity_graph.city`` / ``.region`` / ``.country`` — nullable geo
  columns so a cross-tenant email match can inherit full profile, not just name.

Chained after c4e8f1a9d2b7 (the current alembic head, itself chained after the
three previously-pending migrations d11b39a6c843 → a1c7e4f92b83 → b3f9a1d2c7e5).
Confirmed head via migration graph at EXECUTE time. Docker-gated: never applied
against a live Postgres in the build sandbox.

See:
process/features/visitors-identity/active/owned-data-layer_23-07-26/owned-data-layer_PLAN_23-07-26.md
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f8a2c1d9b3e7"
down_revision: Union[str, None] = "c4e8f1a9d2b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "company_graph",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("domain", sa.String(253), nullable=True),
        sa.Column("company_name", sa.String(200), nullable=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_verified", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_company_graph_ip", "company_graph", ["ip"])
    op.create_index("idx_company_graph_domain", "company_graph", ["domain"])
    op.create_unique_constraint(
        "uq_company_graph_ip_source", "company_graph", ["ip", "source"]
    )

    # beam_identity_graph geo columns (nullable/additive).
    op.add_column("beam_identity_graph", sa.Column("city", sa.String(100), nullable=True))
    op.add_column("beam_identity_graph", sa.Column("region", sa.String(100), nullable=True))
    op.add_column("beam_identity_graph", sa.Column("country", sa.String(5), nullable=True))


def downgrade() -> None:
    op.drop_column("beam_identity_graph", "country")
    op.drop_column("beam_identity_graph", "region")
    op.drop_column("beam_identity_graph", "city")
    op.drop_constraint("uq_company_graph_ip_source", "company_graph", type_="unique")
    op.drop_index("idx_company_graph_domain", table_name="company_graph")
    op.drop_index("idx_company_graph_ip", table_name="company_graph")
    op.drop_table("company_graph")
