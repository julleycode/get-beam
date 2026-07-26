"""add sites.last_daily_digest_sent_at (daily activity digest throttle)

Daily-digest feature (26-07-26). Additive-only, NON-DESTRUCTIVE: one nullable
timestamp column. NULL = never sent, so every existing site is eligible on the
first run without a data migration.

Deliberately a SEPARATE column from `last_outcome_digest_sent_at` — the weekly
forwardable outcomes digest and the daily owner-only activity digest throttle
independently and must never starve each other.

Chained on a4f7c2e9d31b (add_agent_profile), confirmed live via
`alembic -c apps/api/alembic.ini heads` immediately before this file was written
(single head, no branching).

Revision ID: b1e7f3c9d425
Revises: a4f7c2e9d31b
Create Date: 2026-07-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1e7f3c9d425"
down_revision: Union[str, None] = "a4f7c2e9d31b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sites",
        sa.Column("last_daily_digest_sent_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sites", "last_daily_digest_sent_at")
