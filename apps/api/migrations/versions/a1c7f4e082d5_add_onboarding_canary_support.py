"""add onboarding canary support

Two additive changes for the onboarding location reveal.

1. ``idx_visitors_fingerprint`` — REQUIRED, not an optimisation nicety. The
   ``visitors`` table carries only ``site_id`` composite indexes, so every
   fingerprint match is a sequential scan. The canary polls that lookup every
   2-4s for up to 90s per onboarding user. Also speeds the existing
   ``/demo/identify`` and ``/demo/journey``.

2. ``identity_feedback`` — where the "not quite" answer now lands. The legacy
   funnel built the form and read the DOM zero times.

Both are additive and reversible: one new index on an existing column, one new
table. No backfill, no constraint on existing data, no rewrite.

Revision ID: a1c7f4e082d5
Revises: d3f9a1c25e84
Create Date: 2026-08-10

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a1c7f4e082d5"
down_revision = "d3f9a1c25e84"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_visitors_fingerprint",
        "visitors",
        ["fingerprint"],
        unique=False,
    )

    op.create_table(
        "identity_feedback",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Nullable: the canary runs BEFORE site creation, so most rows have none.
        sa.Column("site_id", sa.String(length=50), nullable=True),
        sa.Column("fingerprint", sa.String(length=100), nullable=True),
        sa.Column("surface", sa.String(length=40), nullable=False),
        # Exactly what was rendered (city/region/country/org/kind + ROUNDED
        # lat-lng). Without it a "wrong city" report is unactionable.
        sa.Column(
            "shown",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "reasons",
            postgresql.ARRAY(sa.String(length=40)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # REQUIRED, not decoration. models/database.py:81 declares `updated_at`
        # on `Base` itself, so EVERY model has it whether or not the subclass
        # restates it — and SQLAlchemy puts it in the INSERT ... RETURNING
        # clause. Omitting it here made every /identity-feedback submission
        # 500 with UndefinedColumnError against a real database, while the
        # integration tests stayed green because conftest builds the schema
        # from metadata (create_all), not from this migration. Found by
        # exercising the live endpoint; see Phase 3's report.
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_identity_feedback_surface_created",
        "identity_feedback",
        ["surface", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_identity_feedback_surface_created",
        table_name="identity_feedback",
    )
    op.drop_table("identity_feedback")
    op.drop_index("idx_visitors_fingerprint", table_name="visitors")
