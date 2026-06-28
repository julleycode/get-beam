"""add dashboard_layout to users

Revision ID: e3a9c1d57b42
Revises: c5d8e1f3a7b9
Create Date: 2026-06-29

Per-user dashboard widget layout (JSONB, keyed by surface, e.g.
{"visitors": ["funnel", "traffic_fit", "browser"]}). Nullable so existing rows
backfill as NULL = "use the default layout"; the Visitors page's customizable
widget grid reads/writes it via GET/PUT /api/v1/auth/widget-layout.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e3a9c1d57b42"
down_revision: Union[str, None] = "c5d8e1f3a7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("dashboard_layout", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "dashboard_layout")
