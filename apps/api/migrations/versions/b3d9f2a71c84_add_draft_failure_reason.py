"""add failure_reason to drafts

Revision ID: b3d9f2a71c84
Revises: f2b8d4c1a9e5
Create Date: 2026-07-03

Adds a nullable plain-language reason a draft send failed, so the failed-draft
card can explain WHY and offer the right fix (Reconnect vs Retry). Nullable so
existing rows are untouched (no backfill).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b3d9f2a71c84"
down_revision: Union[str, None] = "f2b8d4c1a9e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "drafts",
        sa.Column("failure_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("drafts", "failure_reason")
