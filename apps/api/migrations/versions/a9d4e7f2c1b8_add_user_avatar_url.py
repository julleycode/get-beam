"""add users.avatar_url (Clerk profile image for the founders wall)

Revision ID: a9d4e7f2c1b8
Revises: f3d9b1c7a2e4
Create Date: 2026-07-04

Stores the Clerk-hosted profile image URL (img.clerk.com) captured at JIT user
creation, only when Clerk reports has_image=true (their gray fallback avatar is
skipped so the wall's initials tiles stay prettier). Purely additive; existing
rows are backfilled by scripts/backfill_clerk_avatars.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a9d4e7f2c1b8"
down_revision: Union[str, None] = "f3d9b1c7a2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("avatar_url", sa.String(length=1000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "avatar_url")
