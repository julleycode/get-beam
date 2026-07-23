"""Owned-data-layer Phase 1: durable company_graph write-through + read-first.

Pure-logic unit coverage (mocked DB, no Postgres):
- write-through upsert-on-conflict issues an execute + commit
- staleness window math + read-time re-validation flag
- flag-off is a byte-identical no-op (no graph read/write)
- _graph_node_by_email returns full profile (city/region/country), not name-only
"""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.services import company_resolver as cr

pytestmark = pytest.mark.unit


def _result_returning(obj):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=obj)
    return r


class TestStalenessWindow:
    def test_fresh_row_not_stale(self):
        recent = datetime.now(timezone.utc) - timedelta(days=1)
        assert cr._company_graph_is_stale(recent, 75) is False

    def test_old_row_is_stale(self):
        old = datetime.now(timezone.utc) - timedelta(days=100)
        assert cr._company_graph_is_stale(old, 75) is True

    def test_missing_last_verified_is_stale(self):
        assert cr._company_graph_is_stale(None, 75) is True

    def test_naive_timestamp_tolerated(self):
        naive_old = datetime.utcnow() - timedelta(days=100)
        assert cr._company_graph_is_stale(naive_old, 75) is True

    @pytest.mark.asyncio
    async def test_read_flags_revalidation_for_stale_row(self):
        db = AsyncMock()
        old = datetime.now(timezone.utc) - timedelta(days=200)
        node = SimpleNamespace(domain="acme.com", last_verified=old, confidence=0.5)
        db.execute = AsyncMock(return_value=_result_returning(node))
        with patch.object(cr, "settings") as s:
            s.company_graph_staleness_days = 75
            out = await cr._read_company_graph(db, "9.9.9.9")
        assert out is not None
        assert out.node is node
        assert out.needs_revalidation is True

    @pytest.mark.asyncio
    async def test_read_no_revalidation_for_fresh_row(self):
        db = AsyncMock()
        recent = datetime.now(timezone.utc) - timedelta(days=2)
        node = SimpleNamespace(domain="acme.com", last_verified=recent, confidence=0.5)
        db.execute = AsyncMock(return_value=_result_returning(node))
        with patch.object(cr, "settings") as s:
            s.company_graph_staleness_days = 75
            out = await cr._read_company_graph(db, "9.9.9.9")
        assert out.needs_revalidation is False

    @pytest.mark.asyncio
    async def test_read_none_when_no_row(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result_returning(None))
        assert await cr._read_company_graph(db, "9.9.9.9") is None


class TestWriteThroughUpsert:
    @pytest.mark.asyncio
    async def test_upsert_on_conflict_executes_and_commits(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        await cr._write_through_company_graph(
            db, "203.0.113.7", "acme.com", None, "rdns", 0.5
        )
        db.execute.assert_awaited_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_ip_is_noop(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        await cr._write_through_company_graph(db, "", "acme.com", None, "rdns", 0.5)
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_write_failure_rolls_back_and_swallows(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=RuntimeError("boom"))
        db.rollback = AsyncMock()
        # Must not raise — best-effort.
        await cr._write_through_company_graph(
            db, "203.0.113.7", "acme.com", None, "rdns", 0.5
        )
        db.rollback.assert_awaited_once()


class TestFlagGating:
    @pytest.mark.asyncio
    async def test_flag_off_is_noop(self):
        """flag off + db provided → no graph read, no write-through; behaves
        exactly like the Redis-only path."""
        db = AsyncMock()
        db.execute = AsyncMock()
        with patch.object(cr, "settings") as s, patch.object(
            cr, "resolve_company_from_ip", new=AsyncMock(return_value=None)
        ):
            s.company_graph_enabled = False
            out = await cr.resolve_company_cached("1.2.3.4", db=db)
        assert out is None
        # No company_graph read or write touched the db.
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_flag_on_reads_fresh_row_and_skips_rdns(self):
        db = AsyncMock()
        recent = datetime.now(timezone.utc) - timedelta(days=1)
        node = SimpleNamespace(domain="fresh.com", last_verified=recent, confidence=0.9)
        db.execute = AsyncMock(return_value=_result_returning(node))
        rdns = AsyncMock(return_value="should-not-be-called.com")
        with patch.object(cr, "settings") as s, patch.object(
            cr, "resolve_company_from_ip", new=rdns
        ):
            s.company_graph_enabled = True
            s.company_graph_staleness_days = 75
            out = await cr.resolve_company_cached("1.2.3.4", db=db)
        assert out == "fresh.com"
        rdns.assert_not_awaited()  # fresh graph row short-circuited rDNS

    @pytest.mark.asyncio
    async def test_flag_on_writes_through_on_rdns_hit(self):
        """flag on, no graph row, redis unavailable → resolve rDNS then
        write-through (execute + commit for the upsert)."""
        db = AsyncMock()
        # First execute = graph read (no row); write-through does execute+commit.
        db.execute = AsyncMock(return_value=_result_returning(None))
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        with patch.object(cr, "settings") as s, patch.object(
            cr, "resolve_company_from_ip", new=AsyncMock(return_value="acme.com")
        ):
            s.company_graph_enabled = True
            s.company_graph_staleness_days = 75
            out = await cr.resolve_company_cached("5.6.7.8", db=db)
        assert out == "acme.com"
        db.commit.assert_awaited()  # write-through committed


class TestGraphNodeByEmailFullProfile:
    """AC3: _graph_node_by_email now surfaces full profile — the caller passes
    city/region/country through to the identification, not just the name."""

    @pytest.mark.asyncio
    async def test_caller_inherits_full_profile(self):
        from apps.api.services.identity_resolver import IdentityResolver

        db = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        resolver = IdentityResolver(db=db, redis_client=MagicMock())

        visitor = SimpleNamespace(
            id=uuid.uuid4(),
            site_id="s",
            visitor_id="v-1",
            ip_address="203.0.113.9",
            fingerprint=None,
            server_visitor_id=None,
        )
        # Check-1 VisitorEmail lookup returns a captured email.
        resolver.db.execute = AsyncMock(return_value=_result_returning("owner@acme.com"))
        graph_node = SimpleNamespace(
            full_name="Jane Doe", city="Austin", region="TX", country="US",
            confidence_score=0.9,
        )
        resolver._graph_node_by_email = AsyncMock(return_value=graph_node)
        resolver._save_identified = AsyncMock(return_value="SAVED")
        with patch("apps.api.services.identity_resolver.settings") as s:
            s.enrich_captured_email_pdl = False
            result = await resolver._check_prior_signals(visitor)

        assert result == "SAVED"
        data = resolver._save_identified.call_args[0][1]
        assert data["full_name"] == "Jane Doe"
        assert data["city"] == "Austin"
        assert data["region"] == "TX"
        assert data["country"] == "US"
        assert data["confidence_score"] == 0.85
