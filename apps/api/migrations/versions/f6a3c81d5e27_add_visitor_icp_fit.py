"""add visitor icp_fit

Additive-nullable only: one new nullable ``icp_fit`` Float column on
``visitors``, holding a deterministic 0-100 fit score against the site's
REVIEWED ``sites.site_profile`` ICP. No backfill, no server default, no
constraint, no index.

NULL = not scored (flag off, no reviewed ``site_profile``, or fewer than two
scorable dimensions). NULL is deliberately NOT 0 — 0 would read as "scored and
a poor fit", a different claim.

Mirrors ``visitors.intent_score``: sole writer is the full-recompute branch of
``aggregate_visitors_for_site`` (``since=None``).

Revision ID: f6a3c81d5e27
Revises: e4b1d78c3a05
Create Date: 2026-08-17

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f6a3c81d5e27"
down_revision = "e4b1d78c3a05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("visitors", sa.Column("icp_fit", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("visitors", "icp_fit")
