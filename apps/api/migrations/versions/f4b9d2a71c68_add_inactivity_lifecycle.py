"""add inactivity lifecycle columns (re-engagement reminder + auto-pause)

Four additive nullable-or-defaulted columns; no data migration, no index.

`users.last_active_at` is NOT NULL with a ``now()`` server_default on purpose:
backfilling every existing row to "active right now" IS the rollout grace
period. The earliest possible auto-pause is therefore migration + 14 days, with
a reminder forced in between at +7 — a day-one mass-pause cannot happen.

No new indexes: all three cohort queries run once a day over the (small) users
and sites tables. Add one only when a real plan shows a seq-scan cost.

tz convention follows the existing tables: ``users.*`` are timezone-aware,
``sites.auto_paused_at`` is naive UTC like every other stamp on `sites`.

Revision ID: f4b9d2a71c68
Revises: e2b7c94a1f38
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa

revision = "f4b9d2a71c68"
down_revision = "e2b7c94a1f38"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("last_reengagement_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("install_nudge_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("sites", sa.Column("auto_paused_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("sites", "auto_paused_at")
    op.drop_column("users", "install_nudge_sent_at")
    op.drop_column("users", "last_reengagement_sent_at")
    op.drop_column("users", "last_active_at")
