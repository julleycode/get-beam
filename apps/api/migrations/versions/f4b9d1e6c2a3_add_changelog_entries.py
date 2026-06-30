"""add changelog_entries table

Revision ID: f4b9d1e6c2a3
Revises: cb697a56c928
Create Date: 2026-06-30

Backs the "what's new" pill on the getbeam.fyi landing page. Short product
updates, published from the dashboard and read publicly by the static landing
page. Simpler than blog_posts — no slug/markdown/SEO.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f4b9d1e6c2a3"
down_revision: Union[str, None] = "cb697a56c928"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "changelog_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_changelog_entries_status", "changelog_entries", ["status"]
    )
    op.create_index(
        "ix_changelog_entries_published_at", "changelog_entries", ["published_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_changelog_entries_published_at", table_name="changelog_entries")
    op.drop_index("ix_changelog_entries_status", table_name="changelog_entries")
    op.drop_table("changelog_entries")
