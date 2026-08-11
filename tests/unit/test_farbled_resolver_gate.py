"""WS2 guards — the two resolver behavior changes for a farbled browser.

Guard 1 (`farbled_graph_write_guard_enabled`) blocks the CROSS-TENANT graph
write. Guard 2 (`farbled_fingerprint_gate_enabled`) skips Check 2 and Check 3.

Both are default-OFF and both are gated on `visitors.has_unstable_fingerprint`,
never on `do_not_resolve` — that is the GPC privacy flag and conflating the two
would be factually wrong and irreversible.

What must STAY ON for a flagged visitor is asserted here too: Check 0 (svid) and
Check 1 (captured email) still run and can still return a result, and the
no-prior-signal return is the SAME `None` that lets `resolve()` continue into the
paid IP-based waterfall — farbling does not touch an IP.
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import apps.api.main  # noqa: F401  — registers every ORM mapper (SocialAccount et al)
from apps.api.config import settings
from apps.api.services.identity_resolver import IdentityResolver

pytestmark = pytest.mark.unit

FP2 ="fp2-bbbbbbbbbbbbbbbb"


def _make_visitor(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "site_id": "test-site",
        "visitor_id": f"v-new-{uuid.uuid4().hex[:8]}",
        "ip_address": "203.0.113.42",
        "fingerprint": FP2,
        "fingerprint_v3": None,
        "server_visitor_id": None,
        "identity_status": "anonymous",
        "do_not_resolve": False,
        "has_unstable_fingerprint": False,
        "first_seen": datetime.now(timezone.utc),
        "last_seen": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_resolver():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    resolver = IdentityResolver(db=db, redis_client=MagicMock())
    resolver._check_beam_identity_network = AsyncMock(return_value=None)
    resolver._email_suppressed = AsyncMock(return_value=False)
    return resolver


def _match(email="cto@acme.com"):
    return SimpleNamespace(
        email=email,
        full_name="Real Person",
        city="Austin",
        region="TX",
        country="US",
        site_id="test-site",
        visitor_id="v-orig-aaaa1111",
    )


def _result(obj):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=obj)
    return r


def _params(stmt) -> set:
    """Flatten bound params to a hashable set (Check 1 binds a LIST via in_())."""
    flat: set = set()
    for v in stmt.compile().params.values():
        if isinstance(v, (list, tuple)):
            flat.update(x for x in v if isinstance(x, str))
        elif isinstance(v, str):
            flat.add(v)
    return flat


def _db_fp_hit(hit, seen=None):
    """Return `hit` for the fingerprint query, None for everything else."""

    async def _execute(stmt, *a, **kw):
        if FP2 in _params(stmt):
            if seen is not None:
                seen.append("fp")
            return _result(hit)
        return _result(None)

    return AsyncMock(side_effect=_execute)


def _db_email_hit(email):
    """Answer Check 1's captured-email query once; everything else misses.

    Only the FIRST non-fingerprint query gets the email — the follow-up
    cross-customer name lookup expects an ORM row, not a string.
    """
    served = {"done": False}

    async def _execute(stmt, *a, **kw):
        if FP2 in _params(stmt):
            return _result(None)
        if served["done"]:
            return _result(None)
        served["done"] = True
        return _result(email)

    return AsyncMock(side_effect=_execute)


# ─── Guard 2: flags OFF => behavior is unchanged ───


class TestGateOff:
    @pytest.mark.asyncio
    async def test_flagged_visitor_still_runs_check_2(self):
        """Default OFF must be byte-identical to pre-WS2 behavior."""
        resolver = _make_resolver()
        visitor = _make_visitor(has_unstable_fingerprint=True)
        seen: list[str] = []
        resolver.db.execute = _db_fp_hit(_match(), seen=seen)

        with patch.object(settings, "farbled_fingerprint_gate_enabled", False):
            result = await resolver._check_prior_signals(visitor)

        assert "fp" in seen, "Check 2 must still query with the gate off"
        assert result is not None

    @pytest.mark.asyncio
    async def test_unflagged_visitor_unaffected_when_gate_on(self):
        """The gate keys on the flag, not on the flag's existence."""
        resolver = _make_resolver()
        visitor = _make_visitor(has_unstable_fingerprint=False)
        seen: list[str] = []
        resolver.db.execute = _db_fp_hit(_match(), seen=seen)

        with patch.object(settings, "farbled_fingerprint_gate_enabled", True):
            result = await resolver._check_prior_signals(visitor)

        assert "fp" in seen
        assert result is not None

    @pytest.mark.asyncio
    async def test_visitor_missing_the_column_is_not_flagged(self):
        """getattr default False: an ORM object without the attr must not gate."""
        resolver = _make_resolver()
        visitor = _make_visitor()
        del visitor.has_unstable_fingerprint
        seen: list[str] = []
        resolver.db.execute = _db_fp_hit(_match(), seen=seen)

        with patch.object(settings, "farbled_fingerprint_gate_enabled", True):
            result = await resolver._check_prior_signals(visitor)

        assert "fp" in seen
        assert result is not None


# ─── Guard 2: gate ON => Check 2 AND Check 3 are both skipped ───


