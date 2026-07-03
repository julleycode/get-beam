"""add last_expiry_alert_sent_at to social_accounts

Revision ID: d8a3c6b2f915
Revises: c7e1a4b9d3f2
Create Date: 2026-07-03

Throttle column for the connection-expiry nudge job: records when the account
owner was last emailed about a token expiring, so they aren't nudged more than
once per window. Nullable so existing rows are untouched (no backfill).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d8a3c6b2f915"
down_revision: Union[str, None] = "c7e1a4b9d3f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "social_accounts",
        sa.Column("last_expiry_alert_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("social_accounts", "last_expiry_alert_sent_at")
