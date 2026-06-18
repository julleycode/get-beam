"""add focus_keyword to blog_posts

Revision ID: a4d1f0b9c3e2
Revises: f7c2e9a4b1d3
Create Date: 2026-06-18

The blog editor's "Focus keyword" field (the phrase a post should rank for, and
the driver of the live SEO checklist) was author-time only and never persisted.
Add a nullable column so it round-trips back into the editor on reopen.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a4d1f0b9c3e2"
down_revision: Union[str, None] = "f7c2e9a4b1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "blog_posts",
        sa.Column("focus_keyword", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("blog_posts", "focus_keyword")
