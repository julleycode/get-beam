"""add identity_feedback.actual_city

Ground truth for the onboarding location reveal: when a user ticks "wrong city"
the form now asks which city they are actually in, and the answer lands here.

Purely additive — one nullable column, no backfill, no index. Existing rows keep
NULL, which reads correctly as "reported before we started asking".

Revision ID: b7e3c9a4f215
Revises: f4b9d2a71c68
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "b7e3c9a4f215"
down_revision = "f4b9d2a71c68"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "identity_feedback",
        sa.Column("actual_city", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("identity_feedback", "actual_city")
