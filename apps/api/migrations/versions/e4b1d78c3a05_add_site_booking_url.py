"""add site booking_url

Additive-nullable only: one new nullable ``booking_url`` column on ``sites``,
holding the owner's demo/meeting booking link (Calendly, Cal.com, or a page on
their own site). No backfill, no server default, no constraint, no index.

Rendered into campaign drafts through the ``{{booking_link}}`` token. NULL =
not configured, in which case the token resolves to an empty string.

Revision ID: e4b1d78c3a05
Revises: d7e2b4c81f93
Create Date: 2026-08-16

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e4b1d78c3a05"
down_revision = "d7e2b4c81f93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sites", sa.Column("booking_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("sites", "booking_url")
