"""add server_visitor_id to visitors (durable _rta_svid reconciliation)

Revision ID: b1c4e7f2a9d6
Revises: a7c3e9f1b6d2
Create Date: 2026-06-30

P1 of the own-data identity program. Stores the original visitor_id carried by
the HttpOnly `_rta_svid` server cookie so a returning visitor whose CLIENT id was
wiped (Safari ITP) can be reconciled to their prior identification for free,
instead of being treated as a brand-new anonymous visitor and re-resolved at
provider cost. Nullable — existing rows backfill as NULL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b1c4e7f2a9d6"
down_revision: Union[str, None] = "a7c3e9f1b6d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "visitors",
        sa.Column("server_visitor_id", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("visitors", "server_visitor_id")
