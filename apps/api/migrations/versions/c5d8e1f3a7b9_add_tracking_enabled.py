"""add tracking_enabled to sites

Revision ID: c5d8e1f3a7b9
Revises: a1c7f2e9b4d6
Create Date: 2026-06-28

Adds the per-site tracking pause toggle. Defaults to true so existing rows are
backfilled without a NULL (the column is NOT NULL) and existing sites keep
collecting events. When set to false the ingest endpoint silently drops events
for the site (offboarding "pause" — the pixel stays installed, plan/data are
untouched).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c5d8e1f3a7b9"
down_revision: Union[str, None] = "a1c7f2e9b4d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sites",
        sa.Column(
            "tracking_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("sites", "tracking_enabled")
