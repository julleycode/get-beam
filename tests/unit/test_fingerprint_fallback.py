"""WS3: Check 2 fp3 -> fp2 candidate loop (the `fp_col` either/or bug).

Check 2 (per-site fingerprint match) used to SELECT one column — fingerprint_v3
when the visitor carried an fp3, else fingerprint (fp2). Selecting a column is
not a fallback: one query ran against one column, so an fp3-carrying visitor
could never match the fp2-only rows (measured fp3 coverage 34%, so ~66% of
stored rows were unreachable).

The fix runs a v3-then-v2 candidate loop, shaped like Check 3. The fp2 SECOND
pass is gated on settings.fingerprint_v2_fallback_enabled so the flag-OFF path
stays byte-identical to the historical behavior.
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.config import settings
from apps.api.services.identity_resolver import IdentityResolver

pytestmark = pytest.mark.unit

FP3 ="fp3-aaaaaaaaaaaaaaaa"
FP2 = "fp2-bbbbbbbbbbbbbbbb"


def _make_visitor(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "site_id": "test-site",
        "visitor_id": f"v-new-{uuid.uuid4().hex[:8]}",
        "ip_address": "203.0.113.42",
        "fingerprint": None,
        "fingerprint_v3": None,
        "server_visitor_id": None,
        "identity_status": "anonymous",
        "do_not_resolve": False,
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
    # Check 3 is a separate code path; keep it out of these assertions.
    resolver._check_beam_identity_network = AsyncMock(return_value=None)
    resolver._email_suppressed = AsyncMock(return_value=False)
    return resolver


def _match(email="cto@acme.com", visitor_id="v-orig-aaaa1111"):
    return SimpleNamespace(
        email=email,
        full_name="Real Person",
        city="Austin",
        region="TX",
        country="US",
        site_id="test-site",
        visitor_id=visitor_id,
    )


def _result(obj):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=obj)
    return r


def _db_by_fingerprint(*, v3_hit=None, v2_hit=None, seen=None):
    """Route each db.execute by which fingerprint value the query binds.

    Check 1's captured-email query binds neither, so it returns None.
    """

    async def _execute(stmt, *a, **kw):
        params = set(stmt.compile().params.values())
        if FP3 in params:
            if seen is not None:
                seen.append("v3")
            return _result(v3_hit)
        if FP2 in params:
            if seen is not None:
                seen.append("v2")
            return _result(v2_hit)
        return _result(None)

    return AsyncMock(side_effect=_execute)


class TestFlagOff:
    @pytest.mark.asyncio
    async def test_fp3_carrier_does_not_reach_fp2_rows(self):
        """Pins today's behavior exactly: no v2 pass for an fp3 carrier."""
        resolver = _make_resolver()
        visitor = _make_visitor(fingerprint=FP2, fingerprint_v3=FP3)
        seen: list[str] = []
        resolver.db.execute = _db_by_fingerprint(v3_hit=None, v2_hit=_match(), seen=seen)
        resolver._save_identified = AsyncMock()

        with patch.object(settings, "fingerprint_v2_fallback_enabled", False):
            result = await resolver._check_prior_signals(visitor)

        assert result is None
        assert seen == ["v3"]
        resolver._save_identified.assert_not_called()

    @pytest.mark.asyncio
    async def test_fp2_only_visitor_still_searches_v2(self):
        resolver = _make_resolver()
        visitor = _make_visitor(fingerprint=FP2, fingerprint_v3=None)
        seen: list[str] = []
        resolver.db.execute = _db_by_fingerprint(v2_hit=_match(), seen=seen)
        sentinel = object()
        resolver._save_identified = AsyncMock(return_value=sentinel)

        with patch.object(settings, "fingerprint_v2_fallback_enabled", False):
            result = await resolver._check_prior_signals(visitor)

        assert result is sentinel
        assert seen == ["v2"]
        assert resolver._save_identified.call_args[0][1]["confidence_score"] == 0.75


