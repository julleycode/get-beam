"""add events.agent_sig (WS2 agent-session activation)

WS2 agent-session activation plan (pixel, 07-08-26), Step 3. Additive-only,
NON-DESTRUCTIVE: one nullable JSONB column, no backfill, no constraint on
existing data. Every row written before this revision stays NULL, and the batch
sweep that reads it fails safe (flags nobody) on NULL.

JSONB, not JSON: every existing JSON-shaped column in this schema
(agent_profile, agent_visit, api_usage, campaign, crm_connection, enrichment,
request_log) uses JSONB. Contents are whitelisted and bounded by the Pydantic
validator in apps/api/schemas/events.py before they ever reach this column —
/ingest is public and unauthenticated, so the raw client object is never stored.

VISIBILITY-ONLY. Nothing in this migration, or the code that reads this column,
touches is_abuse_flagged, do_not_resolve, agent_visits, or outreach eligibility.

OFFLINE-VALIDATED ONLY (repo convention): this revision joins the queue of
migrations already pending live-apply. Never `alembic upgrade` against a real
environment as part of this plan — live-apply is a separate explicit operator
action. Offline `--sql` dry-runs in this repo need an EXPLICIT <from>:<to> rev
range (the `upgrade head --sql` shorthand fails mid-chain on b7d3e9f1a4c2's
sa.inspect call).

Chained on a4f2b8c15d70, confirmed live via
`alembic -c apps/api/alembic.ini heads` on 07-08-26 immediately before this file
was written (single head, no branching). The plan's own cited head
(f1a7c3e05b92) was already stale by EXECUTE time — a concurrent session had
landed add_job_change_events on top of it.

Revision ID: b8e3f6a2c904
Revises: a4f2b8c15d70
Create Date: 2026-08-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8e3f6a2c904"
down_revision: Union[str, None] = "a4f2b8c15d70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("agent_sig", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("events", "agent_sig")
