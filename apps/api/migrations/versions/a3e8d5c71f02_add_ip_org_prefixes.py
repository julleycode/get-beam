"""add ip_org_prefixes (self-hosted IP→org database, Pillar 1)

visitors-identity / ip-org-database, Phase 1 (07-08-26).

Purely ADDITIVE: one new table plus its indexes. No existing table is touched,
so both directions are safe and the downgrade is a clean DROP.

Two details are load-bearing:

1. ``prefix`` is ``postgresql.CIDR``, not text. The lookup is
   ``WHERE prefix >>= :ip ORDER BY masklen(prefix) DESC LIMIT 1`` — the
   containment operator and ``masklen`` only exist on the network type.
2. The GiST index declares the ``inet_ops`` operator class explicitly. The
   DEFAULT GiST opclass for cidr does not support ``>>=``; without ``inet_ops``
   Postgres accepts the index and then never uses it, silently turning every
   lookup into a sequential scan over ~1M rows.

The ``ip_org_prefixes_staging`` twin is deliberately NOT created here — the
ingest service creates it (``CREATE TABLE … LIKE … INCLUDING ALL``) and drops it
on every run, so it is runtime state, not schema.

Chained off ``f2c81a6b4d09`` (identity-coop's add_site_contribution_enabled),
which is UNCOMMITTED at write time — both must land together, or this migration's
``down_revision`` dangles. Re-run
``.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads`` before applying;
concurrent programs advance this repo's head on a roughly daily cadence.

Revision ID: a3e8d5c71f02
Revises: f2c81a6b4d09
Create Date: 2026-08-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3e8d5c71f02"
down_revision: Union[str, None] = "f2c81a6b4d09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ip_org_prefixes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prefix", postgresql.CIDR(), nullable=False),
        sa.Column("asn", sa.Integer(), nullable=False),
        sa.Column("org_name", sa.String(length=200), nullable=False),
        sa.Column("org_name_raw", sa.String(length=200), nullable=True),
        sa.Column("domain", sa.String(length=253), nullable=True),
        sa.Column("org_kind", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("dataset_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_ip_org_prefixes_prefix_gist",
        "ip_org_prefixes",
        ["prefix"],
        unique=False,
        postgresql_using="gist",
        postgresql_ops={"prefix": "inet_ops"},
    )
    op.create_index("idx_ip_org_prefixes_asn", "ip_org_prefixes", ["asn"], unique=False)
    op.create_index(
        "idx_ip_org_prefixes_org_name", "ip_org_prefixes", ["org_name"], unique=False
    )


def downgrade() -> None:
    op.drop_index("idx_ip_org_prefixes_org_name", table_name="ip_org_prefixes")
    op.drop_index("idx_ip_org_prefixes_asn", table_name="ip_org_prefixes")
    op.drop_index("idx_ip_org_prefixes_prefix_gist", table_name="ip_org_prefixes")
    op.drop_table("ip_org_prefixes")
