"""add crm_closed_won_contacts (closed-won lookalike seed)

Additive only (closed-won-lookalikes_27-11-26). One new table. Dormant until
CLOSED_WON_LOOKALIKES_ENABLED is flipped on.

Revision ID: f7d1b3c84e29
Revises: e5c2a9f71d36
Create Date: 2026-11-27

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f7d1b3c84e29"
down_revision = "e5c2a9f71d36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_closed_won_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "site_id",
            sa.String(length=50),
            sa.ForeignKey("sites.site_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("external_deal_id", sa.String(length=255), nullable=False),
        sa.Column("email_bidx", sa.String(length=64), nullable=False),
        sa.Column("email_ciphertext", sa.String(), nullable=False),
        sa.Column("company_domain", sa.String(length=253), nullable=True),
        sa.Column("country", sa.String(length=5), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("identified_visitor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "site_id", "external_deal_id", "email_bidx", name="uq_crm_closed_won_deal_email"
        ),
    )
    op.create_index(
        "ix_crm_closed_won_contacts_site_id", "crm_closed_won_contacts", ["site_id"]
    )
    op.create_index(
        "ix_crm_closed_won_contacts_email_bidx", "crm_closed_won_contacts", ["email_bidx"]
    )


def downgrade() -> None:
    op.drop_index("ix_crm_closed_won_contacts_email_bidx", table_name="crm_closed_won_contacts")
    op.drop_index("ix_crm_closed_won_contacts_site_id", table_name="crm_closed_won_contacts")
    op.drop_table("crm_closed_won_contacts")
