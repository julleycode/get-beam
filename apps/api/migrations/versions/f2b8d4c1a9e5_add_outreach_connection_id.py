"""add outreach_connection_id to social_accounts

Revision ID: f2b8d4c1a9e5
Revises: e5f1a8c3d2b7
Create Date: 2026-07-03

Adds a nullable opaque reference to a LinkedIn session registered in the
phantommm sidecar (LinkedIn outreach automation). Beam never stores the raw
LinkedIn cookie — this only holds the id phantommm returns. Nullable so existing
rows are untouched (no backfill).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f2b8d4c1a9e5"
down_revision: Union[str, None] = "e5f1a8c3d2b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "social_accounts",
        sa.Column("outreach_connection_id", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("social_accounts", "outreach_connection_id")
