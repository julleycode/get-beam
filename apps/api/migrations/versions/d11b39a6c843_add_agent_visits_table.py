"""add agent_visits table

Revision ID: d11b39a6c843
Revises: b8f3c1d92a47
Create Date: 2026-07-22

EvalLayer Phase 01 — net-new agent-visit surface, structurally separate from
Visitor/Event (SPEC D1). See:
process/features/evallayer/active/evallayer_22-07-26/phase-01-data-model-classifier_PLAN_22-07-26.md
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d11b39a6c843"
down_revision: Union[str, None] = "b8f3c1d92a47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_visits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("site_id", sa.String(50), nullable=False),
        sa.Column("vendor", sa.String(30), nullable=False),
        sa.Column("product_or_ua_token", sa.String(50), nullable=False),
        sa.Column("verification_method", sa.String(20), nullable=False, server_default="ua-only"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("page_paths", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("visit_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("resolved_company_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("idx_agent_visits_vendor", "agent_visits", ["vendor"])
    op.create_index("idx_agent_visits_site_last_seen", "agent_visits", ["site_id", "last_seen_at"])
    op.create_unique_constraint(
        "uq_agent_visits_site_vendor_token", "agent_visits",
        ["site_id", "vendor", "product_or_ua_token"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_agent_visits_site_vendor_token", "agent_visits", type_="unique")
    op.drop_index("idx_agent_visits_site_last_seen", table_name="agent_visits")
    op.drop_index("idx_agent_visits_vendor", table_name="agent_visits")
    op.drop_table("agent_visits")
