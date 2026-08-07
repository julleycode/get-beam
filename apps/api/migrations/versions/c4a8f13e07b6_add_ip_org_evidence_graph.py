"""Add the IP-org evidence graph: relationship typing, validity dates, RPKI ROAs.

Phase 3 stops treating ``ip_org_prefixes`` as a flat prefix→company table. Each
row now records WHICH relationship it asserts (``relationship_type``) and WHEN
that assertion was published (``valid_from`` / ``valid_to``), so BGP origin data
— which frequently names a transit provider rather than the end organization —
is no longer indistinguishable from a registry allocation.

Three things in here are load-bearing and easy to get wrong:

1. ``relationship_type`` is added ``NOT NULL DEFAULT 'route_origin'``. Postgres
   11+ adds a defaulted NOT NULL column without rewriting the table, and the
   default is correct BY CONSTRUCTION: every pre-existing row came from CAIDA
   pfx2as, which IS BGP origin data. Backfilling at next ingest instead would
   leave the table without a relationship for up to a full refresh interval
   while the live v1 lookup reads it.

2. ``asn`` becomes NULLABLE. RIR delegated-extended records publish a range and
   an opaque handle and carry no ASN whatsoever. A ``0`` sentinel would be a
   fabricated fact every future reader must special-case; NULL states the same
   thing checkably.

3. **The downgrade ORDER is load-bearing.** ``asn`` cannot go back to NOT NULL
   while RIR rows exist, because those rows legitimately hold NULL. So the
   downgrade DELETEs them FIRST. Without that DELETE this is the one downgrade
   path in the repo that fails on real data — on any database that has ever
   ingested RIR allocations. The deletion is not lossy in any meaningful sense:
   those rows are rebuilt wholesale by the next ``refresh_rir_allocations``.

``rpki_roas`` is created here rather than in its own revision so the whole phase
is one reversible unit. It is a separate TABLE rather than evidence rows because
an ROA authorizes an ASN, not an organization, and carries ``maxLength``, which
has no home in an org-keyed row.

Revision ID: c4a8f13e07b6
Revises: b6f4a2d90c13
Create Date: 2026-08-07
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c4a8f13e07b6"
down_revision = "b6f4a2d90c13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── ip_org_prefixes → evidence rows ──────────────────────────────────────
    op.add_column(
        "ip_org_prefixes",
        sa.Column(
            "relationship_type",
            sa.String(length=32),
            nullable=False,
            server_default="route_origin",
        ),
    )
    op.add_column("ip_org_prefixes", sa.Column("valid_from", sa.Date(), nullable=True))
    op.add_column("ip_org_prefixes", sa.Column("valid_to", sa.Date(), nullable=True))

    # D13: RIR registered-holder evidence carries no ASN. NULL, never a sentinel.
    op.alter_column(
        "ip_org_prefixes",
        "asn",
        existing_type=sa.Integer(),
        nullable=True,
    )

    op.create_index(
        "idx_ip_org_prefixes_relationship_type",
        "ip_org_prefixes",
        ["relationship_type"],
    )

    # Backfill the snapshot date every existing row already carries. One pass;
    # the table is ~1M rows and this takes tens of seconds. Accepted rather than
    # optimized: ``ip_org_lookup_enabled`` is OFF everywhere this migration will
    # reach, so there is no concurrent reader to block. (If that ever stops
    # being true, move the index to CREATE INDEX CONCURRENTLY in its own
    # non-transactional revision — it cannot run inside alembic's transaction.)
    op.execute(
        "UPDATE ip_org_prefixes SET valid_from = dataset_date WHERE valid_from IS NULL"
    )

    # ── rpki_roas ────────────────────────────────────────────────────────────
    op.create_table(
        "rpki_roas",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prefix", postgresql.CIDR(), nullable=False),
        # BIGINT: ASNs are 32-bit UNSIGNED (RFC 6793) and 4-byte ASNs really do
        # appear in published ROAs — 17 of them in a 755,538-row live dump, up to
        # 4,294,967,294. An INTEGER column rejects those rows outright.
        sa.Column("asn", sa.BigInteger(), nullable=False),
        sa.Column("max_length", sa.Integer(), nullable=False),
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
    # ``inet_ops`` is REQUIRED — the default GiST opclass for cidr does not
    # support the ``>>=`` containment operator this table exists to answer.
    op.execute(
        "CREATE INDEX idx_rpki_roas_prefix_gist "
        "ON rpki_roas USING gist (prefix inet_ops)"
    )


def downgrade() -> None:
    op.drop_table("rpki_roas")

    # ORDER MATTERS — see the module docstring. RIR rows hold a legitimate NULL
    # asn, so re-imposing NOT NULL before deleting them fails on any database
    # that has ingested allocations. Matching on ``asn IS NULL`` rather than on
    # the source string covers any future ASN-less evidence class too.
    op.execute("DELETE FROM ip_org_prefixes WHERE asn IS NULL")
    op.alter_column(
        "ip_org_prefixes",
        "asn",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.drop_index("idx_ip_org_prefixes_relationship_type", table_name="ip_org_prefixes")
    op.drop_column("ip_org_prefixes", "valid_to")
    op.drop_column("ip_org_prefixes", "valid_from")
    op.drop_column("ip_org_prefixes", "relationship_type")
