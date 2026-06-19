"""add updated_at to api_usage_logs

Revision ID: b2e4a1c6d8f0
Revises: a4d1f0b9c3e2
Create Date: 2026-06-20

The Base declarative class gives every model created_at AND updated_at, but the
api_usage_logs table was created (f7c2e9a4b1d3) with only created_at. The ORM
therefore emits `RETURNING ... updated_at` on every insert, which crashed with
UndefinedColumnError the moment the resolution sweep first logged an API call on
a DB built from migrations. Add the missing column to match the model and every
other table. Idempotent so it is a no-op where the column already exists.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2e4a1c6d8f0"
down_revision: Union[str, None] = "a4d1f0b9c3e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE api_usage_logs "
        "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now()"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE api_usage_logs DROP COLUMN IF EXISTS updated_at")
