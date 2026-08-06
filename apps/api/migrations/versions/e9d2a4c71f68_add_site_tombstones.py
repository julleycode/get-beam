"""add site_tombstones

Records the identity (site_id + normalized url + owner + timestamp) of a deleted
site so that a re-create for the SAME normalized url by the SAME user can reuse
the original ``site_id``. Without this, ``create_site`` mints a fresh random id
on every create, the tracking snippet already installed on the customer's page
keeps sending the old id, and ingest rejects it -- silently orphaning a live
pixel.

Stores ONLY id/url/owner/timestamp. Never event, visitor, or identity data, so
this table is not a soft-delete or an undo mechanism; the 17-table hard cascade
in ``delete_site`` is untouched.

Deliberately NO unique constraint on ``site_id``: a domain can be deleted and
re-created repeatedly, so the lookup orders by ``deleted_at DESC`` and takes the
newest row. Reuse *eligibility* is bounded at read time by
``site_id_reclaim_window_days`` (default 90) -- rows themselves are never pruned,
so no cron is introduced.

Additive and reversible: one new table plus one composite index matching the
exact lookup shape. No column added/dropped/altered on any existing table, no
backfill, no data rewrite, no constraint on existing data -- nothing here locks
an existing table.

Revision ID: e9d2a4c71f68
Revises: c2f8a5d31e97
Create Date: 2026-08-04

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e9d2a4c71f68"
down_revision = "c2f8a5d31e97"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_tombstones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("site_id", sa.String(length=50), nullable=False),
        sa.Column("normalized_url", sa.String(length=500), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Exactly the create_site reuse lookup shape:
    #   WHERE user_id = :uid AND normalized_url IN :variants
    #   AND deleted_at >= now() - window ORDER BY deleted_at DESC LIMIT 1
    op.create_index(
        "ix_site_tombstones_user_url",
        "site_tombstones",
        ["user_id", "normalized_url", "deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_site_tombstones_user_url", table_name="site_tombstones")
    op.drop_table("site_tombstones")
