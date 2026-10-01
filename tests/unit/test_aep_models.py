"""AEP Service tables — metadata shape + migration chain (no DB).

AEP integration task 20. The DB-tier behaviour (constraint violations, cascade)
is covered by ``tests/integration/test_aep_models_db.py``.
"""

import ast
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint, Index, UniqueConstraint

import apps.api.models  # noqa: F401  — registers the aep tables
from apps.api.models import aep
from apps.api.models.database import Base

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS = REPO_ROOT / "apps" / "api" / "migrations" / "versions"
MIGRATION = VERSIONS / "6078903ea368_add_aep_service_tables.py"
PRIOR_HEAD = "c5a91f3e07d4"

AEP_TABLES = {
    "aep_enrollments",
    "aep_authorizations",
    "aep_credentials",
    "aep_idempotency",
    "aep_replay",
    "aep_audit_events",
}


def _table(name):
    return Base.metadata.tables[name]


def _checks(table) -> dict[str, str]:
    return {
        c.name: str(c.sqltext)
        for c in table.constraints
        if isinstance(c, CheckConstraint)
    }


def _indexes(table) -> dict[str, Index]:
    return {i.name: i for i in table.indexes}


def _unique_sets(table) -> set[tuple[str, ...]]:
    out = {
        tuple(c.name for c in uc.columns)
        for uc in table.constraints
        if isinstance(uc, UniqueConstraint)
    }
    out |= {(c.name,) for c in table.columns if c.unique}
    return out


def test_all_six_tables_registered():
    assert AEP_TABLES <= set(Base.metadata.tables)


@pytest.mark.parametrize("name", sorted(AEP_TABLES))
def test_every_table_has_base_columns(name):
    cols = set(_table(name).columns.keys())
    assert {"id", "created_at", "updated_at"} <= cols


def test_enrollment_columns_and_constraints():
    t = _table("aep_enrollments")
    cols = t.columns
    for name in (
        "agent_did",
        "enrollment_id",
        "status",
        "owner_action_required",
        "requirements_pending",
        "verification_pending",
        "claims",
        "since",
        "purpose",
    ):
        assert cols[name].nullable is False, name
    assert ("agent_did",) in _unique_sets(t)
    assert ("enrollment_id",) in _unique_sets(t)
    fk = next(iter(cols["decided_by_user_id"].foreign_keys))
    assert fk.target_fullname == "users.id" and fk.ondelete == "SET NULL"

    checks = _checks(t)
    for status in aep.ENROLLMENT_STATUSES:
        assert f"'{status}'" in checks["ck_aep_enrollments_status"]
    assert set(aep.ENROLLMENT_STATUSES) == {
        "active", "pending", "unavailable", "suspended", "terminated", "rejected"
    }
    assert "'customer'" in checks["ck_aep_enrollments_purpose"]
    assert "'paid'" in checks["ck_aep_enrollments_purpose"]
    assert "ix_aep_enrollments_claimed_email_bidx" in _indexes(t)


def test_enrollment_stores_no_plaintext_claim_values():
    cols = set(_table("aep_enrollments").columns.keys())
    assert {"claimed_email_ciphertext", "claimed_email_bidx"} <= cols
    assert not {"email", "claimed_email"} & cols
    doc = aep.AepEnrollment.__doc__ or ""
    assert "claim NAMES only" in doc


def test_authorization_constraints():
    t = _table("aep_authorizations")
    fk = next(iter(t.columns["owner_user_id"].foreign_keys))
    assert fk.target_fullname == "users.id" and fk.ondelete == "CASCADE"
    assert t.columns["owner_user_id"].nullable is False

    scope_check = _checks(t)["ck_aep_authorizations_scopes"]
    assert "cardinality(scopes) > 0" in scope_check
    assert "scopes <@ ARRAY['read', 'spend', 'generate']::text[]" in scope_check
    assert "'revoked'" in _checks(t)["ck_aep_authorizations_status"]

    idx = _indexes(t)
    active = idx["uq_aep_authorizations_owner_did_active"]
    assert active.unique
    assert [c.name for c in active.columns] == ["owner_user_id", "agent_did"]
    assert str(active.dialect_options["postgresql"]["where"]) == "status = 'active'"
    assert "ix_aep_authorizations_agent_did" in idx


def test_credential_shape():
    t = _table("aep_credentials")
    fk = next(iter(t.columns["agent_did"].foreign_keys))
    assert fk.target_fullname == "aep_enrollments.agent_did"
    assert fk.ondelete == "CASCADE"
    assert ("credential_id",) in _unique_sets(t)
    assert ("secret_hash",) in _unique_sets(t)
    # Never a plaintext key column.
    assert not {"api_key", "secret", "credential"} & set(t.columns.keys())
    live = _indexes(t)["ix_aep_credentials_agent_did_live"]
    assert str(live.dialect_options["postgresql"]["where"]) == "revoked_at IS NULL"


def test_idempotency_replay_audit_shape():
    idem = _table("aep_idempotency")
    assert ("agent_did", "idempotency_key") in _unique_sets(idem)
    assert "'in_flight'" in _checks(idem)["ck_aep_idempotency_state"]
    assert "response_body_ciphertext" in idem.columns
    assert "response_body" not in idem.columns
    assert "ix_aep_idempotency_expires_at" in _indexes(idem)

    replay = _table("aep_replay")
    assert ("subject", "jwt_id") in _unique_sets(replay)
    assert "ix_aep_replay_expires_at" in _indexes(replay)

    audit = _table("aep_audit_events")
    idx = _indexes(audit)["ix_aep_audit_events_agent_did_created"]
    assert [c.name for c in idx.columns] == ["agent_did", "created_at"]
    assert audit.columns["detail"].nullable is False


def _module_assign(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found")


def test_migration_chains_on_prior_head_and_is_sole_child():
    tree = ast.parse(MIGRATION.read_text())
    assert _module_assign(tree, "revision") == "6078903ea368"
    assert _module_assign(tree, "down_revision") == PRIOR_HEAD
    # No other migration claims the same parent (no branch).
    siblings = [
        p.name
        for p in VERSIONS.glob("*.py")
        if p != MIGRATION
        and f'down_revision = "{PRIOR_HEAD}"' in p.read_text()
    ]
    assert siblings == []


def test_migration_downgrade_drops_all_six_tables():
    tree = ast.parse(MIGRATION.read_text())
    downgrade = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "downgrade"
    )
    dropped = {
        call.args[0].value
        for call in ast.walk(downgrade)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "drop_table"
    }
    assert dropped == AEP_TABLES
