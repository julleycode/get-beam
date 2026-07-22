"""add company-resolution fields (EvalLayer Phase 05)

Revision ID: a1c7e4f92b83
Revises: d11b39a6c843
Create Date: 2026-07-22

EvalLayer Phase 05 — company-resolution -> outreach feed. Three purely-additive
schema changes:

* ``visitors.is_agent_derived`` — marks a synthetic Visitor row created by the
  agent-company-resolution sweep so every human-facing query can exclude it
  (SPEC AC2). BOOLEAN NOT NULL server_default 'false' — mirrors the existing
  ``do_not_resolve`` column pattern; existing rows are valid as human rows.
* ``identified_visitors.source_agent_visit_id`` — the unforgeable agent-origin
  marker (VARCHAR NULL, stores the AgentVisit.id UUID as a STRING) that Phase 7's
  ``is_emailable_identity`` guard reads. Set atomically at row-insert time by the
  sweep; NULL for every human-resolved row.
* ``agent_visits.resolved_company_id`` — add the FK constraint to companies.id
  (the column already exists nullable, no FK per Phase 1). ondelete='SET NULL'
  matches the house convention (see a2e6c9b4d1f8) — a deleted Company must never
  cascade-delete the AgentVisit rollup row.

See:
process/features/evallayer/active/evallayer_22-07-26/phase-05-company-resolution_PLAN_22-07-26.md
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1c7e4f92b83"
down_revision: Union[str, None] = "d11b39a6c843"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "visitors",
        sa.Column(
            "is_agent_derived",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "identified_visitors",
        sa.Column("source_agent_visit_id", sa.String(64), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_visits_resolved_company_id",
        "agent_visits",
        "companies",
        ["resolved_company_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_agent_visits_resolved_company_id", "agent_visits", type_="foreignkey"
    )
    op.drop_column("identified_visitors", "source_agent_visit_id")
    op.drop_column("visitors", "is_agent_derived")
