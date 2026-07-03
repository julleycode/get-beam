"""add post_ready to social_accounts

Revision ID: e2f5b8c1d094
Revises: d8a3c6b2f915
Create Date: 2026-07-03

Whether an account can actually post, probed at connect time (e.g. X's
x-access-level header). Nullable: True = ready, False = needs write access,
NULL = unknown / not probed. No backfill (existing rows stay unknown).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e2f5b8c1d094"
down_revision: Union[str, None] = "d8a3c6b2f915"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "social_accounts",
        sa.Column("post_ready", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("social_accounts", "post_ready")
