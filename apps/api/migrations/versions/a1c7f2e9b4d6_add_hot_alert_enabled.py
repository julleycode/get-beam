"""add hot_alert_enabled to sites

Revision ID: a1c7f2e9b4d6
Revises: b2e4a1c6d8f0
Create Date: 2026-06-23

Adds the per-site hot-visitor-alert toggle. Defaults to true so owners get the
real-time ping when a high-intent US visitor is identified; they can turn it off
per site. Gating (US + intent >= 40 + once-per-visitor) keeps the volume low.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a1c7f2e9b4d6"
down_revision: Union[str, None] = "b2e4a1c6d8f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sites",
        sa.Column(
            "hot_alert_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("sites", "hot_alert_enabled")
