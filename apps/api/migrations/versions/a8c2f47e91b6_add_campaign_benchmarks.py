"""add campaign_benchmarks + sites.benchmark_contribution_enabled

Two additive changes, both nullable/defaulted so an in-flight deploy never sees
a missing value:

* NEW ``campaign_benchmarks`` table — pooled, k-anonymous cross-tenant campaign
  counters. Deliberately holds NO site identifier, NO visitor reference, NO
  email, and NO tenant free text (``category_normalized`` comes from a closed
  vocabulary), which is what keeps GDPR erasure moot by construction.
* NEW ``sites.benchmark_contribution_enabled`` — the benchmark's OWN consent
  basis, separate from the identity co-op's ``sites.contribution_enabled``.

Revision ID: a8c2f47e91b6
Revises: f6a3c81d5e27
Create Date: 2026-08-17

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a8c2f47e91b6"
down_revision = "f6a3c81d5e27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sites",
        sa.Column(
            "benchmark_contribution_enabled",
            sa.Boolean(),
            nullable=True,
            server_default="false",
        ),
    )
    op.create_table(
        "campaign_benchmarks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("category_normalized", sa.String(length=50), nullable=False),
        sa.Column("period", sa.String(length=20), nullable=False),
        sa.Column("sends", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("opens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conversions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("site_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True
        ),
        sa.UniqueConstraint(
            "category_normalized",
            "period",
            name="uq_campaign_benchmarks_category_period",
        ),
    )


def downgrade() -> None:
    op.drop_table("campaign_benchmarks")
    op.drop_column("sites", "benchmark_contribution_enabled")
