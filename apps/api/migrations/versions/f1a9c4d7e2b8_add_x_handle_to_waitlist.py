"""add x_handle to waitlist_signups

Revision ID: f1a9c4d7e2b8
Revises: b7e1a2c9d4f0
Create Date: 2026-06-14

Adds the optional X (Twitter) handle captured at waitlist signup. Powers the
public Founders Wall. Nullable — existing rows backfill as NULL and only opt-in
signups (those who entered a handle) ever appear on the wall.

Chains off the committed head (b7e1a2c9d4f0). The in-progress privacy/PII
migrations in the working tree have branched into separate heads; resolve those
with a merge revision before deploying them alongside this one.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f1a9c4d7e2b8"
down_revision: Union[str, None] = "b7e1a2c9d4f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "waitlist_signups",
        sa.Column("x_handle", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("waitlist_signups", "x_handle")
