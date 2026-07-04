"""add sites.last_outcome_digest_sent_at

Revision ID: d8f1c5a3b9e7
Revises: c4f8b2d6a9e1
Create Date: 2026-07-04

Throttle stamp for the weekly outcomes digest email (outcomes P4). NULL =
never sent; the digest job skips sites stamped within the last 6 days so
overlapping triggers can't double-send. Purely additive.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d8f1c5a3b9e7"
down_revision: Union[str, None] = "c4f8b2d6a9e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sites",
        sa.Column("last_outcome_digest_sent_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sites", "last_outcome_digest_sent_at")