class TestFlagOn:
    @pytest.mark.asyncio
    async def test_fp3_carrier_falls_back_to_fp2_at_075(self):
        resolver = _make_resolver()
        visitor = _make_visitor(fingerprint=FP2, fingerprint_v3=FP3)
        seen: list[str] = []
        resolver.db.execute = _db_by_fingerprint(v3_hit=None, v2_hit=_match(), seen=seen)
        sentinel = object()
        resolver._save_identified = AsyncMock(return_value=sentinel)

        with patch.object(settings, "fingerprint_v2_fallback_enabled", True):
            result = await resolver._check_prior_signals(visitor)

        assert result is sentinel
        assert seen == ["v3", "v2"]
        args = resolver._save_identified.call_args[0]
        assert args[1]["email"] == "cto@acme.com"
        assert args[1]["confidence_score"] == 0.75
        assert args[2] == "fingerprint_match"

    @pytest.mark.asyncio
    async def test_v3_wins_and_v2_pass_never_runs(self):
        resolver = _make_resolver()
        visitor = _make_visitor(fingerprint=FP2, fingerprint_v3=FP3)
        seen: list[str] = []
        resolver.db.execute = _db_by_fingerprint(
            v3_hit=_match(email="v3@acme.com"),
            v2_hit=_match(email="v2@acme.com"),
            seen=seen,
        )
        sentinel = object()
        resolver._save_identified = AsyncMock(return_value=sentinel)

        with patch.object(settings, "fingerprint_v2_fallback_enabled", True):
            result = await resolver._check_prior_signals(visitor)

        assert result is sentinel
        assert seen == ["v3"]
        args = resolver._save_identified.call_args[0]
        assert args[1]["email"] == "v3@acme.com"
        assert args[1]["confidence_score"] == 0.80

    @pytest.mark.asyncio
    async def test_candidate_tier_origin_guard_survives_the_loop(self):
        """identity_status == 'identified' stays in the WHERE of every pass.

        A candidate-tier origin yields no row, so the query returns None on both
        passes and nothing is inherited.
        """
        resolver = _make_resolver()
        visitor = _make_visitor(fingerprint=FP2, fingerprint_v3=FP3)
        seen: list[str] = []
        resolver.db.execute = _db_by_fingerprint(v3_hit=None, v2_hit=None, seen=seen)
        resolver._save_identified = AsyncMock()
        captured: list[str] = []

        async def _execute(stmt, *a, **kw):
            captured.append(str(stmt))
            params = set(stmt.compile().params.values())
            if FP3 in params:
                seen.append("v3")
            elif FP2 in params:
                seen.append("v2")
            return _result(None)

        resolver.db.execute = AsyncMock(side_effect=_execute)

        with patch.object(settings, "fingerprint_v2_fallback_enabled", True):
            result = await resolver._check_prior_signals(visitor)

        assert result is None
        assert seen == ["v3", "v2"]
        fp_queries = [s for s in captured if "identified_visitors" in s]
        assert len(fp_queries) == 2
        for sql in fp_queries:
            assert "visitors.identity_status" in sql
        resolver._save_identified.assert_not_called()

    @pytest.mark.asyncio
    async def test_suppressed_fp2_match_is_not_inherited(self):
        resolver = _make_resolver()
        visitor = _make_visitor(fingerprint=FP2, fingerprint_v3=FP3)
        seen: list[str] = []
        resolver.db.execute = _db_by_fingerprint(v3_hit=None, v2_hit=_match(), seen=seen)
        resolver._email_suppressed = AsyncMock(return_value=True)
        resolver._save_identified = AsyncMock()

        with patch.object(settings, "fingerprint_v2_fallback_enabled", True):
            result = await resolver._check_prior_signals(visitor)

        assert result is None
        assert seen == ["v3", "v2"]
        resolver._email_suppressed.assert_awaited_once_with("cto@acme.com")
        resolver._save_identified.assert_not_called()

    @pytest.mark.asyncio
    async def test_suppression_fires_per_candidate_not_once_for_the_loop(self):
        """A suppressed v3 hit must not abort the v2 pass."""
        resolver = _make_resolver()
        visitor = _make_visitor(fingerprint=FP2, fingerprint_v3=FP3)
        seen: list[str] = []
        resolver.db.execute = _db_by_fingerprint(
            v3_hit=_match(email="suppressed@acme.com"),
            v2_hit=_match(email="clean@acme.com"),
            seen=seen,
        )
        resolver._email_suppressed = AsyncMock(
            side_effect=lambda email: email == "suppressed@acme.com"
        )
        sentinel = object()
        resolver._save_identified = AsyncMock(return_value=sentinel)

        with patch.object(settings, "fingerprint_v2_fallback_enabled", True):
            result = await resolver._check_prior_signals(visitor)

        assert result is sentinel
        assert seen == ["v3", "v2"]
        assert resolver._email_suppressed.await_count == 2
        args = resolver._save_identified.call_args[0]
        assert args[1]["email"] == "clean@acme.com"
        assert args[1]["confidence_score"] == 0.75
