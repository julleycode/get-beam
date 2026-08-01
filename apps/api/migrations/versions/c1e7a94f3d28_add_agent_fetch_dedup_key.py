"""add agent_fetch_events.dedup_key — replay guard for agent fetch rows

Revision ID: c1e7a94f3d28
Revises: a2f8d61c9e37
Create Date: 2026-07-29

Additive and safe to apply to a live table:

- The new column is nullable with no server default, so the ALTER is a metadata-
  only change in Postgres 11+ and rewrites nothing.
- The unique index is PARTIAL (`WHERE dedup_key IS NOT NULL`). Every pre-existing
  row has a NULL key, and NULLs never conflict with each other in Postgres, so no
  existing row can violate it. There is therefore nothing to de-duplicate first
  and nothing to backfill — the guard applies only to rows written after this
  point, by the paths that supply a key.

Ordering note: the index is created AFTER the column in `upgrade` and dropped
BEFORE it in `downgrade`, so neither direction leaves an index referencing a
column that does not exist.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c1e7a94f3d28"
down_revision: Union[str, None] = "a2f8d61c9e37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_fetch_events",
        sa.Column("dedup_key", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "uq_agent_fetch_events_dedup_key",
        "agent_fetch_events",
        ["dedup_key"],
        unique=True,
        postgresql_where=sa.text("dedup_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_fetch_events_dedup_key", table_name="agent_fetch_events")
    op.drop_column("agent_fetch_events", "dedup_key")
