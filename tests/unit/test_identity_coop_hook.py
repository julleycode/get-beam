"""Identity co-op resolver hook — does the wiring actually EXECUTE? (M3, SG-2)

The co-op hook in `IdentityResolver._save_identified` was wired but never
executed by any test: `maybe_record_contribution` had zero proof it is ever
called. This file closes that hole for the hook's DECISION half.

Scope, stated honestly: this is the mock-only `-m unit` lane, so nothing here
proves a row is persisted, exercises the `uq_coop_accrued_site_email` partial
unique index, or proves `ON CONFLICT` semantics. That is the DB half, proven by
`test_end_to_end_accrual` in the integration lane (SG-3).

`_upsert_beam_identity` is patched rather than driven: its own return contract
(`-> bool`, True iff a row was really written) is already covered by
`tests/unit/test_graph_erasure.py` and the graph-erasure integration lane. What
is under test HERE is the two-line conditional that consumes it — namely that
the hook fires on (flag ON AND wrote_graph True) and on nothing else.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import apps.api.main  # noqa: F401 — registers every ORM mapper before use
from apps.api.services import identity_coop as coop
from apps.api.services.identity_resolver import IdentityResolver

pytestmark = pytest.mark.unit

EMAIL = "coop.hook@example.com"


def _save_session() -> MagicMock:
    """A session mock sufficient for the _save_identified insert path.

    The email-dedup select must return no canonical row, otherwise
    _save_identified takes the merge branch and returns before ever reaching the
    graph write and the hook.
    """
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    result.scalar = MagicMock(return_value=None)

    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.flush = AsyncMock()
    return db


def _visitor() -> SimpleNamespace:
    return SimpleNamespace(
        site_id="site_hook",
        visitor_id="visitor-hook-0001",
        fingerprint="fp-hook",
        fingerprint_v3=None,
        is_abuse_flagged=False,
        is_bot_suspect=False,
        do_not_resolve=False,
        identity_status="anonymous",
        canonical_visitor_id=None,
    )


async def _drive(monkeypatch, *, flag: bool, wrote_graph: bool) -> AsyncMock:
    """Run _save_identified end-to-end and return the hook spy."""
    # Deterministic: the real validator does an MX lookup over the network.
    from apps.api.services import email_validator

    monkeypatch.setattr(
        email_validator, "validate_email", AsyncMock(return_value=(True, ""))
    )
    monkeypatch.setattr(
        IdentityResolver,
        "_upsert_beam_identity",
        AsyncMock(return_value=wrote_graph),
    )
    monkeypatch.setattr(
        IdentityResolver, "_log_owned_resolution", AsyncMock(return_value=None)
    )
    # The hot-visitor ping is unrelated best-effort work on the same path.
    from apps.api.services import hot_alert

    monkeypatch.setattr(
        hot_alert, "maybe_send_hot_alert", AsyncMock(return_value=None)
    )

    spy = AsyncMock(return_value=None)
    monkeypatch.setattr(coop, "maybe_record_contribution", spy)

    from apps.api.services import identity_resolver as ir

    monkeypatch.setattr(ir.settings, "identity_coop_enabled", flag, raising=False)

    db = _save_session()
    resolver = IdentityResolver(db, redis_client=None)
    await resolver._save_identified(
        _visitor(), {"email": EMAIL, "full_name": "Coop Hook"}, "pdl"
    )
    return spy


@pytest.mark.asyncio
async def test_hook_fires_when_flag_on_and_graph_write_happened(monkeypatch):
    """SG-2 (a) — flag ON + wrote_graph True ⇒ called with (db, visitor, data, provider)."""
    spy = await _drive(monkeypatch, flag=True, wrote_graph=True)

    assert spy.await_count == 1, "the co-op hook never executed"
    args = spy.await_args.args
    assert len(args) == 4, f"unexpected hook signature: {args!r}"
    db_arg, visitor_arg, data_arg, provider_arg = args
    assert visitor_arg.site_id == "site_hook"
    assert data_arg["email"] == EMAIL
    assert provider_arg == "pdl"
    assert db_arg is not None


@pytest.mark.asyncio
async def test_hook_does_not_fire_when_graph_write_did_not_happen(monkeypatch):
    """SG-2 (b) — no graph row written ⇒ no credit, even with the flag ON.

    This is the invariant that stops credit being minted for a write that never
    landed (a farbled fingerprint, an erased identity, a duplicate no-op).
    """
    spy = await _drive(monkeypatch, flag=True, wrote_graph=False)

    assert spy.await_count == 0, "credited a graph write that never happened"


@pytest.mark.asyncio
async def test_hook_does_not_fire_when_global_flag_off(monkeypatch):
    """SG-2 (c) — flag OFF ⇒ never called, even when the graph write succeeded."""
    spy = await _drive(monkeypatch, flag=False, wrote_graph=True)

    assert spy.await_count == 0, "the co-op hook ran with the deployment flag OFF"
