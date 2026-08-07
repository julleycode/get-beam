"""Identity co-op Phase 1 — service-logic and signature gates (no Postgres).

identity-coop Phase 1 (visitors-identity, 07-08-26), Step F unit legs.

What this lane proves, and what it deliberately does NOT:

* PROVES the decisions ``record_contribution`` owns — which ``excluded_reason`` it
  stamps, whether it writes a ledger row at all, that a blocked graph write
  produces nothing, and that ``_upsert_beam_identity``'s new ``bool`` return is
  correct on every path.
* Does NOT prove the DB-level enforcement of the two uniqueness rules. A partial
  unique index and ``ON CONFLICT`` are Postgres semantics that a fake session
  cannot simulate honestly. Those are proven by the Hybrid gates (index presence +
  a real duplicate ``ACCRUE`` raising ``IntegrityError`` against a disposable
  Postgres) and by the integration lane. The split is deliberate: what is asserted
  here is what this layer actually decides.

The fake session below returns queued ``scalar_one_or_none`` values so a
same-day-duplicate (conflict ⇒ no id returned) and an accrual conflict
(``IntegrityError`` on the accrued UPDATE) can both be driven without a DB, while
still executing the REAL service code path end to end.
"""

import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError

import apps.api.main  # noqa: F401 — registers ALL ORM models (mapper config)
from apps.api.config import settings
from apps.api.models.identity_coop import (
    ContributionConsentAcceptance,
    ContributionEvent,
    CreditLedgerEntry,
)
from apps.api.models.site import Site
from apps.api.services import identity_coop as coop
from apps.api.services.identity_resolver import IdentityResolver

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fake AsyncSession — executes the real service code, records what it was asked
# to write. Only the surface identity_coop actually touches is implemented.
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value


