"""add outcomes webhook secret columns to sites

Revision ID: c4f8b2d6a9e1
Revises: b7e3a9c4d1f6
Create Date: 2026-07-04

Server-side conversion webhook (outcomes P3): each site can hold one signing
secret for POST /api/v1/outcomes/{site_id}/webhook. Stored Fernet-encrypted;
the hint ("...abcd") is the only recoverable display form. NULL = webhook not
configured (endpoint answers 503). Purely additive.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c4f8b2d6a9e1"
down_revision: Union[str, None] = "b7e3a9c4d1f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sites",
        sa.Column("outcomes_webhook_secret_ciphertext", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "sites",
        sa.Column("outcomes_webhook_secret_hint", sa.String(length=12), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sites", "outcomes_webhook_secret_hint")
    op.drop_column("sites", "outcomes_webhook_secret_ciphertext")
