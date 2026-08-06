"""add resolution deferral watermark to visitors

When every provider tier that could identify a visitor was DOWN, the resolver
used to write ``identity_status = 'unresolvable'`` — the same ending as a real
no-match. Both sweeps select ``anonymous`` only, so that write removed the
visitor from every future run permanently, over a fault that was ours to wait
out. The only ways back were a manual Retry or an IP change.

These two columns let the resolver hold such a visitor at ``anonymous`` behind
a timestamp instead, and let both sweeps skip it until the timestamp passes.

Why a column and not a Redis breaker: the scarce resource is the per-site sweep
slot (``LIMIT 20`` in services/resolution_runner.py, ``LIMIT 50`` in
tasks/resolution_tasks.py, both ordered by ``intent_score DESC``). A breaker
skips the HTTP call, but the row is still SELECTed and still ranked top — so a
long outage would park deferred visitors at the head of every batch and starve
new ones. Only a column can be part of the sweep's WHERE clause.

Additive and reversible: two columns, no index, no constraint, no backfill.
Existing rows get NULL / 0, which reads as "never deferred" — identical
behaviour to before for every row that is not in an outage.

No index: the sweep filter is always ANDed with ``site_id`` +
``identity_status``, which ``idx_visitors_identity_status`` already covers, and
the deferred population is a small fraction of a site's anonymous rows.

Revision ID: c2f7a9d31b64
Revises: b4c9a71e35d8
Create Date: 2026-08-06

"""
from alembic import op
import sqlalchemy as sa

revision = "c2f7a9d31b64"
down_revision = "b4c9a71e35d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "visitors",
        sa.Column("resolution_deferred_until", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "visitors",
        sa.Column(
            "resolution_defer_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("visitors", "resolution_defer_count")
    op.drop_column("visitors", "resolution_deferred_until")
