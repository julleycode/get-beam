"""add agent_fetch_events table

Revision ID: c4e8f1a9d2b7
Revises: b3f9a1d2c7e5
Create Date: 2026-07-23

Handoff Detection Phase 01 (H1) — net-new append-only per-hit agent fetch event
surface, tagged on-demand vs index. Structurally separate from Visitor/Event
(SPEC D1) and additive-only (new table, zero changes to any existing table). See:
process/features/evallayer/active/handoff_23-07-26/phase-01-fetch-events-tiering_PLAN_23-07-26.md
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c4e8f1a9d2b7"
down_revision: Union[str, None] = "b3f9a1d2c7e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_fetch_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("site_id", sa.String(50), nullable=False),
        sa.Column("vendor", sa.String(30), nullable=False),
        sa.Column("raw_ua_token", sa.String(50), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("page_path", sa.String(500), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("verification_method", sa.String(20), nullable=False, server_default="ua-only"),
    )
    op.create_index(
        "idx_agent_fetch_events_site_created", "agent_fetch_events",
        ["site_id", "created_at"],
    )
    op.create_index(
        "idx_agent_fetch_events_site_path_tier_created", "agent_fetch_events",
        ["site_id", "page_path", "tier", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_agent_fetch_events_site_path_tier_created", table_name="agent_fetch_events")
    op.drop_index("idx_agent_fetch_events_site_created", table_name="agent_fetch_events")
    op.drop_table("agent_fetch_events")
