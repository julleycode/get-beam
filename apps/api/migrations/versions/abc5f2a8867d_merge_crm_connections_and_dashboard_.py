"""merge crm_connections and dashboard_layout heads

Revision ID: abc5f2a8867d
Revises: d9f2b6e4c8a1, e3a9c1d57b42
Create Date: 2026-06-29 01:41:06.812562

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'abc5f2a8867d'
down_revision: Union[str, None] = ('d9f2b6e4c8a1', 'e3a9c1d57b42')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
