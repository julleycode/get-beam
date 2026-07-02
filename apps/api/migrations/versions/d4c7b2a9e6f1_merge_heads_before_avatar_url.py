"""merge 4 heads before avatar_url

Revision ID: d4c7b2a9e6f1
Revises: c9d2f7b4e1a6, d5a2b7c1e9f3, e7b4c2f9a1d8, f1a9c4d7e2b8
Create Date: 2026-07-02

Empty merge unifying the four divergent heads (consent_mode, suppression_list,
pii_ciphertext_columns, x_handle_to_waitlist) into one, so the deploy's auto
`alembic upgrade head` has a single target. No schema change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d4c7b2a9e6f1"
down_revision: Union[str, Sequence[str], None] = (
    "c9d2f7b4e1a6",
    "d5a2b7c1e9f3",
    "e7b4c2f9a1d8",
    "f1a9c4d7e2b8",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
