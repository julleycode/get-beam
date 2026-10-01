"""Agent Enrollment Protocol (AEP) Service tables.

Beam acts as an AEP *Service* (``did:web:api.getbeam.fyi``) via the
``agent-enrollment-protocol`` SDK (aep-python). These tables back the SDK's
store ports — ``EnrollmentStore``, ``ServiceCredentialStore``,
``IdempotencyStore``, ``ReplayStore`` — plus two Beam-only tables: owner
pre-registration / approval (``aep_authorizations``) and an append-only audit
trail (``aep_audit_events``). See ``AEP-INTEGRATION-PLAN.md`` task 20.

Deliberately SDK-free: nothing here imports ``agent_enrollment_protocol``. The
store adapters (task 30) translate between these rows and SDK records.

Secrets and PII posture (load-bearing):

- ``aep_enrollments.claims`` holds claim NAMES only. Claim values are personal
  data supplied by an unverified agent; the only value kept is the claimed email,
  and only as ``claimed_email_ciphertext`` (``pii_crypto.encrypt_pii``) plus
  ``claimed_email_bidx`` (``pii_crypto.email_hash``). There is no plaintext
  email column. A claimed email is a hint, never an identity.
- ``aep_credentials.secret_hash`` is HMAC-SHA256 of the issued api key under a
  server key. The plaintext key and the SDK's full ``ServiceCredentialRecord``
  credential object are never stored.
- ``aep_idempotency.response_body_ciphertext`` is encrypted at rest because a
  Grant replay body contains the plaintext api key. It must use the strict
  ``services/key_vault.py`` Fernet helpers (raise on missing key / bad token),
  never the graceful plaintext-passthrough ``pii_crypto.encrypt_pii``.
- ``aep_audit_events.detail`` must never contain secrets or claim values.

``id`` / ``created_at`` / ``updated_at`` come from ``Base``.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base

# Mirrors the SDK's AgentStatus (core/models.py:64-70).
ENROLLMENT_STATUSES = (
    "active",
    "pending",
    "unavailable",
    "suspended",
    "terminated",
    "rejected",
)
# 'customer' = an agent acting for a Beam user's sites (owner-authorized).
# 'paid'     = an independent agent enrolled only for /api/paid/* access.
ENROLLMENT_PURPOSES = ("customer", "paid")
AUTHORIZATION_STATUSES = ("active", "revoked")
# Permanent deny-list lives in route code; these are the only grantable scopes.
AEP_SCOPES = ("read", "spend", "generate")
IDEMPOTENCY_STATES = ("in_flight", "done")

_SCOPES_ARRAY_SQL = "ARRAY[" + ", ".join(f"'{s}'" for s in AEP_SCOPES) + "]::text[]"


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class AepEnrollment(Base):
    """One row per enrolled agent DID (SDK ``EnrollmentRecord`` + Beam fields).

    ``agent_did`` is UNIQUE so the store's ``find_or_create`` can be an
    ``INSERT ... ON CONFLICT (agent_did) DO NOTHING`` followed by a SELECT.

    ``claims`` stores claim NAMES only (a JSON object keyed by claim name, values
    non-identifying such as ``true``). Never put claim values here — the claimed
    email goes to the ciphertext + blind-index columns below.
    """

    __tablename__ = "aep_enrollments"
    __table_args__ = (
        CheckConstraint(
            _in_list("status", ENROLLMENT_STATUSES),
            name="ck_aep_enrollments_status",
        ),
        CheckConstraint(
            _in_list("purpose", ENROLLMENT_PURPOSES),
            name="ck_aep_enrollments_purpose",
        ),
        Index("ix_aep_enrollments_claimed_email_bidx", "claimed_email_bidx"),
    )

    agent_did: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    enrollment_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    owner_action_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    requirements_pending: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    verification_pending: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    # Claim NAMES only — see class docstring.
    claims: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # pii_crypto.encrypt_pii(claimed email) — a hint, never an identity.
    claimed_email_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    # pii_crypto.email_hash(claimed email) — blind index for owner matching.
    claimed_email_bidx: Mapped[str | None] = mapped_column(Text, nullable=True)
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    purpose: Mapped[str] = mapped_column(
        Text, nullable=False, default="customer", server_default=text("'customer'")
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AepAuthorization(Base):
    """Owner pre-registration / approval of an agent DID for some sites + scopes.

    ``site_ids`` holds ``Site.site_id`` slugs (not UUID PKs). Non-empty and
    owner-membership are validated in service code. At most one ``active`` row
    per (owner, agent DID); revoked rows are kept for audit.
    """

    __tablename__ = "aep_authorizations"
    __table_args__ = (
        CheckConstraint(
            _in_list("status", AUTHORIZATION_STATUSES),
            name="ck_aep_authorizations_status",
        ),
        CheckConstraint(
            f"cardinality(scopes) > 0 AND scopes <@ {_SCOPES_ARRAY_SQL}",
            name="ck_aep_authorizations_scopes",
        ),
        Index(
            "uq_aep_authorizations_owner_did_active",
            "owner_user_id",
            "agent_did",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_aep_authorizations_agent_did", "agent_did"),
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_did: Mapped[str] = mapped_column(Text, nullable=False)
    site_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    # Max ~120 chars, enforced in service code.
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AepCredential(Base):
    """An issued api-key session credential (SDK ``CredentialMatch`` source).

    ``secret_hash`` = HMAC-SHA256(server key, api key). Lookups must filter
    ``revoked_at IS NULL AND expires_at > :current_time`` using the SDK request's
    ``current_time`` — an expired match makes the SDK raise (HTTP 500).
    """

    __tablename__ = "aep_credentials"
    __table_args__ = (
        CheckConstraint(
            f"scopes <@ {_SCOPES_ARRAY_SQL}",
            name="ck_aep_credentials_scopes",
        ),
        Index("ix_aep_credentials_agent_did", "agent_did"),
        Index(
            "ix_aep_credentials_agent_did_live",
            "agent_did",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    credential_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    agent_did: Mapped[str] = mapped_column(
        Text,
        ForeignKey("aep_enrollments.agent_did", ondelete="CASCADE"),
        nullable=False,
    )
    grant_type: Mapped[str] = mapped_column(Text, nullable=False)
    header_name: Mapped[str] = mapped_column(Text, nullable=False)
    secret_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    scopes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AepIdempotencyRecord(Base):
    """SDK ``IdempotencyStore`` row: single-flight claim + stored response.

    Claim with ``INSERT state='in_flight' ON CONFLICT DO NOTHING``; a row with a
    different ``command``/``request_hash`` is a conflict (409). ``expires_at`` is
    at least ``created_at + 1h`` (spec minimum TTL).

    ``response_body_ciphertext`` = ``key_vault.encrypt_key(body)`` — strict
    Fernet. A Grant replay body contains the plaintext api key.
    """

    __tablename__ = "aep_idempotency"
    __table_args__ = (
        UniqueConstraint(
            "agent_did", "idempotency_key", name="uq_aep_idempotency_agent_key"
        ),
        CheckConstraint(
            _in_list("state", IDEMPOTENCY_STATES),
            name="ck_aep_idempotency_state",
        ),
        Index("ix_aep_idempotency_expires_at", "expires_at"),
    )

    agent_did: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_headers: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    response_body_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AepReplay(Base):
    """Postgres fallback for client-assertion jti replay (Redis is primary).

    ``consume`` = ``INSERT ... ON CONFLICT (subject, jwt_id) DO NOTHING``; zero
    rows inserted means replay. Rows past ``expires_at`` are purged by a job.
    """

    __tablename__ = "aep_replay"
    __table_args__ = (
        UniqueConstraint("subject", "jwt_id", name="uq_aep_replay_subject_jti"),
        Index("ix_aep_replay_expires_at", "expires_at"),
    )

    subject: Mapped[str] = mapped_column(Text, nullable=False)
    jwt_id: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AepAuditEvent(Base):
    """Append-only AEP audit trail (no update or delete path).

    ``event`` is e.g. enroll, approve, reject, suspend, grant, revoke, auth_fail.
    ``detail`` must never carry secrets or claim values.
    """

    __tablename__ = "aep_audit_events"
    __table_args__ = (
        Index("ix_aep_audit_events_agent_did_created", "agent_did", "created_at"),
    )

    event: Mapped[str] = mapped_column(Text, nullable=False)
    agent_did: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    credential_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    site_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
