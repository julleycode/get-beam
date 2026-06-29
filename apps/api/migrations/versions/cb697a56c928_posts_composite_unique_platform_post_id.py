"""posts composite unique platform_post_id

Revision ID: cb697a56c928
Revises: abc5f2a8867d
Create Date: 2026-06-29 14:16:18.401057

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cb697a56c928'
down_revision: Union[str, None] = 'abc5f2a8867d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The global UNIQUE on posts.platform_post_id caused cross-user collisions:
    # a public tweet one customer imported blocked every other customer from
    # importing it ("already in your feed" — but it wasn't). Relax it to a
    # per-account composite unique. Safe: existing data is globally unique, so
    # every (social_account_id, platform_post_id) pair is already unique.
    op.drop_index(op.f("ix_posts_platform_post_id"), table_name="posts")
    op.create_index(
        op.f("ix_posts_platform_post_id"), "posts", ["platform_post_id"], unique=False
    )
    op.create_unique_constraint(
        "uq_posts_account_platform_post",
        "posts",
        ["social_account_id", "platform_post_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_posts_account_platform_post", "posts", type_="unique")
    op.drop_index(op.f("ix_posts_platform_post_id"), table_name="posts")
    op.create_index(
        op.f("ix_posts_platform_post_id"), "posts", ["platform_post_id"], unique=True
    )
