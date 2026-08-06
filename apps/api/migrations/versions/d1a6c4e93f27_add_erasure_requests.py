"""add erasure_requests (cross-tenant identity graph erasure queue)

graph-erasure-compliance plan (visitors-identity, 07-08-26), C-01/C-02/C-03.
Additive-only, NON-DESTRUCTIVE: one new table plus two indexes. No existing
table, column, or constraint is touched, so reverting the code leaves the table
as a harmless orphan.

The table is plaintext-free by construction: it stores blind indexes
(email_bidx_list) and fingerprints, never an email address.

Chained on c9f4a7b31e85 (add_ws2_agent_operated_flag) — confirmed the live
single head via `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads`
on 07-08-26 immediately before this file was written. Never hardcode a head;
re-run `heads` before applying, since concurrent programs advance it.

OFFLINE-VALIDATED ONLY (repo convention): this revision joins the queue of
migrations already pending live-apply. Live-apply is a separate explicit
operator action. Offline `--sql` dry-runs in this repo need an EXPLICIT
<from>:<to> rev range (the `upgrade head --sql` shorthand fails mid-chain on
b7d3e9f1a4c2's sa.inspect call).

Revision ID: d1a6c4e93f27
Revises: c9f4a7b31e85
Create Date: 2026-08-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d1a6c4e93f27"
down_revision: Union[str, None] = "c9f4a7b31e85"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "erasure_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("requesting_site_id", sa.String(length=50), nullable=False),
        sa.Column("visitor_id", sa.String(length=64), nullable=False),
        sa.Column(
            "email_bidx_list",
            postgresql.ARRAY(sa.String(length=64)),
            nullable=True,
        ),
        sa.Column(
            "fingerprint_list",
            postgresql.ARRAY(sa.String(length=64)),
            nullable=True,
        ),
        sa.Column(
            "targets",
            postgresql.ARRAY(sa.String(length=50)),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        # Forensic marker only — never filtered on any execution path (C-14).
        sa.Column(
            "throttle_flagged",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index(
        "idx_erasure_requests_status_created",
        "erasure_requests",
        ["status", "created_at"],
    )
    op.create_index(
        "idx_erasure_requests_site",
        "erasure_requests",
        ["requesting_site_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_erasure_requests_site", table_name="erasure_requests")
    op.drop_index(
        "idx_erasure_requests_status_created", table_name="erasure_requests"
    )
    op.drop_table("erasure_requests")
