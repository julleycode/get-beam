"""backfill NULL events.event_id and unique (site_id, event_id)

Phase 2 F1: replace global unique index uq_events_event_id with composite
unique (site_id, event_id) named uq_events_site_event_id so the same client
id on two sites inserts both rows. Additive backfill of remaining NULL
event_id values with gen_random_uuid()::text first so the unique constraint
can be created.

Column stays nullable this phase (NOT NULL waits until 24h of zero null
inserts). Do NOT apply this revision against Supabase prod from cook —
local docker Postgres :5433 only.

Chained on live head b7e3c9a4f215 (verified via `alembic heads` 18-08-26).

Revision ID: c3f6a9d1e8b2
Revises: b7e3c9a4f215
Create Date: 2026-08-18
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c3f6a9d1e8b2"
down_revision: Union[str, None] = "b7e3c9a4f215"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_INDEX = "uq_events_event_id"
_NEW_CONSTRAINT = "uq_events_site_event_id"


def upgrade() -> None:
    op.execute(
        "UPDATE events SET event_id = gen_random_uuid()::text WHERE event_id IS NULL"
    )
    op.drop_index(_OLD_INDEX, table_name="events")
    op.create_unique_constraint(
        _NEW_CONSTRAINT,
        "events",
        ["site_id", "event_id"],
    )


def downgrade() -> None:
    op.drop_constraint(_NEW_CONSTRAINT, "events", type_="unique")
    op.create_index(_OLD_INDEX, "events", ["event_id"], unique=True)
