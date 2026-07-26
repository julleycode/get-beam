"""add ingest abuse flags (events + visitors + identified_visitors)

Revision ID: c7d3b8e1f624
Revises: a9f2c1e7b4d6
Create Date: 2026-07-25

ingest-abuse-hardening Phase 4. Adds the write-time abuse marker and its
propagation columns:

  * ``events.is_flagged_abuse``            — set at insert time when the P3 site
    ceiling tripped or the P4 velocity check fired (flag-but-store: the row is
    kept, just excluded downstream).
  * ``ix_events_site_flagged``             — supports the aggregator's exclusion
    filter and the P5 ingest-health query.
  * ``visitors.is_abuse_flagged``          — BOOL_OR rollup of the above, sticky
    across recomputes (mirrors events.optout -> visitors.do_not_resolve).
  * ``identified_visitors.is_abuse_flagged`` — copied from the visitor row inside
    the same atomic INSERT that creates the identity; gates emailability.

Additive only. Every column is NOT NULL with server_default 'false', matching the
existing ``events.optout`` / ``visitors.do_not_resolve`` / ``visitors.
is_agent_derived`` shape, so it cannot fail on existing rows and no backfill is
needed. No existing column is altered or dropped.

down_revision re-verified live at EXECUTE time via
``alembic -c apps/api/alembic.ini heads`` as a9f2c1e7b4d6 (single head at the
moment this file was written). Unrelated ad-connection migrations subsequently
chained ON TOP of this revision (c7d3b8e1f624 -> b7d3e9f1a4c2 -> c8e4f2a6b1d9),
so the chain remains linear with a single head — no branch was introduced.

Docker-gated: this migration is NEVER applied to a real environment as part of
EXECUTE. Round-trip (upgrade head -> downgrade -1 -> upgrade head) is proven on a
disposable Postgres container only, matching the owned-data-layer /
first-party-capture / evallayer convention.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d3b8e1f624"
down_revision: Union[str, None] = "a9f2c1e7b4d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "is_flagged_abuse",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_events_site_flagged", "events", ["site_id", "is_flagged_abuse"]
    )
    op.add_column(
        "visitors",
        sa.Column(
            "is_abuse_flagged",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "identified_visitors",
        sa.Column(
            "is_abuse_flagged",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("identified_visitors", "is_abuse_flagged")
    op.drop_column("visitors", "is_abuse_flagged")
    op.drop_index("ix_events_site_flagged", table_name="events")
    op.drop_column("events", "is_flagged_abuse")
