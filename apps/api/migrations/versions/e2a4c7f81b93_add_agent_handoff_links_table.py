"""add agent_handoff_links table

Revision ID: e2a4c7f81b93
Revises: a3e9f1c7d2b5
Create Date: 2026-07-24

Handoff Detection Phase 02 (H2) — net-new fetch↔click handoff correlation link
surface. One row links an on-demand agent_fetch_events row to the human Visitor
whose AI-referral click landed on the same page from the same vendor family
within a bounded window. Structurally separate from the emailability guardrail
(SPEC Constraint 1 / AC-H2-3) — no source_agent_visit_id column, ever.
Additive-only (new table, zero changes to any existing table). See:
process/features/evallayer/active/handoff_23-07-26/phase-02-handoff-correlation_PLAN_23-07-26.md

down_revision re-verified live at EXECUTE (alembic heads) as a3e9f1c7d2b5 — the
visitors-identity "owned-data-layer" add_identity_signals migration, single head.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e2a4c7f81b93"
down_revision: Union[str, None] = "a3e9f1c7d2b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_handoff_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("site_id", sa.String(50), nullable=False),
        sa.Column("visitor_id", sa.String(100), nullable=False),
        sa.Column("agent_fetch_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("confidence", sa.String(10), nullable=False),
        sa.Column("method", sa.String(30), nullable=False, server_default="temporal-page-match"),
        sa.Column("delta_seconds", sa.Integer(), nullable=False),
        sa.Column("matched_page", sa.String(500), nullable=True),
        sa.UniqueConstraint("agent_fetch_event_id", name="uq_agent_handoff_links_fetch_event"),
    )
    op.create_index(
        "idx_agent_handoff_links_site_visitor", "agent_handoff_links",
        ["site_id", "visitor_id"],
    )
    op.create_index(
        "idx_agent_handoff_links_site_created", "agent_handoff_links",
        ["site_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_agent_handoff_links_site_created", table_name="agent_handoff_links")
    op.drop_index("idx_agent_handoff_links_site_visitor", table_name="agent_handoff_links")
    op.drop_table("agent_handoff_links")
