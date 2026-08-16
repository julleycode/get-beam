"""add waitlist application fields

Additive-nullable only: 7 new nullable columns on ``waitlist_signups`` for the
private-beta /apply form. No backfill, no server default, no constraint, no index.

DEPENDENCY NOTE (read before any deploy): this revision chains onto
``c5e1a9b73d20`` (``add_site_profile``), which was UNTRACKED in git at the time
this migration was written — it belongs to the concurrent, uncommitted
``site-analysis-onboarding_13-08-26`` work. The user explicitly accepted this
risk and instructed chaining anyway. If that sibling revision is ever rebased
away, renamed, or dropped, this migration dangles: re-verify the chain
(``alembic heads``) before any deploy.

Revision ID: d7e2b4c81f93
Revises: c5e1a9b73d20
Create Date: 2026-08-15

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d7e2b4c81f93"
down_revision = "c5e1a9b73d20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("waitlist_signups", sa.Column("business_description", sa.String(1000), nullable=True))
    op.add_column("waitlist_signups", sa.Column("use_case", sa.String(1000), nullable=True))
    op.add_column("waitlist_signups", sa.Column("monthly_visitors", sa.String(32), nullable=True))
    op.add_column("waitlist_signups", sa.Column("role", sa.String(32), nullable=True))
    op.add_column("waitlist_signups", sa.Column("company_size", sa.String(32), nullable=True))
    op.add_column("waitlist_signups", sa.Column("plan_interest", sa.String(32), nullable=True))
    op.add_column(
        "waitlist_signups",
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("waitlist_signups", "applied_at")
    op.drop_column("waitlist_signups", "plan_interest")
    op.drop_column("waitlist_signups", "company_size")
    op.drop_column("waitlist_signups", "role")
    op.drop_column("waitlist_signups", "monthly_visitors")
    op.drop_column("waitlist_signups", "use_case")
    op.drop_column("waitlist_signups", "business_description")
