"""Cross-tenant identity-graph erasure — pure-logic unit coverage (mocked DB).

The `-m unit` lane is mock-only per tests/conftest.py ("Unit tests: no DB, no
network"), so every gate here asserts a CODE-SHAPE or PURE-FUNCTION property:

- the write boundary refuses to write for a do_not_resolve / erased visitor
- the suppression refactor preserved is_email_suppressed exactly
- exactly one blind-index hash implementation exists
- the claim commits SEPARATELY from the destructive work (Boundary 1)
- the failure path re-issues a fresh status update and never wedges at
  'processing' (Boundary 3)
- the tombstone INSERT and the graph DELETE share ONE db.begin() scope with the
  tombstone strictly first and nothing between them (Boundary 2)
- queue health warns on a stale queue AND on any failed row, carrying no PII

MOCKING NOTE (binding, and deliberately NOT copied from a sibling test). The
Boundary-2 gates must NOT assert on db.commit(). AsyncSession.begin() in the
pinned sqlalchemy 2.0.35 is a SYNCHRONOUS method returning an
AsyncSessionTransaction whose __aexit__ calls the sync transaction's __exit__ —
it never calls AsyncSession.commit(). So an "exactly one commit" assertion would
FAIL on the correct implementation and PASS on the broken bare-statements shape,
i.e. inverted from its purpose. These gates therefore assert on db.begin's call
count, on its context manager's __aexit__ (call count + exception info), and on
db.execute call ordering. No existing test in this repo mocks a context-manager
session, so the mock below is built deliberately rather than copied.
"""

import re
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

import apps.api.main  # noqa: F401 — registers every ORM mapper before use
from apps.api.models.erasure_request import ERASURE_STATUSES, ERASURE_TARGETS
from apps.api.services import graph_erasure as ge
from apps.api.services import suppression as sup
from apps.api.services.identity_resolver import IdentityResolver
from apps.api.services.pii_crypto import email_hash

pytestmark = pytest.mark.unit

EMAIL = "erased.person@example.com"


def _scalar_result(value):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=value)
    r.scalar = MagicMock(return_value=value)
    return r


def _work_session(delete_raises: bool = False) -> MagicMock:
    """A session mock that faithfully models `async with db.begin():`.

    db.begin() is SYNCHRONOUS and returns a context manager — a plain AsyncMock
    would make it return a coroutine and `async with` would raise TypeError
    before any assertion ran.
    """
    db = MagicMock()
    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=txn)
    txn.__aexit__ = AsyncMock(return_value=False)
    db.begin = MagicMock(return_value=txn)

    calls: list[str] = []

    async def _execute(stmt, *a, **kw):
        label = type(stmt).__name__
        text = str(stmt)
        if "suppression_list" in text:
            label = "tombstone_insert"
        elif "beam_identity_graph" in text:
            label = "graph_delete"
            if delete_raises:
                calls.append(label)
                raise RuntimeError(f"boom for {EMAIL}")
        elif "identity_signals" in text:
            label = "identity_signals_delete"
        elif "erasure_requests" in text:
            label = "erasure_status_update"
        calls.append(label)
        return _scalar_result(None)

    db.execute = AsyncMock(side_effect=_execute)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.recorded = calls
    return db


def _claimed(attempts: int = 1) -> dict:
    return {
        "id": uuid.uuid4(),
        "attempts": attempts,
        "email_bidx_list": [email_hash(EMAIL)],
        "fingerprint_list": ["fp-abc"],
        "targets": list(ERASURE_TARGETS),
    }


# ───────────────────────── T-U1 / T-U2: write boundary ─────────────────────────


@pytest.mark.asyncio
async def test_t_u1_do_not_resolve_visitor_writes_no_graph_row():
    """T-U1 — a do_not_resolve visitor never reaches the graph insert, and the
    block is logged without any email substring."""
    db = MagicMock()
    db.execute = AsyncMock(return_value=_scalar_result(None))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    resolver = IdentityResolver(db, redis_client=None)
    visitor = SimpleNamespace(
        fingerprint="fp-abc",
        fingerprint_v3=None,
        site_id="site_a",
        visitor_id="visitor-1234567890",
        do_not_resolve=True,
    )

    with structlog.testing.capture_logs() as logs:
        await resolver._upsert_beam_identity(visitor, {"email": EMAIL}, "pdl")

    assert db.execute.await_count == 0, "a blocked visitor issued a graph statement"
    assert db.commit.await_count == 0
    events = [rec["event"] for rec in logs]
    assert "graph_write_blocked" in events
    assert "beam_identity_upserted" not in events
    assert EMAIL not in str(logs), "the block log leaked a plaintext email"
    assert "example.com" not in str(logs)