class TestGateOn:
    @pytest.mark.asyncio
    async def test_check_2_is_skipped(self):
        resolver = _make_resolver()
        visitor = _make_visitor(has_unstable_fingerprint=True)
        seen: list[str] = []
        # A match is waiting; the gate must refuse to look at it. That match is a
        # collision, not a recognition.
        resolver.db.execute = _db_fp_hit(_match(), seen=seen)

        with patch.object(settings, "farbled_fingerprint_gate_enabled", True):
            result = await resolver._check_prior_signals(visitor)

        assert seen == [], "the fingerprint query must never run"
        assert result is None

    @pytest.mark.asyncio
    async def test_check_3_is_skipped_by_the_same_return(self):
        """One `return None` covers both — Check 3 is the last statement."""
        resolver = _make_resolver()
        visitor = _make_visitor(has_unstable_fingerprint=True)
        resolver.db.execute = _db_fp_hit(None)

        with patch.object(settings, "farbled_fingerprint_gate_enabled", True):
            await resolver._check_prior_signals(visitor)

        resolver._check_beam_identity_network.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_1_captured_email_still_runs_and_can_win(self):
        """Farbling does not touch a typed-in address — Check 1 stays ON."""
        resolver = _make_resolver()
        visitor = _make_visitor(has_unstable_fingerprint=True)
        resolver.db.execute = _db_email_hit("typed@acme.com")
        resolver._save_identified = AsyncMock(return_value=({"email": "x"}, "form_capture"))

        with patch.object(settings, "farbled_fingerprint_gate_enabled", True):
            with patch.object(settings, "enrich_captured_email_pdl", False):
                result = await resolver._check_prior_signals(visitor)

        assert result is not None, "Check 1 must still be able to identify"
        resolver._save_identified.assert_awaited_once()
        saved = resolver._save_identified.await_args.args[1]
        assert saved["email"] == "typed@acme.com"

    @pytest.mark.asyncio
    async def test_gate_returns_the_ordinary_no_match_sentinel(self):
        """None is exactly what resolve() reads as "no prior signal".

        That is the shared path into the paid IP-based waterfall (Checks 4-7),
        which stays ON for a flagged visitor: farbling does not touch an IP.
        """
        resolver = _make_resolver()
        visitor = _make_visitor(has_unstable_fingerprint=True)
        resolver.db.execute = _db_fp_hit(None)

        with patch.object(settings, "farbled_fingerprint_gate_enabled", True):
            gated = await resolver._check_prior_signals(visitor)

        unflagged = _make_visitor(has_unstable_fingerprint=False)
        resolver2 = _make_resolver()
        resolver2.db.execute = _db_fp_hit(None)
        with patch.object(settings, "farbled_fingerprint_gate_enabled", True):
            no_match = await resolver2._check_prior_signals(unflagged)

        assert gated is no_match is None

    @pytest.mark.asyncio
    async def test_do_not_resolve_is_never_written(self):
        """Hard constraint: the GPC privacy flag is not ours to set."""
        resolver = _make_resolver()
        visitor = _make_visitor(has_unstable_fingerprint=True)
        resolver.db.execute = _db_fp_hit(None)

        with patch.object(settings, "farbled_fingerprint_gate_enabled", True):
            await resolver._check_prior_signals(visitor)

        assert visitor.do_not_resolve is False


# ─── Guard 1: the cross-tenant graph write ───


class TestGraphWriteGuard:
    @pytest.mark.asyncio
    async def test_flagged_visitor_writes_nothing_and_returns_false(self):
        """False (not raise/skip) so identity-coop never credits a phantom row."""
        resolver = _make_resolver()
        visitor = _make_visitor(has_unstable_fingerprint=True)

        with patch.object(settings, "farbled_graph_write_guard_enabled", True):
            wrote = await resolver._upsert_beam_identity(
                visitor, {"email": "cto@acme.com"}, "hunter"
            )

        assert wrote is False
        resolver.db.execute.assert_not_called()
        resolver.db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_guard_off_does_not_short_circuit(self):
        """Default OFF: a flagged visitor proceeds exactly as before."""
        resolver = _make_resolver()
        visitor = _make_visitor(has_unstable_fingerprint=True)

        with patch.object(settings, "farbled_graph_write_guard_enabled", False):
            await resolver._upsert_beam_identity(
                visitor, {"email": "cto@acme.com"}, "hunter"
            )

        assert resolver.db.execute.called, (
            "with the guard off the method must reach its normal write path"
        )

    @pytest.mark.asyncio
    async def test_unflagged_visitor_unaffected_when_guard_on(self):
        resolver = _make_resolver()
        visitor = _make_visitor(has_unstable_fingerprint=False)

        with patch.object(settings, "farbled_graph_write_guard_enabled", True):
            await resolver._upsert_beam_identity(
                visitor, {"email": "cto@acme.com"}, "hunter"
            )

        assert resolver.db.execute.called

    @pytest.mark.asyncio
    async def test_missing_fingerprint_still_short_circuits_first(self):
        """The pre-existing `not fp` guard keeps precedence."""
        resolver = _make_resolver()
        visitor = _make_visitor(fingerprint=None, has_unstable_fingerprint=True)

        with patch.object(settings, "farbled_graph_write_guard_enabled", False):
            wrote = await resolver._upsert_beam_identity(
                visitor, {"email": "cto@acme.com"}, "hunter"
            )

        assert wrote is False
