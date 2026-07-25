"""add ad_connections table

Revision ID: b7d3e9f1a4c2
Revises: c7d3b8e1f624
Create Date: 2026-07-25

Ad Audiences — Phase 1 (Foundation). Purely additive: creates the
``ad_connections`` table, the ad-platform mirror of ``crm_connections``
(same OAuth token storage shape) plus ``ad_account_id`` / ``business_id``.

No existing table is touched. Guarded at runtime by the
``ad_audiences_enabled`` feature flag (default OFF), so applying this
migration alone changes no behavior.

down_revision re-verified live at EXECUTE time via
``alembic -c apps/api/alembic.ini heads``. A concurrent migration
(c7d3b8e1f624, add_ingest_abuse_flag) landed on a9f2c1e7b4d6 during this
EXECUTE session, so this revision is re-chained onto c7d3b8e1f624 rather than
force-merging two heads — per the phase plan's Blockers contingency.

See: process/features/ads-audiences/active/ad-audiences_25-07-26/
     phase-1-foundation_PLAN_25-07-26.md
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7d3e9f1a4c2"
down_revision: Union[str, None] = "c7d3b8e1f624"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ad_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("site_id", sa.String(50), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("auth_type", sa.String(20), nullable=False, server_default="oauth"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("access_token", sa.Text, nullable=True),
        sa.Column("refresh_token", sa.Text, nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", postgresql.ARRAY(sa.String), nullable=True),
        sa.Column("external_account_id", sa.String(255), nullable=True),
        sa.Column("external_account_label", sa.String(255), nullable=True),
        sa.Column("ad_account_id", sa.String(255), nullable=True),
        sa.Column("business_id", sa.String(255), nullable=True),
        sa.Column("last_pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("is_valid", sa.Boolean, nullable=True, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("site_id", "provider", name="uq_ad_site_provider"),
    )
    op.create_index("ix_ad_connections_site_id", "ad_connections", ["site_id"])


def downgrade() -> None:
    op.drop_index("ix_ad_connections_site_id", table_name="ad_connections")
    op.drop_table("ad_connections")
