"""add sites.last_aggregated_at (incremental aggregation watermark)

Capacity-hardening plan Phase 3 (W1), decision D2. Additive NULLABLE column only
— no backfill, no data movement, no default. NULL means "never aggregated
incrementally", which the aggregator treats as "do a full recompute, then stamp".

OFFLINE-VALIDATED ONLY (plan non-goal + repo convention C2): this revision joins
the queue of migrations already pending live-apply. Never `alembic upgrade`
against a real environment as part of this plan.

Chained on c8e4f2a6b1d9 (ad_audience_links), confirmed live via `alembic heads`
on 26-07-26 immediately before this file was written (E11).

Revision ID: d5b1f7c3a908
Revises: c8e4f2a6b1d9
Create Date: 2026-07-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5b1f7c3a908"
down_revision: Union[str, None] = "c8e4f2a6b1d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sites",
        sa.Column("last_aggregated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sites", "last_aggregated_at")
