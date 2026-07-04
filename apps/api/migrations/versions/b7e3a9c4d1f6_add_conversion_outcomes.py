"""add conversion outcomes tables

Revision ID: b7e3a9c4d1f6
Revises: a9d4e7f2c1b8
Create Date: 2026-07-04

Conversion attribution foundation ("Beam drove N conversions"):

- conversion_goals: per-site definitions of what counts as a conversion
  (URL match at launch; js_event/webhook sources in a later phase).
- campaign_clicks: durable touchpoint ↔ landing-visitor link recorded when a
  ``_tp``-decorated campaign link lands on the pixel — the piece that makes
  cross-device attribution possible (the emailed visitor_id and the landing
  browser's visitor_id often differ).
- conversions: recorded conversions with last-click attribution snapshot.
  Own table (not events) so outcome history survives raw-event retention.
- idx_campaign_touchpoints_visitor: same-browser attribution fallback looks
  up touchpoints by visitor_id (only campaign_id was indexed before).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b7e3a9c4d1f6"
down_revision: Union[str, None] = "a9d4e7f2c1b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversion_goals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("goal_type", sa.String(length=20), nullable=False, server_default="url_match"),
        sa.Column("match_type", sa.String(length=20), nullable=False, server_default="contains"),
        sa.Column("pattern", sa.String(length=500), nullable=False),
        sa.Column("value_cents", sa.Integer(), nullable=True),
        sa.Column("repeatable", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "name", name="uq_conversion_goals_site_name"),
    )
    op.create_index(
        "idx_conversion_goals_site_enabled", "conversion_goals", ["site_id", "enabled"]
    )

    op.create_table(
        "campaign_clicks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("touchpoint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", sa.String(length=50), nullable=False),
        sa.Column("visitor_id", sa.String(length=100), nullable=False),
        sa.Column("clicked_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["touchpoint_id"], ["campaign_touchpoints.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("touchpoint_id", "visitor_id", name="uq_campaign_clicks_tp_visitor"),
    )
    op.create_index(
        "idx_campaign_clicks_site_visitor_time",
        "campaign_clicks",
        ["site_id", "visitor_id", "clicked_at"],
    )
    op.create_index("idx_campaign_clicks_campaign", "campaign_clicks", ["campaign_id"])

    op.create_table(
        "conversions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", sa.String(length=50), nullable=False),
        sa.Column("goal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visitor_id", sa.String(length=100), nullable=False),
        sa.Column("touchpoint_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel", sa.String(length=50), nullable=True),
        sa.Column("attribution", sa.String(length=20), nullable=False, server_default="organic"),
        sa.Column("matched_by", sa.String(length=20), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="url_match"),
        sa.Column("value_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("url", sa.Text(), nullable=False, server_default=""),
        sa.Column("dedupe_key", sa.String(length=250), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["goal_id"], ["conversion_goals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["touchpoint_id"], ["campaign_touchpoints.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("dedupe_key", name="uq_conversions_dedupe_key"),
    )
    op.create_index("idx_conversions_site_time", "conversions", ["site_id", "occurred_at"])
    op.create_index("idx_conversions_goal", "conversions", ["goal_id"])
    op.create_index("idx_conversions_campaign", "conversions", ["campaign_id"])
    op.create_index("idx_conversions_site_visitor", "conversions", ["site_id", "visitor_id"])

    op.create_index(
        "idx_campaign_touchpoints_visitor", "campaign_touchpoints", ["visitor_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_campaign_touchpoints_visitor", table_name="campaign_touchpoints")
    op.drop_index("idx_conversions_site_visitor", table_name="conversions")
    op.drop_index("idx_conversions_campaign", table_name="conversions")
    op.drop_index("idx_conversions_goal", table_name="conversions")
    op.drop_index("idx_conversions_site_time", table_name="conversions")
    op.drop_table("conversions")
    op.drop_index("idx_campaign_clicks_campaign", table_name="campaign_clicks")
    op.drop_index("idx_campaign_clicks_site_visitor_time", table_name="campaign_clicks")
    op.drop_table("campaign_clicks")
    op.drop_index("idx_conversion_goals_site_enabled", table_name="conversion_goals")
    op.drop_table("conversion_goals")
