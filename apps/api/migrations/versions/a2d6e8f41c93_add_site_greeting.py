"""add sites.greeting_enabled + sites.greeting_templates (on-site greeting)

Additive only (onsite-greeting_27-11-26). Dormant until BOTH
ONSITE_GREETING_ENABLED and a site's greeting_enabled are True.

Revision ID: a2d6e8f41c93
Revises: f7d1b3c84e29
Create Date: 2026-11-27

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a2d6e8f41c93"
down_revision = "f7d1b3c84e29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sites",
        sa.Column(
            "greeting_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "sites",
        sa.Column("greeting_templates", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sites", "greeting_templates")
    op.drop_column("sites", "greeting_enabled")
