"""add uq_coop_ledger_expire_per_lot partial unique index

identity-coop Phase 2a (E2 — MANDATORY, not conditional).

At most ONE ``EXPIRE`` row per credit lot, enforced at the DB tier rather than
only in service code. This matters because duplicate EXPIRE rows are
BALANCE-INVISIBLE under the lot-symmetric stamping rule (both duplicates carry the
lot's ``[spendable_at, expires_at]`` window, so they enter and leave the balance
filter together with the ACCRUE they zero) — no balance assertion at any tier
could ever see them. Phase 3's dashboard, however, reads EXPIRE rows WITHOUT the
balance window predicate and would report double the credits lost: durable audit
corruption on a billing surface.

Same principle Phase 1 applied to ``uq_coop_accrued_site_email``: a uniqueness
rule is enforced by a DB partial unique index so a concurrent race cannot corrupt
the ledger, not by service code that a second process does not observe.

``expire_lapsed_lots`` targets this index by predicate with
``ON CONFLICT (lot_id) WHERE entry_type = 'EXPIRE' DO NOTHING``, so a losing racer
is a silent no-op rather than a 500.

No E1 covering index is included: the A4/S-9 EXPLAIN evidence showed no seq scan
on ``api_usage_logs``. Had it fired, the E1 index would have been added to THIS
file — a second migration file is never created for it.

Revision ID: b7e4d21a9c58
Revises: a8c2f47e91b6
Create Date: 2026-08-17

"""
import sqlalchemy as sa
from alembic import op

revision = "b7e4d21a9c58"
down_revision = "a8c2f47e91b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_coop_ledger_expire_per_lot",
        "identity_credit_ledger",
        ["lot_id"],
        unique=True,
        postgresql_where=sa.text("entry_type = 'EXPIRE'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_coop_ledger_expire_per_lot", table_name="identity_credit_ledger"
    )
