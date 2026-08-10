"""Add ip_org_prefixes.as2org_org_id (CAIDA opaque org handle retention, WS-C).

Additive, nullable, unindexed. CAIDA's AS2Org ``organizationId`` (e.g.
``LPL-141-ARIN``) used to be discarded at parse time; it is now retained so a
family of ASNs sharing one org can be grouped for sizing and org-family
classification consistency. Populated only for ``source="caida_pfx2as"`` rows and
NULL for every other evidence class by construction.

No index: no query filters on the column yet, and an index on a ~1M-row table for
zero readers is pure write cost. A defaulted nullable column is a metadata-only
change on Postgres 11+ — no table rewrite.

Revision ID: d3f9a1c25e84
Revises: c4a8f13e07b6
Create Date: 2026-08-08
"""

import sqlalchemy as sa
from alembic import op

revision = "d3f9a1c25e84"
down_revision = "c4a8f13e07b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ip_org_prefixes",
        sa.Column("as2org_org_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ip_org_prefixes", "as2org_org_id")
