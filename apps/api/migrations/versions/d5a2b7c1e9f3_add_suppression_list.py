"""add suppression_list table (GDPR/CCPA do-not-sell / do-not-process)

Revision ID: d5a2b7c1e9f3
Revises: c3f8a1d6e2b4
Create Date: 2026-06-14

Phase 02 of the GDPR/CCPA technical compliance plan: a suppression list keyed
by a blind index (HMAC of the email) so a "Do Not Sell / Do Not Process"
request is honored automatically at resolution and export time, without storing
a second plaintext copy of the address.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d5a2b7c1e9f3"
down_revision: Union[str, None] = "c3f8a1d6e2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "suppression_list",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(length=320), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_suppression_hash_scope",
        "suppression_list",
        ["email_hash", "scope"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_suppression_hash_scope", table_name="suppression_list")
    op.drop_table("suppression_list")
