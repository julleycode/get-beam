"""add agent_leads + agent_tool_calls — WS3 agent concierge conversion + metrics

Revision ID: c5e0f2b8d163
Revises: b4d9e1a7c052
Create Date: 2026-07-30

Additive only: two new tables, no change to any existing table.

- agent_leads: append-only agent-provenance sales lead, one row per conversion-
  tool call. STRUCTURALLY ISOLATED from the identity graph — no visitor_id, no
  email column, no FK to identified_visitors/visitors. resolved_company_domain is
  a best-effort FREE rDNS string, never a paid-provider identity.
- agent_tool_calls: append-only MCP tool-call metric row (kill-test
  instrumentation). Dedicated table (not columns on agent_fetch_events) so a
  machine-to-machine JSON-RPC caller with no classifiable UA never needs a
  NOT-NULL vendor.

Nothing writes either table until agent_concierge_conversion_enabled /
agent_concierge_qualification_enabled are turned on (both default False), so
applying this migration is a no-behavior-change step.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c5e0f2b8d163"
down_revision: Union[str, None] = "b4d9e1a7c052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("site_id", sa.String(length=50), nullable=False),
        sa.Column("tool_name", sa.String(length=30), nullable=False),
        sa.Column("use_case", sa.String(length=200), nullable=True),
        sa.Column("company_size", sa.String(length=100), nullable=True),
        sa.Column("evaluating_against", sa.String(length=200), nullable=True),
        sa.Column("resolved_company_domain", sa.String(length=253), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("notified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_agent_leads_site_created", "agent_leads", ["site_id", "created_at"])

    op.create_table(
        "agent_tool_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("site_id", sa.String(length=50), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("tool_name", sa.String(length=40), nullable=True),
        sa.Column("params_provided", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("params_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_gated_tool", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_agent_tool_calls_site_created", "agent_tool_calls", ["site_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_agent_tool_calls_site_created", table_name="agent_tool_calls")
    op.drop_table("agent_tool_calls")
    op.drop_index("idx_agent_leads_site_created", table_name="agent_leads")
    op.drop_table("agent_leads")
