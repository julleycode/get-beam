"""add site analysis profile columns to sites

Five additive nullable columns backing the onboarding site-analysis feature
(flag ``site_analysis_enabled``, default OFF). Two-slot storage (plan D4/V1):

* ``site_profile``           — the CONFIRMED profile. ONLY ``PUT /sites/{id}/analysis``
                               ever writes it; the background analysis task never does.
* ``site_profile_candidate`` — the un-reviewed output of the latest analysis run,
                               awaiting the owner's confirm. Written ONLY by the task,
                               NULLed by ``PUT`` (promote or dismiss).
* ``site_profile_status``    — "pending" | "ready" | "failed"; NULL = never analyzed
                               ("none"). FAILED is also DERIVED at read time from a
                               stale ``pending`` (plan D2), so this column is not the
                               whole truth on its own.
* ``site_profile_started_at``  — naive UTC stamp of when the current run began; the
                                 input to the stale-pending derivation.
* ``site_profile_analyzed_at`` — naive UTC completion time of the run that produced
                                 the candidate. Single writer: the task. ``PUT`` never
                                 stamps it.

All five are additive + nullable, so every existing row reads correctly as
"never analyzed" and flag-OFF behavior is byte-identical. No index on either JSONB
column — neither is ever queried by content.

Revision ID: c5e1a9b73d20
Revises: b7e3c9a4f215
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c5e1a9b73d20"
down_revision = "b7e3c9a4f215"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sites",
        sa.Column("site_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "sites",
        sa.Column(
            "site_profile_candidate",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "sites", sa.Column("site_profile_status", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "sites", sa.Column("site_profile_started_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "sites", sa.Column("site_profile_analyzed_at", sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("sites", "site_profile_analyzed_at")
    op.drop_column("sites", "site_profile_started_at")
    op.drop_column("sites", "site_profile_status")
    op.drop_column("sites", "site_profile_candidate")
    op.drop_column("sites", "site_profile")