class _NestedCM:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Minimal AsyncSession stand-in.

    ``event_ids`` is the queue of values returned by the event-insert
    ``RETURNING id``: a UUID means "inserted", ``None`` means "ON CONFLICT DO
    NOTHING fired" (the same-day duplicate). ``raise_on_accrue`` simulates the
    ``uq_coop_accrued_site_email`` partial index rejecting a second credit.
    """

    def __init__(self, event_ids=None, raise_on_accrue=False):
        self._event_ids = list(event_ids or [uuid.uuid4()])
        self.raise_on_accrue = raise_on_accrue
        self.added: list = []
        self.updates: list[dict] = []
        self.commits = 0
        self.rollbacks = 0
        self._in_nested = False

    async def execute(self, stmt):
        compiled = str(stmt)
        if "INSERT INTO identity_contribution_events" in compiled:
            return _Result(self._event_ids.pop(0) if self._event_ids else None)
        if "UPDATE identity_contribution_events" in compiled:
            params = dict(getattr(stmt, "_values", {}) or {})
            resolved = {
                k.name if hasattr(k, "name") else str(k): getattr(v, "value", v)
                for k, v in params.items()
            }
            if self._in_nested and self.raise_on_accrue:
                raise IntegrityError("dup accrue", None, Exception("dup"))
            self.updates.append(resolved)
            return _Result(None)
        return _Result(None)

    def begin_nested(self):
        session = self

        class _CM(_NestedCM):
            async def __aenter__(self_inner):
                session._in_nested = True
                return self_inner

            async def __aexit__(self_inner, *exc):
                session._in_nested = False
                return False

        return _CM()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    @property
    def ledger_rows(self):
        return [o for o in self.added if isinstance(o, CreditLedgerEntry)]

    @property
    def last_excluded_reason(self):
        for u in reversed(self.updates):
            if "excluded_reason" in u:
                return u["excluded_reason"]
        return None


def _visitor(**kw):
    base = dict(
        visitor_id="v" * 12,
        site_id="site_coop_a",
        fingerprint="fp2_coop",
        fingerprint_v3=None,
        do_not_resolve=False,
        is_abuse_flagged=False,
        is_bot_suspect=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


async def _record(session, **overrides):
    kwargs = dict(
        site_id="site_coop_a",
        email_bidx="a" * 64,
        source_provider="pdl",
        is_abuse_flagged=False,
        is_bot_suspect=False,
        contributed_on=date(2026, 8, 7),
    )
    kwargs.update(overrides)
    await coop.record_contribution(session, **kwargs)


# ---------------------------------------------------------------------------
# B2 — every Phase 1 setting defaults OFF / inert (FIVE settings, not four)
# ---------------------------------------------------------------------------


def test_all_five_coop_settings_default_off_or_inert():
    """A shipped default must never opt a site into the co-op or mint credit."""
    assert settings.identity_coop_enabled is False
    assert settings.coop_credit_per_contribution == 1
    assert settings.coop_credit_expiry_days == 90
    assert settings.coop_credit_hold_hours == 24
    # Pinned policy digest: 64-char lowercase hex, never a free-form label.
    tv = settings.coop_terms_version
    assert len(tv) == 64
    assert all(c in "0123456789abcdef" for c in tv)


def test_site_contribution_enabled_defaults_off():
    """The per-site half of the gate is OFF for a freshly constructed Site."""
    site = Site(site_id="s1", user_id=uuid.uuid4(), name="n", url="https://x.example")
    assert bool(getattr(site, "contribution_enabled", False)) is False
    col = Site.__table__.c.contribution_enabled
    assert col.nullable is False
    assert "false" in str(col.server_default.arg).lower()


# ---------------------------------------------------------------------------
# F3 (AC-3) — merge-aware counting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merged_duplicate_counts_once():
    """Same email, two visitor_ids, same day ⇒ ONE event, ONE credit.

    The second call's event insert hits uq_coop_contrib_site_email_day and returns
    no id; the service must treat that as "already counted" and accrue nothing —
    NOT fall through and mint a second credit for the same day.
    """
    session = FakeSession(event_ids=[uuid.uuid4(), None])
    await _record(session)  # first visitor_id
    await _record(session)  # second visitor_id, same email + day
    assert len(session.ledger_rows) == 1


# ---------------------------------------------------------------------------
# F5/F11 (AC-9, D-C) — the fraud gate covers BOTH flags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flag", ["is_abuse_flagged", "is_bot_suspect"], ids=["abuse", "bot_suspect"]
)
async def test_fraud_flagged_visitor_earns_no_credit(flag):
    """Either flag ⇒ event still recorded (audit), zero ledger rows (no credit).

    Only ACCRUAL is gated, never the audit trail — an excluded contribution must
    stay visible or the exclusion itself becomes unauditable.
    """
    session = FakeSession()
    await _record(session, **{flag: True})
    assert session.ledger_rows == []
    assert session.last_excluded_reason == "fraud_flagged"


@pytest.mark.asyncio
async def test_bot_suspect_visitor_earns_no_credit():
    """F11 — named leg for the is_bot_suspect half of AC-9 (D-C widening)."""
    session = FakeSession()
    await _record(session, is_bot_suspect=True)
    assert session.ledger_rows == []
    assert session.last_excluded_reason == "fraud_flagged"


# ---------------------------------------------------------------------------
# F12 (AC-5 / D-E) — one credit per identity for all time, not one per day
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_day_resolve_accrues_no_second_credit():
    """A later-day repeat resolve records an event but mints NO second credit.

    Day 1 accrues. Day 2 passes the per-day audit key (different date ⇒ a new
    event row) but the accrued-UPDATE hits uq_coop_accrued_site_email; the service
    must stamp 'duplicate' and write no ledger row. Without this, the same person
    would mint a fresh credit every calendar day forever — credit inflation on the
    money surface.
    """
    day1 = FakeSession()
    await _record(day1, contributed_on=date(2026, 8, 7))
    assert len(day1.ledger_rows) == 1

    day2 = FakeSession(raise_on_accrue=True)
    await _record(day2, contributed_on=date(2026, 8, 8))
    assert day2.ledger_rows == []
    assert day2.last_excluded_reason == "duplicate"


# ---------------------------------------------------------------------------
# F4 shape (AC-5) — the ACCRUE lot carries hold + expiry + provenance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qualifying_contribution_builds_a_complete_accrue_lot():
    session = FakeSession()
    await _record(session)
    (row,) = session.ledger_rows
    assert row.entry_type == "ACCRUE"
    assert row.amount == settings.coop_credit_per_contribution > 0
    assert row.reason == "contribution"
    assert row.site_id == "site_coop_a"
    assert row.contribution_event_id is not None
    # An ACCRUE row is its own lot; Phase 2's SPEND/EXPIRE rows point at it.
    assert row.lot_id == row.id
    # Hold before spendable, expiry after — never the other way round.
    assert row.spendable_at < row.expires_at
    assert (
        row.expires_at - row.spendable_at
        == timedelta(days=settings.coop_credit_expiry_days)
        - timedelta(hours=settings.coop_credit_hold_hours)
    )


# ---------------------------------------------------------------------------
# F9 / F10 (D-A, D-B) — a blocked graph write leaves NOTHING behind
# ---------------------------------------------------------------------------


def _resolver(db):
    return IdentityResolver(db, redis_client=object())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "visitor_kw,data,blocked_by",
    [
        (dict(fingerprint=None), {"email": "a@b.com"}, "missing fingerprint"),
        (dict(), {}, "missing email"),
        (dict(do_not_resolve=True), {"email": "a@b.com"}, "do_not_resolve"),
    ],
    ids=["no_fingerprint", "no_email", "do_not_resolve"],
)
async def test_blocked_graph_write_accrues_nothing(
    visitor_kw, data, blocked_by, monkeypatch
):
    """No graph write ⇒ no event row and no ledger row, per no-op path.

    This is the hole that would otherwise let a credit be minted for a write that
    never happened. The gate is the bool return: the hook is unreachable when
    _upsert_beam_identity returns False.
    """
    session = FakeSession()
    resolver = _resolver(session)
    monkeypatch.setattr(
        coop, "record_contribution", AsyncMock(side_effect=AssertionError("accrued!"))
    )
    monkeypatch.setattr(
        "apps.api.services.suppression.is_email_suppressed_any", AsyncMock(return_value=False)
    )
    wrote = await resolver._upsert_beam_identity(_visitor(**visitor_kw), data, "pdl")
    assert wrote is False, f"{blocked_by} must not report a graph write"
    assert session.added == []
    assert session.updates == []


@pytest.mark.asyncio
async def test_erased_person_leaves_no_new_bidx_row(monkeypatch):
    """D-B privacy invariant: an erasure tombstone ⇒ no email_bidx row is created.

    This is what makes the co-op tables' absence from ERASURE_TARGETS harmless:
    a row for an erased person can never be created AFTER their erasure, so
    SPEC A's sweep has nothing here it needs to reach.
    """
    session = FakeSession()
    resolver = _resolver(session)
    monkeypatch.setattr(
        "apps.api.services.suppression.is_email_suppressed_any",
        AsyncMock(return_value=True),  # tombstoned under erased/do_not_process/all
    )
    monkeypatch.setattr(
        coop, "record_contribution", AsyncMock(side_effect=AssertionError("wrote row!"))
    )
    wrote = await resolver._upsert_beam_identity(
        _visitor(), {"email": "erased@example.com"}, "pdl"
    )
    assert wrote is False
    assert session.added == []
    assert not any("email_bidx" in str(u) for u in session.updates)


# ---------------------------------------------------------------------------
# F14 (D-A) — the bool return is correct AND existing callers are unaffected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_returns_bool_and_existing_callers_unaffected(monkeypatch):
    """True only on a real committed write; False on every guard path.

    Second half of the D-A compatibility claim: a test that replaces
    _upsert_beam_identity with AsyncMock() gets a TRUTHY Mock, which would satisfy
    `wrote_graph` — the hook still stays inert because identity_coop_enabled
    defaults False. That is why no existing test needed rewriting.
    """
    monkeypatch.setattr(
        "apps.api.services.suppression.is_email_suppressed_any", AsyncMock(return_value=False)
    )
    ok = FakeSession()
    resolver = _resolver(ok)
    assert (
        await resolver._upsert_beam_identity(
            _visitor(), {"email": "new@example.com"}, "pdl"
        )
        is True
    )

    # A failing write must report False, never a truthy/None ambiguity.
    class _Boom(FakeSession):
        async def execute(self, stmt):
            raise RuntimeError("db down")

    assert (
        await _resolver(_Boom())._upsert_beam_identity(
            _visitor(), {"email": "new@example.com"}, "pdl"
        )
        is False
    )

    # Truthy AsyncMock + flag OFF ⇒ hook inert (no accrual attempted).
    assert settings.identity_coop_enabled is False
    accrual = AsyncMock(side_effect=AssertionError("hook fired while flag OFF"))
    monkeypatch.setattr(coop, "maybe_record_contribution", accrual)
    r = _resolver(FakeSession())
    r._upsert_beam_identity = AsyncMock(return_value=True)
    assert (await r._upsert_beam_identity(_visitor(), {}, "pdl")) is True
    accrual.assert_not_awaited()


# ---------------------------------------------------------------------------
# F7 (AC-12) — no retro-credit for pre-program graph rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grandfathered_rows_contribute_zero():
    """A pre-existing graph row with no contribution event contributes 0.

    Balance is derived from the LEDGER, never from beam_identity_graph, so a graph
    row that predates the co-op can never be retro-credited: there is no ledger
    row for it and nothing in this phase creates one.
    """
    empty = FakeSession()
    empty._event_ids = []

    class _ZeroSum(FakeSession):
        async def execute(self, stmt):
            return _Result(0)

    assert await coop.spendable_balance(_ZeroSum(), "site_with_old_graph_rows") == 0


# ---------------------------------------------------------------------------
# F8 — a co-op failure never breaks identification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coop_failure_does_not_break_identification():
    """record_contribution swallows everything; the caller never sees a raise."""

    class _Broken(FakeSession):
        async def execute(self, stmt):
            raise RuntimeError("ledger table missing")

    session = _Broken()
    await _record(session)  # must not raise
    assert session.ledger_rows == []
    assert session.rollbacks >= 1


@pytest.mark.asyncio
async def test_maybe_record_contribution_is_best_effort(monkeypatch):
    """The resolver-facing entrypoint also never raises into the resolver."""

    class _Broken(FakeSession):
        async def execute(self, stmt):
            raise RuntimeError("site lookup failed")

    await coop.maybe_record_contribution(
        _Broken(), _visitor(), {"email": "a@b.com"}, "pdl"
    )


@pytest.mark.asyncio
async def test_maybe_record_contribution_respects_per_site_flag(monkeypatch):
    """Global flag ON but site flag OFF ⇒ nothing recorded (AC-1, per-site half)."""

    class _FlagOff(FakeSession):
        async def execute(self, stmt):
            return _Result(False)

    called = AsyncMock()
    monkeypatch.setattr(coop, "record_contribution", called)
    await coop.maybe_record_contribution(
        _FlagOff(), _visitor(), {"email": "a@b.com"}, "pdl"
    )
    called.assert_not_awaited()


# ---------------------------------------------------------------------------
# Structural guards — the invariants that must fail loudly if reworded away
# ---------------------------------------------------------------------------


def test_coop_module_imports_no_suppression_scope():
    """D-B: the single source of truth for suppression stays in the resolver.

    If this module ever re-lists a scope literal, the erased-only-narrowness bug
    class reopens. A tripwire, not a style check.

    AST-based on purpose: a plain substring scan would trip on the module's own
    docstring, which legitimately *names* these symbols to explain why it must not
    import them. Only real imports and real string literals count.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path("apps/api/services/identity_coop.py").read_text())

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)

    assert not any("suppression" in m for m in imported), imported
    assert "SuppressionEntry" not in imported
    assert "GRAPH_WRITE_BLOCKING_SCOPES" not in imported

    # No suppression-scope literal may be re-listed in executable code.
    docstrings = {
        ast.get_docstring(n)
        for n in ast.walk(tree)
        if isinstance(
            n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        )
    }
    literals = {
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and n.value not in docstrings
    }
    assert not {"erased", "do_not_process", "all"} & literals, literals


def test_consent_trail_has_no_update_path():
    """AC-10: acceptances are append-only — no update/delete in the service."""
    from pathlib import Path

    src = Path("apps/api/services/identity_coop.py").read_text()
    accept = src.split("async def record_consent_acceptance")[1]
    assert ".update(" not in accept
    assert "delete(" not in accept
    assert ContributionConsentAcceptance.__tablename__ == (
        "identity_contribution_consent_acceptances"
    )


def test_ledger_has_no_user_id_column():
    """D-D: site_id is the attribution unit; user_id is derived, never stored."""
    assert "user_id" not in CreditLedgerEntry.__table__.c
    assert "site_id" in CreditLedgerEntry.__table__.c


def test_contribution_event_carries_blind_index_only():
    """No plaintext or ciphertext email may exist on the co-op event table."""
    cols = set(ContributionEvent.__table__.c.keys())
    assert "email_bidx" in cols
    assert not {"email", "email_ciphertext"} & cols
