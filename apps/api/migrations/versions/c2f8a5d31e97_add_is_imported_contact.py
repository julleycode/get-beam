"""add is_imported_contact to visitors

Identity-honesty Phase 4 (contact import). A CSV-imported contact becomes a
PHANTOM ``Visitor`` row (``visitor_id = f"import:{contact_id}"``) so every
existing join (segments, campaign_sender, dashboards, aggregator) works
unmodified. This flag marks those rows so human traffic/engagement surfaces can
exclude a phantom that has not been visited yet — mirroring the
``is_agent_derived`` precedent, except the exclusion is conditional, not
permanent (see ``agent_visitor_filters.human_only_visitor_filter``).

Additive and fully reversible: one boolean column with a server_default, no
backfill, no constraint, no index. Existing rows read as False, which is
correct — they were not imported.

Revision ID: c2f8a5d31e97
Revises: b1c9e7f24d83
Create Date: 2026-08-04

"""
from alembic import op
import sqlalchemy as sa

revision = "c2f8a5d31e97"
down_revision = "b1c9e7f24d83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "visitors",
        sa.Column(
            "is_imported_contact",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("visitors", "is_imported_contact")