@pytest.mark.asyncio
async def test_t_u2_erased_tombstone_blocks_graph_write():
    """T-U2 — an "erased" tombstone alone blocks the write (it is already in the
    guard's scope tuple, so it does not depend on the do_not_process row)."""
    assert "erased" in ge.GRAPH_WRITE_BLOCKING_SCOPES

    db = MagicMock()
    # The suppression lookup finds a row => suppressed.
    db.execute = AsyncMock(return_value=_scalar_result(uuid.uuid4()))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    resolver = IdentityResolver(db, redis_client=None)
    visitor = SimpleNamespace(
        fingerprint="fp-abc",
        fingerprint_v3=None,
        site_id="site_a",
        visitor_id="visitor-1234567890",
        do_not_resolve=False,
    )

    with structlog.testing.capture_logs() as logs:
        await resolver._upsert_beam_identity(visitor, {"email": EMAIL}, "pdl")

    # Exactly one statement: the suppression lookup. No insert, no commit.
    assert db.execute.await_count == 1
    assert db.commit.await_count == 0
    assert "graph_write_blocked" in [rec["event"] for rec in logs]


# ───────────────────────── T-U3: no regression ─────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope", ["all", "do_not_process", "do_not_email", "do_not_sell"]
)
@pytest.mark.parametrize("has_entry", [True, False])
async def test_t_u3_is_email_suppressed_behavior_unchanged(scope, has_entry):
    """T-U3 — the delegate preserves the exact signature and result, and still
    issues exactly one query, for every scope with and without a match."""
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=_scalar_result(uuid.uuid4() if has_entry else None)
    )

    assert await sup.is_email_suppressed(db, EMAIL, scope) is has_entry
    assert db.execute.await_count == 1

    # The scope tuple passed to the SQL is exactly (scope, "all") — unchanged.
    rendered = str(db.execute.await_args.args[0])
    assert "suppression_list" in rendered


@pytest.mark.asyncio
async def test_t_u3b_empty_email_short_circuits_without_query():
    assert await sup.is_email_suppressed(MagicMock(), "", "all") is False
    assert await sup.is_email_suppressed_any(MagicMock(), "", ("erased",)) is False


def test_t_u3c_erased_is_a_valid_scope():
    assert "erased" in sup.VALID_SCOPES
    # Additive only — no pre-existing scope was removed.
    assert {"all", "do_not_sell", "do_not_process", "do_not_email"} <= sup.VALID_SCOPES


# ───────────────────────── T-U4: one hash implementation ─────────────────────────


def test_t_u4_single_blind_index_implementation():
    """T-U4 — every consumer routes through pii_crypto.email_hash, so a graph
    email_bidx is directly usable as a suppression_list email_hash. A second
    implementation appearing later breaks this pin."""
    from apps.api.services import identity_signals

    assert sup.email_hash is email_hash
    assert identity_signals.email_hash is email_hash
    assert ge.email_hash is email_hash

    h = email_hash(EMAIL)
    assert h == email_hash(EMAIL.upper()), "hash is not normalisation-stable"
    assert len(h) == 64 and h != EMAIL


# ───────────────────────── T-U5: state machine ─────────────────────────


def test_t_u5_status_and_target_constants():
    assert ERASURE_STATUSES == ("pending", "processing", "done", "failed")
    assert ERASURE_TARGETS == ("beam_identity_graph", "identity_signals")


@pytest.mark.asyncio
async def test_t_u5b_claim_on_non_pending_row_is_a_no_op():
    """T-U5 — when no pending row exists the claim returns None and issues no
    UPDATE, so a row already claimed by another worker is never re-claimed."""
    db = MagicMock()
    db.execute = AsyncMock(return_value=_scalar_result(None))
    db.commit = AsyncMock()

    assert await ge._claim_next(db) is None
    assert db.execute.await_count == 1  # the candidate SELECT only


