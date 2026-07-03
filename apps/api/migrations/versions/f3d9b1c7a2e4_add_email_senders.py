"""add email_senders (Connect-Gmail outbound identity)

Revision ID: f3d9b1c7a2e4
Revises: c7e1a4b9d3f2
Create Date: 2026-07-03

Stores a site owner's connected Gmail so campaign email goes out FROM their
address (removes Gmail's "via sendgrid.info"). OAuth tokens are Fernet-encrypted
by the app before insert. One row per (user, provider); provider is future-proof
for Outlook but only "google" is written today. Nullable-friendly: purely
additive, no backfill, existing sends fall back to SendGrid when no row exists.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f3d9b1c7a2e4"
down_revision: Union[str, None] = "e2f5b8c1d094"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_senders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False, server_default="google"),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_email_sender_user_provider",
        "email_senders",
        ["user_id", "provider"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_email_sender_user_provider", table_name="email_senders")
    op.drop_table("email_senders")
