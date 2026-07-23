"""add AI-referral attribution fields (visitors.first_touch_referrer, ai_source)

Revision ID: b3f9a1d2c7e5
Revises: a1c7e4f92b83
Create Date: 2026-07-23

AI-Referral Attribution (v1). Two purely-additive columns plus one index:

* ``visitors.first_touch_referrer`` — the chronologically-first pageview's
  referrer (VARCHAR(500) NULL). ``top_referrer`` is ``MAX(referrer)`` =
  lexicographic, unusable for attribution; this is the true first-touch value.
* ``visitors.ai_source`` — the AI answer-engine label derived from
  ``first_touch_referrer`` via ``classify_ai_source`` (VARCHAR(30) NULL).
  ADDITIVE ATTRIBUTION METADATA ONLY — never sets ``source_agent_visit_id``,
  never gates emailability.
* index ``idx_visitors_site_ai_source`` on ``(site_id, ai_source)`` — powers the
  Source facet / list filter (mirrors ``idx_visitors_identity_status``).

Backfill: none. Both aggregation paths do a full recompute, so the columns
populate on the next pass.

See:
process/features/... (AI-Referral Attribution v1 plan)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b3f9a1d2c7e5"
down_revision: Union[str, None] = "a1c7e4f92b83"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "visitors",
        sa.Column("first_touch_referrer", sa.String(500), nullable=True),
    )
    op.add_column(
        "visitors",
        sa.Column("ai_source", sa.String(30), nullable=True),
    )
    op.create_index(
        "idx_visitors_site_ai_source",
        "visitors",
        ["site_id", "ai_source"],
    )


def downgrade() -> None:
    op.drop_index("idx_visitors_site_ai_source", table_name="visitors")
    op.drop_column("visitors", "ai_source")
    op.drop_column("visitors", "first_touch_referrer")
