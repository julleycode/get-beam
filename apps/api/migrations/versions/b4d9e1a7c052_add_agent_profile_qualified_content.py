"""add agent_profiles.qualified_content — WS3 agent concierge qualified answers

Revision ID: b4d9e1a7c052
Revises: a2f8d61c9e37
Create Date: 2026-07-30

Additive only: one nullable-with-default JSONB column on an existing table. The
column holds customer-authored gated content (configured pricing, competitor
comparisons, security answers), served ONLY when a caller supplies the 3
qualification params AND agent_concierge_qualification_enabled is on (default
False). No behavior change on apply — nothing reads it until the flag is flipped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b4d9e1a7c052"
down_revision: Union[str, None] = "a2f8d61c9e37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_profiles",
        sa.Column(
            "qualified_content",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_profiles", "qualified_content")
