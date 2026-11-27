"""add site_exclusions (company/domain exclusion list)

Additive only: one new table. ``site_id`` is a real FK onto ``sites.site_id``
with ON DELETE CASCADE so deleting a site removes its exclusions. Dormant until
COMPANY_EXCLUSION_ENABLED is flipped on.

Chained on d3f8a2c61b47, observed via ``alembic heads`` (pinned local DSN)
immediately before this file was written.

Revision ID: e8c4b2a7d913
Revises: d3f8a2c61b47
Create Date: 2026-11-27

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e8c4b2a7d913"
down_revision = "d3f8a2c61b47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_exclusions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("site_id", sa.String(length=50), nullable=False),
        sa.Column("domain", sa.String(length=253), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=True),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["sites.site_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_site_exclusions_site_id", "site_exclusions", ["site_id"])
    op.create_index(
        "uq_site_exclusions_site_domain", "site_exclusions", ["site_id", "domain"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_site_exclusions_site_domain", table_name="site_exclusions")
    op.drop_index("ix_site_exclusions_site_id", table_name="site_exclusions")
    op.drop_table("site_exclusions")
