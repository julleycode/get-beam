"""add source_ref to changelog_entries (GitHub auto-sync idempotency)

Revision ID: a7c3e9f1b6d2
Revises: f4b9d1e6c2a3
Create Date: 2026-06-30

The GitHub→Gemini auto-generator stamps each entry with the PR it came from
(e.g. "pr-62"). A unique index makes re-running the sync idempotent — a PR that
was already turned into an entry is skipped. Manual entries leave it NULL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a7c3e9f1b6d2"
down_revision: Union[str, None] = "f4b9d1e6c2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "changelog_entries",
        sa.Column("source_ref", sa.String(length=50), nullable=True),
    )
    op.create_index(
        "uq_changelog_source_ref",
        "changelog_entries",
        ["source_ref"],
        unique=True,
        postgresql_where=sa.text("source_ref IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_changelog_source_ref", table_name="changelog_entries")
    op.drop_column("changelog_entries", "source_ref")
