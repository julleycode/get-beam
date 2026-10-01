"""add AEP Service tables

AEP integration task 20 (``AEP-INTEGRATION-PLAN.md``). Six new tables backing the
aep-python SDK store ports plus Beam owner authorization and audit. Purely
additive — no existing table is touched.

- ``aep_enrollments``     — one row per agent DID (``EnrollmentStore``).
  ``claims`` holds claim NAMES only; the claimed email is stored solely as
  ``claimed_email_ciphertext`` + ``claimed_email_bidx``.
- ``aep_authorizations``  — owner pre-registration / approval (sites + scopes).
  One ``active`` row per (owner, DID) via a partial unique index.
- ``aep_credentials``     — issued api keys as HMAC ``secret_hash`` only;
  ``agent_did`` FK to ``aep_enrollments.agent_did`` ON DELETE CASCADE.
- ``aep_idempotency``     — ``IdempotencyStore``; response body encrypted at rest
  (a Grant replay contains the plaintext api key).
- ``aep_replay``          — Postgres fallback for jti replay (Redis primary).
- ``aep_audit_events``    — append-only audit trail.

Every index/constraint here is ALSO declared in ``apps/api/models/aep.py``
``__table_args__`` because the integration lane builds schema with
``Base.metadata.create_all`` and never runs alembic. Keep both in sync.

Revision ID: 6078903ea368
Revises: c5a91f3e07d4
Create Date: 2026-10-01

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "6078903ea368"
down_revision = "c5a91f3e07d4"
branch_labels = None
depends_on = None

_SCOPES_ARRAY_SQL = "ARRAY['read', 'spend', 'generate']::text[]"
_EMPTY_TEXT_ARRAY = sa.text("'{}'::text[]")
_EMPTY_JSONB = sa.text("'{}'::jsonb")


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
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
    ]


def upgrade() -> None:
    op.create_table(
        "aep_enrollments",
        *_base_columns(),
        sa.Column("agent_did", sa.Text(), nullable=False),
        sa.Column("enrollment_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "owner_action_required",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "requirements_pending",
            postgresql.ARRAY(sa.Text()),
            server_default=_EMPTY_TEXT_ARRAY,
            nullable=False,
        ),
        sa.Column(
            "verification_pending",
            postgresql.ARRAY(sa.Text()),
            server_default=_EMPTY_TEXT_ARRAY,
            nullable=False,
        ),
        sa.Column(
            "claims",
            postgresql.JSONB(),
            server_default=_EMPTY_JSONB,
            nullable=False,
        ),
        sa.Column("claimed_email_ciphertext", sa.Text(), nullable=True),
        sa.Column("claimed_email_bidx", sa.Text(), nullable=True),
        sa.Column("since", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "purpose", sa.Text(), server_default=sa.text("'customer'"), nullable=False
        ),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("agent_did", name="aep_enrollments_agent_did_key"),
        sa.UniqueConstraint("enrollment_id", name="aep_enrollments_enrollment_id_key"),
        sa.CheckConstraint(
            "status IN ('active', 'pending', 'unavailable', 'suspended', "
            "'terminated', 'rejected')",
            name="ck_aep_enrollments_status",
        ),
        sa.CheckConstraint(
            "purpose IN ('customer', 'paid')",
            name="ck_aep_enrollments_purpose",
        ),
    )
    op.create_index(
        "ix_aep_enrollments_claimed_email_bidx",
        "aep_enrollments",
        ["claimed_email_bidx"],
    )

    op.create_table(
        "aep_authorizations",
        *_base_columns(),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_did", sa.Text(), nullable=False),
        sa.Column("site_ids", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_aep_authorizations_status",
        ),
        sa.CheckConstraint(
            f"cardinality(scopes) > 0 AND scopes <@ {_SCOPES_ARRAY_SQL}",
            name="ck_aep_authorizations_scopes",
        ),
    )
    op.create_index(
        "uq_aep_authorizations_owner_did_active",
        "aep_authorizations",
        ["owner_user_id", "agent_did"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_aep_authorizations_agent_did", "aep_authorizations", ["agent_did"]
    )

    op.create_table(
        "aep_credentials",
        *_base_columns(),
        sa.Column("credential_id", sa.Text(), nullable=False),
        sa.Column("agent_did", sa.Text(), nullable=False),
        sa.Column("grant_type", sa.Text(), nullable=False),
        sa.Column("header_name", sa.Text(), nullable=False),
        sa.Column("secret_hash", sa.LargeBinary(), nullable=False),
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.Text()),
            server_default=_EMPTY_TEXT_ARRAY,
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["agent_did"], ["aep_enrollments.agent_did"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("credential_id", name="aep_credentials_credential_id_key"),
        sa.UniqueConstraint("secret_hash", name="aep_credentials_secret_hash_key"),
        sa.CheckConstraint(
            f"scopes <@ {_SCOPES_ARRAY_SQL}",
            name="ck_aep_credentials_scopes",
        ),
    )
    op.create_index("ix_aep_credentials_agent_did", "aep_credentials", ["agent_did"])
    op.create_index(
        "ix_aep_credentials_agent_did_live",
        "aep_credentials",
        ["agent_did"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "aep_idempotency",
        *_base_columns(),
        sa.Column("agent_did", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_content_type", sa.Text(), nullable=True),
        sa.Column("response_headers", postgresql.JSONB(), nullable=True),
        sa.Column("response_body_ciphertext", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "agent_did", "idempotency_key", name="uq_aep_idempotency_agent_key"
        ),
        sa.CheckConstraint(
            "state IN ('in_flight', 'done')",
            name="ck_aep_idempotency_state",
        ),
    )
    op.create_index(
        "ix_aep_idempotency_expires_at", "aep_idempotency", ["expires_at"]
    )

    op.create_table(
        "aep_replay",
        *_base_columns(),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("jwt_id", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("subject", "jwt_id", name="uq_aep_replay_subject_jti"),
    )
    op.create_index("ix_aep_replay_expires_at", "aep_replay", ["expires_at"])

    op.create_table(
        "aep_audit_events",
        *_base_columns(),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("agent_did", sa.Text(), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("credential_id", sa.Text(), nullable=True),
        sa.Column("site_id", sa.Text(), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(),
            server_default=_EMPTY_JSONB,
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_aep_audit_events_agent_did_created",
        "aep_audit_events",
        ["agent_did", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_aep_audit_events_agent_did_created", table_name="aep_audit_events"
    )
    op.drop_table("aep_audit_events")

    op.drop_index("ix_aep_replay_expires_at", table_name="aep_replay")
    op.drop_table("aep_replay")

    op.drop_index("ix_aep_idempotency_expires_at", table_name="aep_idempotency")
    op.drop_table("aep_idempotency")

    op.drop_index("ix_aep_credentials_agent_did_live", table_name="aep_credentials")
    op.drop_index("ix_aep_credentials_agent_did", table_name="aep_credentials")
    op.drop_table("aep_credentials")

    op.drop_index("ix_aep_authorizations_agent_did", table_name="aep_authorizations")
    op.drop_index(
        "uq_aep_authorizations_owner_did_active", table_name="aep_authorizations"
    )
    op.drop_table("aep_authorizations")

    op.drop_index(
        "ix_aep_enrollments_claimed_email_bidx", table_name="aep_enrollments"
    )
    op.drop_table("aep_enrollments")
