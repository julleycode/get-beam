"""add consent_mode to sites

Revision ID: c9d2f7b4e1a6
Revises: b1c4e7f2a9d6
Create Date: 2026-07-01

Adds the per-site cookie-consent mode emitted into the pixel snippet as
data-consent. Defaults to "off" so existing rows are backfilled without a NULL
(the column is NOT NULL) and every existing site keeps its current behavior
(no banner; GPC/DNT opt-out still honored). Values: off | eu | all | cmp.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c9d2f7b4e1a6"
down_revision: Union[str, None] = "b1c4e7f2a9d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sites",
        sa.Column(
            "consent_mode",
            sa.String(length=10),
            nullable=False,
            server_default="off",
        ),
    )


def downgrade() -> None:
    op.drop_column("sites", "consent_mode")
