"""add fingerprint_v3 (fp3: base signals + fonts + audio)

The pixel's fingerprint gained two signals -- an installed-font probe and an
offline audio render -- which change the hash for every device. Overwriting the
existing ``fingerprint`` column with the new hash would make every already-known
visitor look brand new: ``fingerprint_match`` would miss, the cross-tenant
``beam_identity_graph`` would miss, and the resolver would re-pay a provider to
re-identify people Beam already owns.

So fp3 lands in its own column next to fp2 rather than replacing it. The pixel
emits BOTH hashes (``_fp`` unchanged + new ``_fp3``); the resolver prefers a v3
match and falls back to v2, so old rows, old pixel builds, and the async window
before fp3 resolves on the client all keep working.

``beam_identity_graph``'s unique key stays ``(fingerprint, email)`` -- untouched.
The new column is only an additional lookup path on the same row.

Additive and reversible: two nullable columns plus two indexes. No column
dropped or altered, no backfill, no constraint applied to existing data, so
nothing here rewrites or locks an existing table.

Revision ID: f1a7c3e05b92
Revises: e9d2a4c71f68
Create Date: 2026-08-07

"""
from alembic import op
import sqlalchemy as sa

revision = "f1a7c3e05b92"
down_revision = "e9d2a4c71f68"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "visitors",
        sa.Column("fingerprint_v3", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "idx_visitors_fingerprint_v3",
        "visitors",
        ["fingerprint_v3"],
        unique=False,
    )
    op.add_column(
        "beam_identity_graph",
        sa.Column("fingerprint_v3", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "idx_beam_identity_fingerprint_v3",
        "beam_identity_graph",
        ["fingerprint_v3"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_beam_identity_fingerprint_v3", table_name="beam_identity_graph")
    op.drop_column("beam_identity_graph", "fingerprint_v3")
    op.drop_index("idx_visitors_fingerprint_v3", table_name="visitors")
    op.drop_column("visitors", "fingerprint_v3")
