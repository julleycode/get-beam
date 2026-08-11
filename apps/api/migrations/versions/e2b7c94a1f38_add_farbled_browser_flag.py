"""add events.farbled + visitors.has_unstable_fingerprint (WS2 farbled-browser detection)

Privacy-browser plan (10-08-26), WS2. Additive-only, NON-DESTRUCTIVE: two boolean
columns, no backfill, no constraint on existing data, no index on either.

METADATA-ONLY ON POSTGRESQL 11+. `ADD COLUMN ... NOT NULL DEFAULT false` stores
the default in the catalog instead of rewriting every row, so neither statement
takes a long lock. This matters here specifically because `events` is the largest
table in the schema — the same reasoning recorded in b8e3f6a2c904 and
c7d3b8e1f624.

No index on `events.farbled`: it is never a query predicate, only a BOOL_OR
rollup input inside the existing per-visitor aggregation. An index would add
write cost on the hottest path in the API to serve no read.

`visitors.has_unstable_fingerprint` is named for the OBSERVED PROPERTY, never a
vendor — Brave, Firefox resist_fingerprinting, Tor and CanvasBlocker all produce
identical behavior, so an `is_brave` column would be a lie within a quarter.

NO BACKFILL IS POSSIBLE. Both columns are false for every existing row; a
rotating fingerprint cannot be recognised retroactively from stored data.

Nothing in this migration, or the code that reads these columns, touches
is_abuse_flagged, do_not_resolve, agent_visits, or outreach eligibility. In
particular do_not_resolve (the GPC privacy flag) is never written by this
feature — conflating "your browser randomizes canvas" with "you invoked GPC"
would be factually wrong and irreversible.

OFFLINE-VALIDATED ONLY (repo convention): this revision joins the queue of
migrations pending live-apply. Live-apply is a separate explicit operator
action, and `.env` points at PRODUCTION Supabase while migrations/env.py has no
local-host guard — always pin DATABASE_URL to localhost:5433 first.

Chained on a1c7f4e082d5 (add_onboarding_canary_support), re-derived live via
`alembic -c apps/api/alembic.ini heads` on 10-08-26 immediately before this file
was written (single head, no branching). CAVEAT recorded at EXECUTE time: that
head file is currently UNTRACKED in the worktree (concurrent session's work). It
was still the correct chain target — picking the last COMMITTED revision instead
would have created a second head.

Revision ID: e2b7c94a1f38
Revises: a1c7f4e082d5
Create Date: 2026-08-10
"""

from alembic import op
import sqlalchemy as sa

revision = "e2b7c94a1f38"
down_revision = "a1c7f4e082d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("farbled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "visitors",
        sa.Column(
            "has_unstable_fingerprint",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("visitors", "has_unstable_fingerprint")
    op.drop_column("events", "farbled")
