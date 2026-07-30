"""add visitors.is_agent_operated + identified_visitors.is_agent_operated (WS2)

WS2 agent-driven session classifier plan (agent-native-revenue, 30-07-26),
Step 5. Additive-only, NON-DESTRUCTIVE: two boolean columns, NOT NULL with
server_default false, so every existing row backfills to false without a data
migration.

The columns are VISIBILITY-ONLY. Nothing in this migration (or the code that
reads these columns) touches is_abuse_flagged, do_not_resolve, agent_visits, or
outreach eligibility.

OFFLINE-VALIDATED ONLY (repo convention): this revision joins the queue of
migrations already pending live-apply. Never `alembic upgrade` against a real
environment as part of this plan — live-apply is a program hard stop.

Chained on a2f8d61c9e37, confirmed live via
`alembic -c apps/api/alembic.ini heads` on 30-07-26 immediately before this file
was written (single head, no branching). Offline `--sql` dry-runs in this repo
need an EXPLICIT <from>:<to> rev range (the `upgrade head --sql` shorthand fails
mid-chain on b7d3e9f1a4c2's sa.inspect call) — e.g.
`alembic upgrade a2f8d61c9e37:head --sql`.

Revision ID: f4c1a9e2d3b8
Revises: a2f8d61c9e37
Create Date: 2026-07-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4c1a9e2d3b8"
down_revision: Union[str, None] = "a2f8d61c9e37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "visitors",
        sa.Column(
            "is_agent_operated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "identified_visitors",
        sa.Column(
            "is_agent_operated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("identified_visitors", "is_agent_operated")
    op.drop_column("visitors", "is_agent_operated")
