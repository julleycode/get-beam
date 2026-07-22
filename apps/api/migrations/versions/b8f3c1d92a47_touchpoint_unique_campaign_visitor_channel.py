"""unique (campaign_id, visitor_id, channel) on campaign_touchpoints

Revision ID: b8f3c1d92a47
Revises: a2e6c9b4d1f8
Create Date: 2026-07-22

Closes a double-send race: idempotency was an application read-then-write on
status='sent' with no campaign lock, so two concurrent /send or /start calls
could both pass the check and email the same recipient twice — violating the
brand-critical "never double-send" invariant. The send loop now claims a
touchpoint row per (campaign, visitor, channel) before dispatching; this unique
constraint makes the DB reject the losing racer (IntegrityError → skip).

Only channel='email' rows are written today (campaign_sender), so the constraint
matches current semantics. A defensive dedupe runs first so the constraint can
be created even if legacy duplicates exist (keeps the sent/newest row per group).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b8f3c1d92a47"
down_revision: Union[str, None] = "a2e6c9b4d1f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT = "uq_campaign_touchpoints_campaign_visitor_channel"


def upgrade() -> None:
    # Drop any pre-existing duplicates, keeping one row per group: prefer a
    # 'sent' row, then the most recent sent_at, then a stable id tiebreak.
    op.execute(
        """
        DELETE FROM campaign_touchpoints
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY campaign_id, visitor_id, channel
                    ORDER BY (status = 'sent') DESC, sent_at DESC NULLS LAST, id
                ) AS rn
                FROM campaign_touchpoints
            ) ranked
            WHERE ranked.rn > 1
        )
        """
    )
    op.create_unique_constraint(
        _CONSTRAINT,
        "campaign_touchpoints",
        ["campaign_id", "visitor_id", "channel"],
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "campaign_touchpoints", type_="unique")
