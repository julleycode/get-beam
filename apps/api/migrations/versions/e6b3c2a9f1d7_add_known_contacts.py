"""add known_contacts table (site owner's existing-customer list)

Revision ID: e6b3c2a9f1d7
Revises: b7e1a2c9d4f0
Create Date: 2026-06-14

Phase 03a of the visitor-filter plan. A per-site list of contacts the owner
already knows (uploaded from CSV / a CRM export). Stored as a blind index
(HMAC of the email, services/pii_crypto.py) — never plaintext — so matching an
identified visitor against the owner's list is hash-vs-hash. Lets the dashboard
flag "Known" visitors and filter them out of net-new targeting.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e6b3c2a9f1d7"
down_revision: Union[str, None] = "b7e1a2c9d4f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "known_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", sa.String(length=50), nullable=False),
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="csv"),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_known_contacts_site_id", "known_contacts", ["site_id"])
    op.create_index(
        "uq_known_site_hash",
        "known_contacts",
        ["site_id", "email_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_known_site_hash", table_name="known_contacts")
    op.drop_index("ix_known_contacts_site_id", table_name="known_contacts")
    op.drop_table("known_contacts")
