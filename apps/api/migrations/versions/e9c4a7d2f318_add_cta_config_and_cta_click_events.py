"""add sites.cta_config + cta_click_events

Additive only: one nullable JSONB column on ``sites`` and one new append-only
table ``cta_click_events`` (no PII). Chained off the live head at EXECUTE time.

Revision ID: e9c4a7d2f318
Revises: d3f8a2c61b47
Create Date: 2026-11-27

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e9c4a7d2f318"
down_revision = "d3f8a2c61b47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sites",
        sa.Column("cta_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_table(
        "cta_click_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "site_id",
            sa.String(length=50),
            sa.ForeignKey("sites.site_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cta_type", sa.String(length=30), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index(
        "idx_cta_click_events_site_type", "cta_click_events", ["site_id", "cta_type"]
    )


def downgrade() -> None:
    op.drop_index("idx_cta_click_events_site_type", table_name="cta_click_events")
    op.drop_table("cta_click_events")
    op.drop_column("sites", "cta_config")
