"""add engage_outcomes table + drafts.platform_comment_id / drafts.site_id

engage-learning-agent Phase 1 (signal acquisition).

Three additive changes, no destructive step:

1. ``drafts.platform_comment_id`` — the platform's own id for a reply we posted.
   Nullable: historical rows have no id and a post that succeeds without
   returning one must still be recorded as sent.
2. ``drafts.site_id`` — the site a draft is attributed to. FK targets the unique
   ``sites.site_id`` SLUG (``String(50)``), NOT the UUID PK, matching every other
   site-keyed consumer in the repo. ``ON DELETE SET NULL`` because losing a site
   must not cascade-delete draft history. Nullable, and NULL is a legitimate
   outcome (multi-site user, no visitor to disambiguate) that every consumer
   fails closed on.
3. ``engage_outcomes`` — append-only outcome facts. No body/text column exists by
   design (AC-6), and no ``contact_bidx`` ships here: the blind-index helper and
   the erasure registration are Phase-2 owned, so adding a PII-derived column now
   would ship un-erasable PII (N5/N6).

The dedupe index is PARTIAL (``WHERE platform_ref IS NOT NULL``). Its predicate
must stay textually identical to the ``__table_args__`` declaration in
``apps/api/models/engage_outcome.py`` — the metrics upsert infers this index as
its ON CONFLICT arbiter, and Postgres only infers a partial index when the
statement repeats the predicate verbatim. The index is declared in BOTH places
because the integration lane builds schema via ``Base.metadata.create_all`` and
never runs alembic.

Revision ID: c5a91f3e07d4
Revises: b7e4d21a9c58
Create Date: 2026-08-17

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c5a91f3e07d4"
down_revision = "b7e4d21a9c58"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "drafts", sa.Column("platform_comment_id", sa.String(length=64), nullable=True)
    )
    op.add_column("drafts", sa.Column("site_id", sa.String(length=50), nullable=True))
    op.create_index("ix_drafts_site_id", "drafts", ["site_id"])
    op.create_foreign_key(
        "fk_drafts_site_id_sites",
        "drafts",
        "sites",
        ["site_id"],
        ["site_id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "engage_outcomes",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("site_id", sa.String(length=50), nullable=True),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform_comment_id", sa.String(length=64), nullable=True),
        sa.Column("outcome_type", sa.String(length=32), nullable=False),
        sa.Column("platform_ref", sa.String(length=128), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=True),
        sa.Column("retweet_count", sa.Integer(), nullable=True),
        sa.Column("quote_count", sa.Integer(), nullable=True),
        sa.Column("reply_count", sa.Integer(), nullable=True),
        sa.Column("strategy", sa.String(length=50), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
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
            ["draft_id"], ["drafts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.site_id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "outcome_type IN ('reply_received', 'metrics_snapshot', 'attributed_visit')",
            name="ck_engage_outcomes_outcome_type",
        ),
    )
    op.create_index("ix_engage_outcomes_site_id", "engage_outcomes", ["site_id"])
    op.create_index(
        "uq_engage_outcomes_dedup",
        "engage_outcomes",
        ["draft_id", "outcome_type", "platform_ref"],
        unique=True,
        postgresql_where=sa.text("platform_ref IS NOT NULL"),
    )
    op.create_index(
        "ix_engage_outcomes_site_strategy_created",
        "engage_outcomes",
        ["site_id", "strategy", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_engage_outcomes_site_strategy_created", table_name="engage_outcomes"
    )
    op.drop_index("uq_engage_outcomes_dedup", table_name="engage_outcomes")
    op.drop_index("ix_engage_outcomes_site_id", table_name="engage_outcomes")
    op.drop_table("engage_outcomes")

    op.drop_constraint("fk_drafts_site_id_sites", "drafts", type_="foreignkey")
    op.drop_index("ix_drafts_site_id", table_name="drafts")
    op.drop_column("drafts", "site_id")
    op.drop_column("drafts", "platform_comment_id")
