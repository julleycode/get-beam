"""add CHECK constraint on visitor_emails.source (canonical enum)

Revision ID: a9f2c1e7b4d6
Revises: e2a4c7f81b93
Create Date: 2026-07-24

first-party-capture Phase 3 (AC13). Formalizes the visitor_emails.source value
space with a CHECK constraint matching VISITOR_EMAIL_SOURCES (apps/api/models/
visitor_email.py). The router already normalizes any unrecognized value to
"other" via normalize_source(), so this constraint is defense-in-depth against a
future write path that bypasses that helper.

The IN(...) list is a SUPERSET of every value any live write path has ever
emitted (form/utm/manual/email_click/login/checkout/newsletter/input/identify
+ the new mailto_click/url_param + the "other" fallback), so it cannot fail on
existing rows. Column shape is unchanged (stays String(20)).

down_revision re-verified live at EXECUTE time via `alembic heads` as
e2a4c7f81b93 (single head — the Handoff Detection Phase-02 agent_handoff_links
migration). Additive-only. Docker-gated: offline-validate only in this sandbox
(`alembic upgrade head --sql` dry-run), never live-applied against a real
Postgres — matching the owned-data-layer / evallayer migration convention.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a9f2c1e7b4d6"
down_revision: Union[str, None] = "e2a4c7f81b93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT = "ck_visitor_emails_source"
# Keep in lockstep with VISITOR_EMAIL_SOURCES in models/visitor_email.py.
_ALLOWED = (
    "form", "utm", "manual", "email_click", "login", "checkout",
    "newsletter", "input", "identify", "mailto_click", "url_param", "other",
)


def upgrade() -> None:
    values = ", ".join(f"'{v}'" for v in _ALLOWED)
    op.create_check_constraint(
        _CONSTRAINT,
        "visitor_emails",
        f"source IN ({values})",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "visitor_emails", type_="check")
