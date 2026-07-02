"""add avatar_url to enrichment_profiles

Revision ID: e5f1a8c3d2b7
Revises: d4c7b2a9e6f1
Create Date: 2026-07-02

Adds a nullable social avatar URL (Twitter/X primary, OSINT secondary).
Display-only; nullable so existing rows are untouched (no backfill).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e5f1a8c3d2b7"
down_revision: Union[str, None] = "d4c7b2a9e6f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "enrichment_profiles",
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("enrichment_profiles", "avatar_url")
