"""add outlier/internal-traffic damping columns

Outlier-traffic-damping plan (general-plans, 27-07-26), Step 5. Additive-only,
NON-DESTRUCTIVE: three columns, each with a safe default, so every existing row
backfills without a data migration.

  visitors.is_internal_suspect        BOOLEAN NOT NULL DEFAULT false
  visitors.internal_override          VARCHAR(20) NULL
  identified_visitors.is_internal_suspect BOOLEAN NOT NULL DEFAULT false
  sites.internal_damping_enabled      BOOLEAN NOT NULL DEFAULT false

REVERSIBILITY IS THE POINT. Unlike is_bot_suspect / is_abuse_flagged, the
is_internal_suspect columns are NOT sticky and are never OR-merged: a false
positive would silently remove a genuine prospect from the customer's aggregates
and deprioritise them for identity resolution, so it must be clearable. The
nullable internal_override column carries the human's tri-state call
(NULL / 'internal' / 'not_internal'), which wins over the automatic sweep
permanently and in BOTH directions.

Nothing here touches is_abuse_flagged, do_not_resolve, source_agent_visit_id, or
outreach eligibility. is_emailable_identity keeps exactly 3 parameters.

OFFLINE-VALIDATED ONLY (repo convention C2): this revision joins the queue of
migrations already pending live-apply. Never `alembic upgrade` against a real
environment as part of this plan.

Chained on b1e7f3c9d425 (sites.last_daily_digest_sent_at), confirmed live via
`alembic -c apps/api/alembic.ini heads` on 27-07-26 immediately before this file
was written (single head, no branching).

Revision ID: f3a7c9e21b48
Revises: b1e7f3c9d425
Create Date: 2026-07-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3a7c9e21b48"
down_revision: Union[str, None] = "b1e7f3c9d425"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "visitors",
        sa.Column(
            "is_internal_suspect",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "visitors",
        sa.Column("internal_override", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "identified_visitors",
        sa.Column(
            "is_internal_suspect",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "sites",
        sa.Column(
            "internal_damping_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("sites", "internal_damping_enabled")
    op.drop_column("identified_visitors", "is_internal_suspect")
    op.drop_column("visitors", "internal_override")
    op.drop_column("visitors", "is_internal_suspect")
