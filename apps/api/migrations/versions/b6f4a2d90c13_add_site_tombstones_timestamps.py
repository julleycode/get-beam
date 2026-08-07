"""add created_at/updated_at to site_tombstones

Repairs a Base-inheritance mismatch. ``apps/api/models/database.py`` declares
``created_at`` and ``updated_at`` (both ``DateTime(timezone=True)``,
``server_default=func.now()``, ``updated_at`` also ``onupdate=func.now()``) on
the shared declarative ``Base``, so EVERY model -- including
``SiteTombstone`` -- carries them. The original table-creating migration
(``e9d2a4c71f68_add_site_tombstones``) hand-listed only id/site_id/
normalized_url/user_id/deleted_at and omitted the two Base columns.

Consequence: the tombstone INSERT on the site-delete path
(``apps/api/routers/sites.py``) emits a RETURNING clause naming
``created_at``/``updated_at``, Postgres raises "column does not exist", the
transaction rolls back, and the dashboard surfaces "Failed to delete site".

The broken migration is already applied on production (Railway auto-applies on
deploy), so it must NOT be edited in place -- this is a new forward-only fix.

``ADD COLUMN IF NOT EXISTS`` is deliberate, not defensive sloppiness: an
operator may have hand-run the equivalent ALTER as a production hotfix before
this migration lands. IF NOT EXISTS makes the upgrade a no-op on an
already-patched database instead of failing the whole deploy boot. Downgrade is
symmetric with ``DROP COLUMN IF EXISTS``.

Additive only: two nullable-free columns with a ``now()`` default, so existing
rows backfill to the migration timestamp. No data rewrite, no constraint on
existing data, no index change.

Revision ID: b6f4a2d90c13
Revises: a3e8d5c71f02
Create Date: 2026-08-07

"""
from alembic import op

revision = "b6f4a2d90c13"
down_revision = "a3e8d5c71f02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE site_tombstones
          ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now(),
          ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE site_tombstones
          DROP COLUMN IF EXISTS updated_at,
          DROP COLUMN IF EXISTS created_at;
        """
    )
