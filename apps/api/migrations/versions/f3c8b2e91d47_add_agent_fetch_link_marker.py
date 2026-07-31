"""add link_marker to agent_fetch_events

Stores the per-fetch token the Cloudflare Pages edge stamps onto every same-host
link in the HTML it serves to an on-demand AI fetcher. A human who later clicks
one of those links arrives with it in the landing URL, which the pixel already
reports into ``events.url`` -- so this column is the other half of a join that
names the exact agent fetch behind a click, replacing the vendor+page+30-minute
guess in ``agent_handoff_correlation``.

Additive and reversible: one nullable column plus one PARTIAL index. No backfill
(pre-existing rows legitimately have no marker), no constraint, no data rewrite,
so the upgrade does not lock the table for any meaningful time.

Revision ID: f3c8b2e91d47
Revises: c1e7a94f3d28
Create Date: 2026-07-31

"""
from alembic import op
import sqlalchemy as sa

revision = "f3c8b2e91d47"
down_revision = "c1e7a94f3d28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_fetch_events",
        sa.Column("link_marker", sa.String(length=32), nullable=True),
    )
    # PARTIAL: only marked rows are indexed. Most agent fetches carry no marker
    # (every non-edge write path, and every row written before this revision),
    # and indexing their NULLs would tax the ingest write path for no read.
    #
    # NOT unique -- the edge mints markers with no coordination, so uniqueness is
    # something to observe in the data, not to enforce at write time. Enforcing
    # it would turn an unlikely collision into a lost agent visit, which is a
    # strictly worse failure than two candidate rows to disambiguate.
    op.create_index(
        "idx_agent_fetch_events_link_marker",
        "agent_fetch_events",
        ["link_marker"],
        unique=False,
        postgresql_where=sa.text("link_marker IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_agent_fetch_events_link_marker",
        table_name="agent_fetch_events",
    )
    op.drop_column("agent_fetch_events", "link_marker")
