"""add ad conversion outbox + config tables, visitors.click_ids

Additive only (conversion-apis_27-11-26). Two new tables and one nullable
JSONB column. Dormant until AD_CONVERSIONS_ENABLED is flipped on.

Revision ID: e5c2a9f71d36
Revises: d3f8a2c61b47
Create Date: 2026-11-27

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e5c2a9f71d36"
down_revision = "d3f8a2c61b47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("visitors", sa.Column("click_ids", postgresql.JSONB(), nullable=True))

    op.create_table(
        "ad_conversion_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "site_id",
            sa.String(length=50),
            sa.ForeignKey("sites.site_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("visitor_id", sa.String(length=100), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("conversion_type", sa.String(length=20), nullable=False),
        sa.Column("goal_id", sa.String(length=64), nullable=True),
        sa.Column("dedup_id", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint("site_id", "platform", "dedup_id", name="uq_ad_conv_delivery_dedup"),
    )
    op.create_index(
        "idx_ad_conv_delivery_due", "ad_conversion_deliveries", ["status", "next_attempt_at"]
    )
    op.create_index(
        "idx_ad_conv_delivery_site_visitor", "ad_conversion_deliveries", ["site_id", "visitor_id"]
    )

    op.create_table(
        "ad_conversion_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "site_id",
            sa.String(length=50),
            sa.ForeignKey("sites.site_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("goal_event_map", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("meta_dataset_id", sa.String(length=64), nullable=True),
        sa.Column("meta_test_event_code", sa.String(length=64), nullable=True),
        sa.Column("google_operating_account_id", sa.String(length=64), nullable=True),
        sa.Column("google_product_destination_id", sa.String(length=64), nullable=True),
        sa.Column("validate_only", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("eea_consent_attested", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("goal_watermark_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lead_watermark_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint("site_id", "platform", name="uq_ad_conv_config_site_platform"),
    )


def downgrade() -> None:
    op.drop_table("ad_conversion_configs")
    op.drop_index("idx_ad_conv_delivery_site_visitor", table_name="ad_conversion_deliveries")
    op.drop_index("idx_ad_conv_delivery_due", table_name="ad_conversion_deliveries")
    op.drop_table("ad_conversion_deliveries")
    op.drop_column("visitors", "click_ids")
