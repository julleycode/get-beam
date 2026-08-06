"""add job_change_events table

Revision ID: a4f2b8c15d70
Revises: f1a7c3e05b92
Create Date: 2026-08-07

Job-change detection v1 (same-tenant). Purely additive, non-destructive.

NEW ``job_change_events`` table — one row per CONFIRMED job change for an
identified visitor, recorded as a minimal before/after pair. NO PII: no email
column, no name column; the person is referenced by the (site_id, visitor_id)
string pair only (SPEC AC-14). Same-tenant only — never joined with
beam_identity_graph (SPEC AC-11).

No FK constraints (string-pair convention shared with enrichment_profiles /
identity_signals / company_graph), so erasure is explicit: the table is listed
in visitors.delete_visitor_data's DELETE-loop tuple (SPEC AC-12).

The (site_id, visitor_id) index is intentionally NOT unique — a visitor may
change jobs more than once.

Chained after f1a7c3e05b92 (add_fingerprint_v3), confirmed as the single live
head via `alembic -c apps/api/alembic.ini heads` on 07-08-26. Docker-gated:
offline `--sql` validated only, never applied against a live Postgres in the
build sandbox.

See:
process/features/visitors-identity/active/job-change-detection_07-08-26/job-change-detection_PLAN_07-08-26.md
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a4f2b8c15d70"
down_revision: Union[str, None] = "f1a7c3e05b92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_change_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("site_id", sa.String(50), nullable=False),
        sa.Column("visitor_id", sa.String(100), nullable=False),
        sa.Column("prior_company", sa.String(200), nullable=True),
        sa.Column("new_company", sa.String(200), nullable=True),
        sa.Column("prior_job_title", sa.String(200), nullable=True),
        sa.Column("new_job_title", sa.String(200), nullable=True),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("corroboration_signal", sa.String(100), nullable=True),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_job_change_site_visitor", "job_change_events", ["site_id", "visitor_id"]
    )
    op.create_index(
        "idx_job_change_site_detected", "job_change_events", ["site_id", "detected_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_job_change_site_detected", table_name="job_change_events")
    op.drop_index("idx_job_change_site_visitor", table_name="job_change_events")
    op.drop_table("job_change_events")