@pytest.mark.asyncio
async def test_t_u5c_lost_claim_race_returns_none():
    """The candidate existed but the conditional UPDATE matched nothing —
    another worker won. Must be a skip, never a crash."""
    db = MagicMock()
    select_result = _scalar_result(uuid.uuid4())
    update_result = MagicMock()
    update_result.first = MagicMock(return_value=None)
    db.execute = AsyncMock(side_effect=[select_result, update_result])
    db.commit = AsyncMock()

    assert await ge._claim_next(db) is None
    assert db.commit.await_count == 1, "the claim attempt must still be committed"


@pytest.mark.asyncio
async def test_t_u5d_claim_increments_attempts_and_captures_returning():
    db = MagicMock()
    rid = uuid.uuid4()
    select_result = _scalar_result(rid)
    update_result = MagicMock()
    update_result.first = MagicMock(
        return_value=(rid, 3, ["bidx-1"], ["fp-1"], ["beam_identity_graph"])
    )
    db.execute = AsyncMock(side_effect=[select_result, update_result])
    db.commit = AsyncMock()

    claimed = await ge._claim_next(db)

    assert claimed["attempts"] == 3
    assert claimed["email_bidx_list"] == ["bidx-1"]
    rendered = str(db.execute.await_args_list[1].args[0])
    assert "attempts" in rendered
    # The claim query must never filter on the forensic marker (E-2: scoped to
    # the claim statement only — enqueue_erasure in the same module must and
    # does write that column).
    assert "throttle_flagged" not in rendered


# ───────────────────────── T-U6: Boundary 1 ─────────────────────────


@pytest.mark.asyncio
async def test_t_u6_claim_commits_before_any_destructive_statement():
    """T-U6 (Boundary 1) — the claim's commit lands BEFORE the work begins, so a
    crash in the work cannot roll back the attempts increment. Without this,
    attempts >= max_attempts can never trip and the stale reclaim is dead code."""
    order: list[str] = []
    db = MagicMock()
    rid = uuid.uuid4()
    select_result = _scalar_result(rid)
    update_result = MagicMock()
    update_result.first = MagicMock(return_value=(rid, 1, [], [], ["x"]))

    async def _execute(stmt, *a, **kw):
        order.append("execute")
        return select_result if len(order) == 1 else update_result

    db.execute = AsyncMock(side_effect=_execute)

    async def _commit():
        order.append("commit")

    db.commit = AsyncMock(side_effect=_commit)

    await ge._claim_next(db)

    assert order == ["execute", "execute", "commit"], (
        "the claim did not commit on its own before returning"
    )


# ───────────────────────── T-U7: Boundary 3 ─────────────────────────


@pytest.mark.asyncio
async def test_t_u7_failure_path_never_wedges_at_processing(monkeypatch):
    """T-U7 (Boundary 3) — on failure the row is re-issued to 'pending' (below
    max attempts), never left at 'processing', and last_error carries no email."""
    monkeypatch.setattr(ge.settings, "graph_erasure_max_attempts", 5, raising=False)
    db = _work_session(delete_raises=True)

    ok = await ge._process_claimed(db, _claimed(attempts=1))

    assert ok is False
    assert db.rollback.await_count == 1
    assert "erasure_status_update" in db.recorded, "no fresh status update was issued"
    # The status write happened AFTER the rollback (a same-transaction write
    # would have been discarded by it).
    values = db.execute.await_args.args[0].compile().params
    assert values["status"] == "pending"
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", values["last_error"] or "")


@pytest.mark.asyncio
async def test_t_u7b_exhausted_attempts_land_at_failed(monkeypatch):
    monkeypatch.setattr(ge.settings, "graph_erasure_max_attempts", 5, raising=False)
    db = _work_session(delete_raises=True)

    await ge._process_claimed(db, _claimed(attempts=5))

    assert db.execute.await_args.args[0].compile().params["status"] == "failed"


def test_t_u7c_sanitize_error_strips_emails_and_truncates():
    msg = f"insert failed for {EMAIL} " + "x" * 2000
    out = ge.sanitize_error(RuntimeError(msg))
    assert EMAIL not in out
    assert "[email-redacted]" in out
    assert len(out) <= 500


# ───────────────────────── T-U8 / T-U8b: Boundary 2 ─────────────────────────


