"""add agent_profiles table (agent-gateway Phase 1)

Agent-gateway program (feature: agent-gateway, 26-07-26), Phase 1.
ADDITIVE-ONLY, NON-DESTRUCTIVE: one brand-new table. No existing table, column,
constraint, or index is altered. Nothing here touches visitors,
identified_visitors, visitor_emails, or any identity/PII surface.

FK strategy (plan instruction E5, deliberate): ``agent_profiles.site_id`` is a
REAL FOREIGN KEY onto ``sites.site_id`` with a UNIQUE constraint, rather than
the soft ``site_id VARCHAR`` no-FK pattern used by ``agent_visits`` /
``campaigns``. Both precedents exist in this repo. The hard FK is correct here
because ``sites.site_id`` is itself UNIQUE and ``agent_profiles`` is a genuine
1:1 record (one profile per site), not an append-only rollup. A future reader
should NOT "fix" this to match the soft-reference majority style.

OFFLINE-VALIDATED ONLY (repo convention C2): this revision joins the queue of
migrations already pending live-apply. Never `alembic upgrade` against a real
environment as part of this plan. Note that this repo's offline `--sql`
shorthand (`upgrade head` / `downgrade -1`) fails mid-chain; use an EXPLICIT
`<from-rev>:<to-rev>` range.

Chained on e6b2d4a1c837 (cadence bot flag), OBSERVED live via
`.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` on 26-07-26
immediately before this file was written (single head, no branching) — not
assumed from context docs.

Revision ID: a4f7c2e9d31b
Revises: e6b2d4a1c837
Create Date: 2026-07-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a4f7c2e9d31b"
down_revision: Union[str, None] = "e6b2d4a1c837"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("site_id", sa.String(length=50), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("tagline", sa.String(length=300), nullable=True),
        sa.Column("long_description", sa.Text(), nullable=True),
        sa.Column(
            "offers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("primary_cta", sa.String(length=500), nullable=True),
        sa.Column("privacy_policy_url", sa.String(length=500), nullable=True),
        sa.Column("tos_url", sa.String(length=500), nullable=True),
        sa.Column("contact_email", sa.String(length=320), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["sites.site_id"],
            name="fk_agent_profiles_site_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("site_id", name="uq_agent_profiles_site_id"),
    )
    op.create_index(
        "ix_agent_profiles_site_id", "agent_profiles", ["site_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_agent_profiles_site_id", table_name="agent_profiles")
    op.drop_table("agent_profiles")
