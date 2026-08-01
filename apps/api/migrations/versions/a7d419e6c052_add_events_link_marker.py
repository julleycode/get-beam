"""add link_marker to events

Denormalises the edge-minted ``?_bfm=`` marker out of ``events.url`` into its own
indexed column. Without it, tying a human click back to the agent fetch that
produced it means ``events.url LIKE '%_bfm=' || ... || '%'`` — a sequential scan
of the largest table in the schema, on a join that is meant to run per dashboard
view.

Additive and reversible: one nullable column plus one PARTIAL index, no
constraint, no data rewrite.

DELIBERATELY NOT BACKFILLED. Existing rows keep NULL even where their ``url``
contains a marker: those markers predate ``agent_fetch_events.link_marker``, so
there is nothing on the other side of the join to match them to, and an UPDATE
over the whole events table would be by far the most expensive statement in this
migration for zero joinable rows.

Revision ID: a7d419e6c052
Revises: f3c8b2e91d47
Create Date: 2026-07-31

"""
from alembic import op
import sqlalchemy as sa

revision = "a7d419e6c052"
down_revision = "f3c8b2e91d47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("link_marker", sa.String(length=32), nullable=True),
    )
    # PARTIAL: this table absorbs every pageview/scroll/time_on_page on every
    # site, and almost none of those rows carry a marker. Indexing their NULLs
    # would tax the hottest write path in the API for rows that can never
    # satisfy the join this index exists to serve.
    op.create_index(
        "ix_events_link_marker",
        "events",
        ["link_marker"],
        unique=False,
        postgresql_where=sa.text("link_marker IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_events_link_marker", table_name="events")
    op.drop_column("events", "link_marker")