@pytest.mark.asyncio
async def test_t_u8_boundary2_single_transaction_tombstone_first_happy_path():
    """T-U8 (Boundary 2, happy path) — CODE SHAPE, not Postgres atomicity.

    Asserts exactly one db.begin() scope; that its __aexit__ was awaited once
    with no exception; and that the tombstone INSERT was issued strictly before
    the graph DELETE with nothing between them. Deliberately does NOT assert on
    db.commit() — see this module's docstring.
    """
    db = _work_session()

    ok = await ge._process_claimed(db, _claimed())

    assert ok is True
    assert db.begin.call_count == 1, "the work is not in exactly one transaction"

    aexit = db.begin.return_value.__aexit__
    assert aexit.await_count == 1
    assert aexit.await_args.args[0] is None, "the happy path exited with an exception"

    inside = db.recorded[: db.recorded.index("erasure_status_update")]
    assert inside == ["tombstone_insert", "graph_delete", "identity_signals_delete"], (
        f"wrong Boundary-2 statement order / extra statement between: {inside}"
    )
    # H6 positive assertion: the identity_signals DELETE for the erased bidx was
    # issued inside the same Boundary-2 transaction (tombstone-first preserved).
    assert "identity_signals_delete" in inside


@pytest.mark.asyncio
async def test_t_u8b_boundary2_failure_path_propagates_and_recovers(monkeypatch):
    """T-U8b (Boundary 2, failure path) — the DELETE raises. The transaction
    scope must see the exception (so it rolls back both statements), the
    tombstone must still have been issued BEFORE the DELETE, and recovery must
    be rollback-then-fresh-UPDATE."""
    monkeypatch.setattr(ge.settings, "graph_erasure_max_attempts", 5, raising=False)
    db = _work_session(delete_raises=True)

    await ge._process_claimed(db, _claimed())

    assert db.begin.call_count == 1
    aexit = db.begin.return_value.__aexit__
    assert aexit.await_count == 1
    assert aexit.await_args.args[0] is RuntimeError, (
        "the exception did not propagate through the transaction scope"
    )

    assert db.recorded.index("tombstone_insert") < db.recorded.index("graph_delete")
    assert db.rollback.await_count == 1
    assert db.recorded[-1] == "erasure_status_update"


# ───────────────────────── T-U9 / T-U9b: queue health ─────────────────────────


def _health_session(counts: dict, oldest_pending=None, oldest_failed=None, flagged=0):
    from datetime import datetime, timedelta, timezone

    def _age(hours):
        if hours is None:
            return None
        return datetime.now(timezone.utc) - timedelta(hours=hours)

    db = MagicMock()
    grouped = MagicMock()
    grouped.all = MagicMock(return_value=list(counts.items()))
    db.execute = AsyncMock(
        side_effect=[
            grouped,
            _scalar_result(_age(oldest_pending)),
            _scalar_result(_age(oldest_failed)),
            _scalar_result(flagged),
        ]
    )
    return db


@pytest.mark.asyncio
async def test_t_u9_queue_health_warns_on_stale_pending_with_no_pii(monkeypatch):
    """T-U9 — a queue older than the alert threshold warns, reports a correct
    age, and carries no email / bidx / fingerprint."""
    monkeypatch.setattr(ge.settings, "graph_erasure_stale_alert_hours", 168)
    db = _health_session({"pending": 2}, oldest_pending=200)

    with structlog.testing.capture_logs() as logs:
        await ge._emit_queue_health(db)

    rec = next(r for r in logs if r["event"] == "erasure_queue_health")
    assert rec["log_level"] == "warning"
    assert rec["pending_count"] == 2
    assert 199 < rec["oldest_pending_age_hours"] < 201
    blob = str(rec)
    assert "@" not in blob and "fingerprint" not in blob and "bidx" not in blob


@pytest.mark.asyncio
async def test_t_u9_fresh_queue_stays_info(monkeypatch):
    monkeypatch.setattr(ge.settings, "graph_erasure_stale_alert_hours", 168)
    db = _health_session({"pending": 1, "done": 4}, oldest_pending=1)

    with structlog.testing.capture_logs() as logs:
        await ge._emit_queue_health(db)

    rec = next(r for r in logs if r["event"] == "erasure_queue_health")
    assert rec["log_level"] == "info"


