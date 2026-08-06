"""add visitors.is_agent_operated + identified_visitors.is_agent_operated (WS2)

WS2 agent-session activation plan (pixel, 07-08-26), Step 4. Additive-only,
NON-DESTRUCTIVE: two boolean columns, NOT NULL with server_default false, so
every existing row backfills to false without a data migration.

The columns are VISIBILITY-ONLY. Nothing in this migration (or the code that
reads these columns) touches is_abuse_flagged, do_not_resolve, agent_visits, or
outreach eligibility. is_emailable_identity() keeps its exact 3-parameter
signature — see the locked invariant in
f3a7c9e21b48_add_internal_traffic_damping.py.

Content is carried over from the abandoned branch revision f4c1a9e2d3b8, but the
revision/down_revision header is freshly authored: that file chained on
a2f8d61c9e37, a stale head from the branch's own history that never existed on
this line.

OFFLINE-VALIDATED ONLY (repo convention): this revision joins the queue of
migrations already pending live-apply. Never `alembic upgrade` against a real
environment as part of this plan — live-apply is a separate explicit operator
action. Offline `--sql` dry-runs in this repo need an EXPLICIT <from>:<to> rev
range (the `upgrade head --sql` shorthand fails mid-chain on b7d3e9f1a4c2's
sa.inspect call).

Chained on b8e3f6a2c904 (add_events_agent_sig, authored minutes earlier in the
same EXECUTE pass), which chains on a4f2b8c15d70 — confirmed the live single head
via `alembic -c apps/api/alembic.ini heads` on 07-08-26 immediately before that
file was written.

Revision ID: c9f4a7b31e85
Revises: b8e3f6a2c904
Create Date: 2026-08-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9f4a7b31e85"
down_revision: Union[str, None] = "b8e3f6a2c904"
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
