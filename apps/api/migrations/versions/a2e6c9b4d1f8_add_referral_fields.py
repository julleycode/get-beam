"""add referral program fields to users

Revision ID: a2e6c9b4d1f8
Revises: d8f1c5a3b9e7
Create Date: 2026-07-06

Referral program ("give quota, get quota"): referral_code is each user's
shareable code (generated lazily, unique), referred_by_user_id links a new
account to its referrer, referral_activated_at doubles as the status column
(NULL = pending, set = referee activated + both sides rewarded), and
bonus_monthly_quota holds the earned extra identified-visitors added to the
monthly plan limit. Purely additive; server_default='0' keeps existing rows
valid under NOT NULL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a2e6c9b4d1f8"
down_revision: Union[str, None] = "d8f1c5a3b9e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("referral_code", sa.String(16), nullable=True))
    op.create_index("ix_users_referral_code", "users", ["referral_code"], unique=True)
    op.add_column(
        "users",
        sa.Column(
            "referred_by_user_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.create_foreign_key(
        "fk_users_referred_by_user_id",
        "users",
        "users",
        ["referred_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_users_referred_by_user_id", "users", ["referred_by_user_id"]
    )
    op.add_column(
        "users",
        sa.Column("referral_activated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "bonus_monthly_quota",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "bonus_monthly_quota")
    op.drop_column("users", "referral_activated_at")
    op.drop_index("ix_users_referred_by_user_id", table_name="users")
    op.drop_constraint("fk_users_referred_by_user_id", "users", type_="foreignkey")
    op.drop_column("users", "referred_by_user_id")
    op.drop_index("ix_users_referral_code", table_name="users")
    op.drop_column("users", "referral_code")
