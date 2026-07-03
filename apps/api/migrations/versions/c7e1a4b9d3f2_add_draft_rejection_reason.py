"""add rejection_reason to drafts

Revision ID: c7e1a4b9d3f2
Revises: b3d9f2a71c84
Create Date: 2026-07-03

Distinguishes a user-rejected draft ("user_rejected") from a sibling that was
auto-rejected because another draft for the same post was approved
("auto_rejected_sibling"), so the UI can relabel the latter as "Not used".
Nullable so existing rows are untouched (no backfill).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c7e1a4b9d3f2"
down_revision: Union[str, None] = "b3d9f2a71c84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "drafts",
        sa.Column("rejection_reason", sa.String(length=30), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("drafts", "rejection_reason")
