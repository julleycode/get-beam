"""add ad_performance_daily + content_opportunities (ad-insights-seo-aeo)

Additive only. Dormant until AD_INSIGHTS_ENABLED is True.

Revision ID: b3e9c4d71a58
Revises: a2d6e8f41c93
Create Date: 2026-11-27

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b3e9c4d71a58"
down_revision = "a2d6e8f41c93"
branch_labels = None
depends_on = None


def _base_cols() -> list:
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "ad_performance_daily",
        *_base_cols(),
        sa.Column("site_id", sa.String(50), nullable=False),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ad_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("platform_ad_id", sa.String(100), nullable=False),
        sa.Column("campaign_name", sa.String(500), nullable=True),
        sa.Column("headline", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("landing_url", sa.Text(), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("impressions", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("conversions", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.UniqueConstraint("connection_id", "platform_ad_id", "date", name="uq_ad_perf_conn_ad_date"),
    )
    op.create_index("ix_ad_performance_daily_site_id", "ad_performance_daily", ["site_id"])
    op.create_index("idx_ad_perf_site_date", "ad_performance_daily", ["site_id", "date"])

    op.create_table(
        "content_opportunities",
        *_base_cols(),
        sa.Column("site_id", sa.String(50), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("source_ad_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("signals", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column("generated_on", sa.Date(), nullable=False),
        sa.CheckConstraint("kind IN ('page_title', 'faq', 'llms_txt')", name="ck_content_opp_kind"),
        sa.CheckConstraint("status IN ('new', 'dismissed', 'copied')", name="ck_content_opp_status"),
    )
    op.create_index("ix_content_opportunities_site_id", "content_opportunities", ["site_id"])
    op.create_index("idx_content_opp_site_status", "content_opportunities", ["site_id", "status"])


def downgrade() -> None:
    op.drop_index("idx_content_opp_site_status", table_name="content_opportunities")
    op.drop_index("ix_content_opportunities_site_id", table_name="content_opportunities")
    op.drop_table("content_opportunities")
    op.drop_index("idx_ad_perf_site_date", table_name="ad_performance_daily")
    op.drop_index("ix_ad_performance_daily_site_id", table_name="ad_performance_daily")
    op.drop_table("ad_performance_daily")
