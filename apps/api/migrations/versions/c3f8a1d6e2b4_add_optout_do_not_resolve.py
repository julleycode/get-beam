"""add privacy opt-out columns (events.optout, visitors.do_not_resolve)

Revision ID: c3f8a1d6e2b4
Revises: b7e1a2c9d4f0
Create Date: 2026-06-14

Phase 01 of the GDPR/CCPA technical compliance plan: honor GPC/DNT signals.

The pixel sets ``events.optout`` when the browser signals Global Privacy
Control or Do Not Track. The visitor aggregator BOOL_ORs that into
``visitors.do_not_resolve`` (sticky), and the identity resolver refuses to
resolve any visitor with the flag set. Both columns default false so existing
rows keep their current behavior.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c3f8a1d6e2b4"
down_revision: Union[str, None] = "b7e1a2c9d4f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "optout",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "visitors",
        sa.Column(
            "do_not_resolve",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("visitors", "do_not_resolve")
    op.drop_column("events", "optout")
