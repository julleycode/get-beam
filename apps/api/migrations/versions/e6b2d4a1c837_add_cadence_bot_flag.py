"""add visitors.is_bot_suspect + identified_visitors.is_bot_suspect (cadence bot flag)

Cadence-bot-flag plan (pixel feature, 26-07-26), Step 2. Additive-only,
NON-DESTRUCTIVE: two boolean columns, NOT NULL with server_default false, so
every existing row backfills to false without a data migration.

The columns are VISIBILITY-ONLY. Nothing in this migration (or the code that
reads these columns) touches is_abuse_flagged, do_not_resolve, agent_visits, or
outreach eligibility.

OFFLINE-VALIDATED ONLY (repo convention C2): this revision joins the queue of
migrations already pending live-apply. Never `alembic upgrade` against a real
environment as part of this plan.

Chained on d5b1f7c3a908 (sites.last_aggregated_at), confirmed live via
`alembic -c apps/api/alembic.ini heads` on 26-07-26 immediately before this file
was written (single head, no branching).

Revision ID: e6b2d4a1c837
Revises: d5b1f7c3a908
Create Date: 2026-07-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6b2d4a1c837"
down_revision: Union[str, None] = "d5b1f7c3a908"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "visitors",
        sa.Column(
            "is_bot_suspect",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "identified_visitors",
        sa.Column(
            "is_bot_suspect",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("identified_visitors", "is_bot_suspect")
    op.drop_column("visitors", "is_bot_suspect")