@pytest.mark.asyncio
async def test_t_u9b_failed_rows_force_a_warning_even_when_queue_is_fresh(monkeypatch):
    """T-U9b — a permanently-failed erasure is the WORST silent outcome: the
    caller already received a 200. With pending/processing empty, the stale-age
    trigger structurally cannot fire, so failed_count must warn on its own."""
    monkeypatch.setattr(ge.settings, "graph_erasure_stale_alert_hours", 168)
    db = _health_session({"failed": 3, "done": 9}, oldest_pending=None, oldest_failed=50)

    with structlog.testing.capture_logs() as logs:
        await ge._emit_queue_health(db)

    rec = next(r for r in logs if r["event"] == "erasure_queue_health")
    assert rec["log_level"] == "warning", "a failed-only queue was reported at info"
    assert rec["failed_count"] == 3
    assert rec["oldest_pending_age_hours"] is None
    assert 49 < rec["oldest_failed_age_hours"] < 51
    blob = str(rec)
    assert "@" not in blob and "bidx" not in blob


# ───────────────────────── volume marker semantics ─────────────────────────


def test_volume_marker_is_never_a_filter_on_the_claim_path():
    """E-2 — scoped to the claim query ONLY. enqueue_erasure lives in the same
    module and MUST write throttle_flagged, so a whole-file grep would false-fail
    on correct code."""
    import ast
    import inspect

    def _executable_src(fn) -> str:
        """Source with the docstring and comments removed — the assertion is
        about what the code DOES, not about prose that names the column."""
        tree = ast.parse(inspect.getsource(fn).lstrip())
        node = tree.body[0]
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]
        return "\n".join(ast.unparse(n) for n in body)

    assert "throttle_flagged" not in _executable_src(ge._claim_next)
    assert "throttle_flagged" not in _executable_src(ge._process_claimed)

    # ...and the enqueue producer genuinely does write it.
    assert "throttle_flagged" in inspect.getsource(ge.enqueue_erasure)


# ──────────── SG-15: the enqueue tombstone is SAVEPOINT-scoped ────────────


class _Savepoint:
    """No-op async CM standing in for db.begin_nested().

    Same pattern as tests/unit/test_site_limit.py:100-114. It cannot model
    Postgres transaction abort — the unit lane has no transaction — so this gate
    proves the savepoint is ENTERED, not that the server honours it (SG-16).
    """

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _enqueue_session(tombstone_raises: bool = False) -> MagicMock:
    """Fake session covering enqueue_erasure's reads plus the tombstone write.

    The module-level `_scalar_result` helper is not reusable here:
    `_collect_match_keys` needs `.first()` and `.scalars().all()`, which it does
    not expose. A non-empty email list is essential — with an empty bidx,
    enqueue_erasure skips the tombstone branch entirely and never calls
    begin_nested, so the assertions below would go red rather than pass
    vacuously.
    """
    db = MagicMock()
    db.recorded: list[str] = []

    def _result(rows):
        r = MagicMock()
        r.first = MagicMock(return_value=("fp-abc", None))
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=rows)
        r.scalars = MagicMock(return_value=scalars)
        r.scalar = MagicMock(return_value=0)  # volume marker: not tripped
        return r

    async def _execute(stmt, *a, **kw):
        text = str(stmt).lower()
        if "suppression_list" in text:
            db.recorded.append("tombstone_insert")
            if tombstone_raises:
                raise RuntimeError("deadlock detected")
            return _result([])
        return _result([EMAIL])

    db.execute = AsyncMock(side_effect=_execute)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.begin_nested = MagicMock(return_value=_Savepoint())
    return db


@pytest.mark.asyncio
async def test_tombstone_write_failure_preserves_erasure_request():
    """SG-15 — a failing tombstone must not cost us the ErasureRequest.

    The `db.begin_nested` assertion is the load-bearing one: a bare try/except
    implementation never enters a savepoint, so it goes RED here. Without that
    assertion the gate would be vacuous — against a fake session a Python raise
    never aborts a real transaction, so "nothing escaped" passes either way.
    """
    db = _enqueue_session(tombstone_raises=True)

    row = await ge.enqueue_erasure(db, site_id="site_a", visitor_id="v-sg15")

    assert db.begin_nested.call_count == 1, (
        "the tombstone write was not SAVEPOINT-scoped — a bare try/except cannot "
        "un-abort a Postgres transaction, so the ErasureRequest would be lost"
    )
    assert "tombstone_insert" in db.recorded, "the tombstone statement never ran"
    assert db.add.call_count == 1, "the ErasureRequest was not added"
    assert db.commit.await_count == 1, (
        "db.commit() was not awaited after the tombstone failure — the queued "
        "request would never be persisted"
    )
    assert row is not None, "enqueue_erasure returned no row"
