"""add crm_connections table (outbound CRM connectors)

Revision ID: d9f2b6e4c8a1
Revises: c5d8e1f3a7b9
Create Date: 2026-06-29

Phase 2 of the Connectors tab. One row per (site, provider) holding an outbound
CRM connection: OAuth tokens (HubSpot/Pipedrive/Salesforce) encrypted via
services/encryption.py, or a signed webhook URL + secret (generic_webhook)
encrypted via services/key_vault.py. Lets a site push identified visitors
straight into its CRM instead of CSV round-trips.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d9f2b6e4c8a1"
down_revision: Union[str, None] = "c5d8e1f3a7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crm_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", sa.String(length=50), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("auth_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("direction", sa.String(length=10), nullable=False, server_default="out"),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("external_account_id", sa.String(length=255), nullable=True),
        sa.Column("external_account_label", sa.String(length=255), nullable=True),
        sa.Column("webhook_url", sa.Text(), nullable=True),
        sa.Column("encrypted_secret", sa.Text(), nullable=True),
        sa.Column("secret_hint", sa.String(length=20), nullable=True),
        sa.Column("field_mapping", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("last_pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("is_valid", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crm_connections_site_id", "crm_connections", ["site_id"])
    op.create_index(
        "uq_crm_site_provider",
        "crm_connections",
        ["site_id", "provider"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_crm_site_provider", table_name="crm_connections")
    op.drop_index("ix_crm_connections_site_id", table_name="crm_connections")
    op.drop_table("crm_connections")
