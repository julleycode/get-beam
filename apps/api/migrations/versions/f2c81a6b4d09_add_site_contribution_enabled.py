"""add sites.contribution_enabled (identity co-op per-site opt-in)

identity-coop Phase 1 (visitors-identity, 07-08-26), step A5.
Additive-only, NON-DESTRUCTIVE: one new boolean column with
``server_default='false'`` so every existing row is backfilled OFF in place and
no site is ever silently opted into the data co-op by a migration.

The column is NOT NULL with a server default rather than nullable, because
"unknown" must not be representable here: any ambiguity would have to be resolved
somewhere, and the only safe resolution for a consent flag is False. The
server_default keeps the ALTER non-blocking on Postgres 11+ (no table rewrite).

Reverting is safe: the co-op hook is additionally gated on
``settings.identity_coop_enabled`` (default False), so dropping this column
cannot leave a half-enabled co-op behind.

Chained on e7b3d5f19c46 (add_identity_coop_tables). Re-run
`.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` before applying —
concurrent programs advance this repo's head on a roughly daily cadence.

Revision ID: f2c81a6b4d09
Revises: e7b3d5f19c46
Create Date: 2026-08-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2c81a6b4d09"
down_revision: Union[str, None] = "e7b3d5f19c46"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sites",
        sa.Column(
            "contribution_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("sites", "contribution_enabled")
