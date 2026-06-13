"""add auto_identify_enabled to sites

Revision ID: b7e1a2c9d4f0
Revises: cd811a8b1f32
Create Date: 2026-06-13

Adds the per-site auto-identify toggle. Defaults to false so existing rows are
backfilled without a NULL (the column is NOT NULL) and existing sites stop the
automatic resolution sweep until the owner opts in.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b7e1a2c9d4f0"
down_revision: Union[str, None] = "cd811a8b1f32"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sites",
        sa.Column(
            "auto_identify_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("sites", "auto_identify_enabled")
