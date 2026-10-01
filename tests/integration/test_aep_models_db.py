"""AEP Service tables against real Postgres — constraints + cascade.

AEP integration task 20. Schema comes from ``Base.metadata.create_all`` (see
``tests/conftest.py``), so this proves the ``__table_args__`` declarations; the
alembic migration is round-tripped separately on a disposable container.

Precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis`.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from apps.api.models.aep import (
    AepAuditEvent,
    AepAuthorization,
    AepCredential,
    AepEnrollment,
    AepIdempotencyRecord,
    AepReplay,
)
from apps.api.models.user import User

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _did() -> str:
    return f"did:web:agent-{uuid.uuid4().hex[:8]}.example"


def _enrollment(did: str, **kw) -> AepEnrollment:
    return AepEnrollment(
        agent_did=did,
        enrollment_id=f"enr_{uuid.uuid4().hex}",
        status=kw.pop("status", "pending"),
        since=NOW,
        **kw,
    )


def _credential(did: str, **kw) -> AepCredential:
    return AepCredential(
        credential_id=f"cred_{uuid.uuid4().hex}",
        agent_did=did,
        grant_type="api-key",
        header_name="x-beam-agent-key",
        secret_hash=uuid.uuid4().bytes + uuid.uuid4().bytes,
        scopes=kw.pop("scopes", ["read"]),
        expires_at=NOW + timedelta(hours=24),
        **kw,
    )


async def _user(db) -> User:
    user = User(email=f"aep-{uuid.uuid4().hex[:8]}@example.com")
    db.add(user)
    await db.flush()
    return user


def _authorization(user: User, did: str, **kw) -> AepAuthorization:
    return AepAuthorization(
        owner_user_id=user.id,
        agent_did=did,
        site_ids=kw.pop("site_ids", ["site_abc"]),
        scopes=kw.pop("scopes", ["read", "spend"]),
        status=kw.pop("status", "active"),
        **kw,
    )


async def _expect_integrity_error(db, *rows) -> None:
    db.add_all(list(rows))
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_happy_path_insert_all_tables_with_defaults(test_db):
    db = test_db
    user = await _user(db)
    did = _did()
    db.add(_enrollment(did, status="active", purpose="paid"))
    await db.flush()
    db.add_all(
        [
            _authorization(user, did),
            _credential(did),
            AepIdempotencyRecord(
                agent_did=did,
                idempotency_key="k1",
                command="grant",
                request_hash="sha256:abc",
                state="in_flight",
                expires_at=NOW + timedelta(hours=1),
            ),
            AepReplay(subject=did, jwt_id="jti-1", expires_at=NOW),
            AepAuditEvent(event="enroll", agent_did=did, actor_user_id=user.id),
        ]
    )
    await db.flush()

    enr = (
        await db.execute(select(AepEnrollment).where(AepEnrollment.agent_did == did))
    ).scalar_one()
    assert enr.owner_action_required is False
    assert enr.requirements_pending == [] and enr.verification_pending == []
    assert enr.claims == {}
    audit = (
        await db.execute(select(AepAuditEvent).where(AepAuditEvent.agent_did == did))
    ).scalar_one()
    assert audit.detail == {}
    await db.rollback()


async def test_bad_enrollment_status_rejected(test_db):
    await _expect_integrity_error(test_db, _enrollment(_did(), status="approved"))


async def test_bad_enrollment_purpose_rejected(test_db):
    await _expect_integrity_error(test_db, _enrollment(_did(), purpose="admin"))


async def test_duplicate_enrollment_did_rejected(test_db):
    did = _did()
    await _expect_integrity_error(test_db, _enrollment(did), _enrollment(did))


@pytest.mark.parametrize(
    "scopes", [[], ["admin"], ["read", "send"]], ids=["empty", "unknown", "mixed"]
)
async def test_invalid_authorization_scopes_rejected(test_db, scopes):
    user = await _user(test_db)
    await _expect_integrity_error(test_db, _authorization(user, _did(), scopes=scopes))


async def test_bad_authorization_status_rejected(test_db):
    user = await _user(test_db)
    await _expect_integrity_error(
        test_db, _authorization(user, _did(), status="pending")
    )


async def test_duplicate_active_authorization_rejected(test_db):
    user = await _user(test_db)
    did = _did()
    await _expect_integrity_error(
        test_db, _authorization(user, did), _authorization(user, did)
    )


async def test_revoked_plus_active_authorization_allowed(test_db):
    db = test_db
    user = await _user(db)
    did = _did()
    db.add_all(
        [
            _authorization(user, did, status="revoked", revoked_at=NOW),
            _authorization(user, did, status="revoked", revoked_at=NOW),
            _authorization(user, did),
        ]
    )
    await db.flush()
    await db.rollback()


async def test_credential_scope_outside_vocabulary_rejected(test_db):
    did = _did()
    test_db.add(_enrollment(did))
    await test_db.flush()
    await _expect_integrity_error(test_db, _credential(did, scopes=["write"]))


async def test_credential_requires_existing_enrollment(test_db):
    await _expect_integrity_error(test_db, _credential(_did()))


async def test_duplicate_idempotency_key_rejected(test_db):
    did = _did()

    def rec() -> AepIdempotencyRecord:
        return AepIdempotencyRecord(
            agent_did=did,
            idempotency_key="same",
            command="enroll",
            request_hash="sha256:x",
            state="done",
            expires_at=NOW + timedelta(hours=1),
        )

    await _expect_integrity_error(test_db, rec(), rec())


async def test_bad_idempotency_state_rejected(test_db):
    await _expect_integrity_error(
        test_db,
        AepIdempotencyRecord(
            agent_did=_did(),
            idempotency_key="k",
            command="enroll",
            request_hash="sha256:x",
            state="failed",
            expires_at=NOW,
        ),
    )


async def test_duplicate_replay_jti_rejected(test_db):
    did = _did()
    await _expect_integrity_error(
        test_db,
        AepReplay(subject=did, jwt_id="j", expires_at=NOW),
        AepReplay(subject=did, jwt_id="j", expires_at=NOW),
    )


async def test_enrollment_delete_cascades_credentials(test_db):
    db = test_db
    did = _did()
    other = _did()
    db.add_all([_enrollment(did), _enrollment(other)])
    await db.flush()
    db.add_all([_credential(did), _credential(did), _credential(other)])
    await db.flush()
    db.expunge_all()

    enr = (
        await db.execute(select(AepEnrollment).where(AepEnrollment.agent_did == did))
    ).scalar_one()
    await db.delete(enr)
    await db.flush()

    async def count(agent_did: str) -> int:
        return (
            await db.execute(
                select(func.count())
                .select_from(AepCredential)
                .where(AepCredential.agent_did == agent_did)
            )
        ).scalar_one()

    assert await count(did) == 0
    assert await count(other) == 1
    await db.rollback()
