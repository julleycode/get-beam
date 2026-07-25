"""add ad_audience_links table

Revision ID: c8e4f2a6b1d9
Revises: b7d3e9f1a4c2
Create Date: 2026-07-25

Ad Audiences — Phase 1 (Foundation). Purely additive: creates
``ad_audience_links``, one row per (connection_id, segment_id). The unique
constraint ``uq_ad_audience_link`` is the update-not-duplicate mechanism —
repeat pushes reuse the stored ``platform_audience_id`` via an
``ON CONFLICT (connection_id, segment_id) DO UPDATE`` upsert rather than
creating a second platform-side audience.

Chained after b7d3e9f1a4c2 (ad_connections), which owns the FK target.

See: process/features/ads-audiences/active/ad-audiences_25-07-26/
     phase-1-foundation_PLAN_25-07-26.md
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c8e4f2a6b1d9"
down_revision: Union[str, None] = "b7d3e9f1a4c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ad_audience_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("segment_id", sa.String(50), nullable=False),
        sa.Column("platform_audience_id", sa.String(255), nullable=False),
        sa.Column("last_pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_push_count", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["ad_connections.id"],
            name="fk_ad_audience_links_connection_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("connection_id", "segment_id", name="uq_ad_audience_link"),
    )
    op.create_index(
        "ix_ad_audience_links_connection_id", "ad_audience_links", ["connection_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_ad_audience_links_connection_id", table_name="ad_audience_links")
    op.drop_table("ad_audience_links")
