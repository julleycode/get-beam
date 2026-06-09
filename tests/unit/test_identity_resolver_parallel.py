"""Tests for Phase 4 (parallel identity resolution) and Phase 5 (Beam Identity Network).

Unit tests: mock DB, verify parallel execution and beam graph logic.
"""

import asyncio
import time
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.services.identity_resolver import IdentityResolver


def _make_visitor(**overrides):
    """Create a fake Visitor-like object for testing."""
    defaults = {
        "id": uuid.uuid4(),
        "site_id": "test-site",
        "visitor_id": f"v-{uuid.uuid4().hex[:8]}",
        "ip_address": "203.0.113.42",
        "fingerprint": "fp2_abc123def456",
        "identity_status": "anonymous",
        "company_domain": None,
        "country_code": None,
        "first_seen": datetime.now(timezone.utc),
        "last_seen": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_resolver(db=None, redis_client=None):
    """Create an IdentityResolver with mocked dependencies."""
    if db is None:
        db = AsyncMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock()
    if redis_client is None:
        redis_client = MagicMock()  # Prevent auto-import of real redis
    return IdentityResolver(db=db, redis_client=redis_client)


class TestParallelIdentityGraphs:
    """Phase 4: identity graphs run concurrently."""

    @pytest.mark.asyncio
    @patch("apps.api.services.identity_resolver.settings")
    async def test_all_three_graphs_called_in_parallel(self, mock_settings):
        mock_settings.leadpipe_api_key = "test-lp"
        mock_settings.capturify_api_key = "test-cap"
        mock_settings.rb2b_api_key = "test-rb2b"

        resolver = _make_resolver()
        visitor = _make_visitor()

        call_times = []

        async def timed_mock(name):
            async def wrapper(v):
                call_times.append((name, time.monotonic()))
                return None  # No match
            return wrapper

        resolver._call_leadpipe_api = await timed_mock("leadpipe")
        resolver._call_capturify_api = await timed_mock("capturify")
        resolver._call_rb2b_api = await timed_mock("rb2b")

        result = await resolver._resolve_identity_graphs_parallel(visitor)

        assert result is None
        assert len(call_times) == 3, "All 3 providers should be called"
        providers_called = {name for name, _ in call_times}
        assert providers_called == {"leadpipe", "capturify", "rb2b"}

    @pytest.mark.asyncio
    @patch("apps.api.services.identity_resolver.settings")
    async def test_first_match_wins(self, mock_settings):
        mock_settings.leadpipe_api_key = "test-lp"
        mock_settings.capturify_api_key = "test-cap"
        mock_settings.rb2b_api_key = "test-rb2b"

        resolver = _make_resolver()
        visitor = _make_visitor()

        async def no_match(v):
            return None

        async def cap_match(v):
            return {
                "email": "cap@test.com",
                "full_name": "Cap User",
                "confidence_score": 0.9,
            }

        async def rb2b_match(v):
            return {
                "email": "rb2b@test.com",
                "full_name": "RB2B User",
                "confidence_score": 0.85,
            }

        resolver._call_leadpipe_api = no_match
        resolver._call_capturify_api = cap_match
        resolver._call_rb2b_api = rb2b_match

        resolver._log_resolution = AsyncMock()
        resolver._save_identified = AsyncMock(return_value="identified-capturify")
        resolver._upsert_beam_identity = AsyncMock()

        result = await resolver._resolve_identity_graphs_parallel(visitor)

        assert result == "identified-capturify"
        resolver._save_identified.assert_called_once()
        call_args = resolver._save_identified.call_args
        assert call_args[0][1]["email"] == "cap@test.com"
        assert call_args[0][2] == "capturify"

    @pytest.mark.asyncio
    @patch("apps.api.services.identity_resolver.settings")
    async def test_skips_provider_without_api_key(self, mock_settings):

        mock_settings.leadpipe_api_key = "test-lp"
        mock_settings.capturify_api_key = ""  # Empty — skip
        mock_settings.rb2b_api_key = None  # None — skip

        resolver = _make_resolver()
        resolver._call_leadpipe_api = AsyncMock(return_value=None)
        resolver._log_resolution = AsyncMock()

        visitor = _make_visitor()

        result = await resolver._resolve_identity_graphs_parallel(visitor)

        assert result is None
        assert resolver._log_resolution.call_count == 1  # Only leadpipe logged

    @pytest.mark.asyncio
    @patch("apps.api.services.identity_resolver.settings")
    async def test_timeout_doesnt_block_others(self, mock_settings):

        mock_settings.leadpipe_api_key = "test-lp"
        mock_settings.capturify_api_key = "test-cap"
        mock_settings.rb2b_api_key = "test-rb2b"

        resolver = _make_resolver()
        visitor = _make_visitor()

        async def slow_leadpipe(v):
            await asyncio.sleep(10)  # Way past 5s timeout
            return {"email": "slow@test.com"}

        async def fast_capturify(v):
            return {"email": "fast@test.com", "full_name": "Fast", "confidence_score": 0.9}

        async def fast_rb2b(v):
            return None

        resolver._call_leadpipe_api = slow_leadpipe
        resolver._call_capturify_api = fast_capturify
        resolver._call_rb2b_api = fast_rb2b
        resolver._log_resolution = AsyncMock()
        resolver._save_identified = AsyncMock(return_value="identified-cap")
        resolver._upsert_beam_identity = AsyncMock()

        start = time.monotonic()
        result = await resolver._resolve_identity_graphs_parallel(visitor)
        elapsed = time.monotonic() - start

        assert result == "identified-cap"
        assert elapsed < 7, f"Should not wait for slow provider, took {elapsed:.1f}s"

    @pytest.mark.asyncio
    @patch("apps.api.services.identity_resolver.settings")
    async def test_exception_in_one_provider_doesnt_crash(self, mock_settings):

        mock_settings.leadpipe_api_key = "test-lp"
        mock_settings.capturify_api_key = "test-cap"
        mock_settings.rb2b_api_key = "test-rb2b"

        resolver = _make_resolver()
        visitor = _make_visitor()

        async def exploding_leadpipe(v):
            raise ConnectionError("API down")

        async def working_capturify(v):
            return {"email": "works@test.com", "full_name": "Works", "confidence_score": 0.8}

        async def working_rb2b(v):
            return None

        resolver._call_leadpipe_api = exploding_leadpipe
        resolver._call_capturify_api = working_capturify
        resolver._call_rb2b_api = working_rb2b
        resolver._log_resolution = AsyncMock()
        resolver._save_identified = AsyncMock(return_value="identified")
        resolver._upsert_beam_identity = AsyncMock()

        result = await resolver._resolve_identity_graphs_parallel(visitor)

        assert result == "identified"


class TestParallelIPCompany:
    """Phase 4: PDL + IPinfo run concurrently."""

    @pytest.mark.asyncio
    @patch("apps.api.services.identity_resolver.settings")
    async def test_both_providers_called(self, mock_settings):
        mock_settings.pdl_api_key = "test-pdl"
        mock_settings.ipinfo_token = "test-ipinfo"

        resolver = _make_resolver()
        visitor = _make_visitor()

        pdl_called = False
        ipinfo_called = False

        async def track_pdl(v):
            nonlocal pdl_called
            pdl_called = True
            return None

        async def track_ipinfo(v):
            nonlocal ipinfo_called
            ipinfo_called = True
            return None

        resolver._call_pdl_ip_enrich = track_pdl
        resolver._call_ipinfo_api = track_ipinfo
        resolver._log_resolution = AsyncMock()

        result = await resolver._resolve_ip_company_parallel(visitor)

        assert pdl_called
        assert ipinfo_called

    @pytest.mark.asyncio
    @patch("apps.api.services.identity_resolver.settings")
    async def test_pdl_preferred_over_ipinfo(self, mock_settings):
        mock_settings.pdl_api_key = "test-pdl"
        mock_settings.ipinfo_token = "test-ipinfo"

        resolver = _make_resolver()
        visitor = _make_visitor()

        async def pdl_result(v):
            return "pdl-company.com"

        async def ipinfo_result(v):
            return "ipinfo-company.com"

        resolver._call_pdl_ip_enrich = pdl_result
        resolver._call_ipinfo_api = ipinfo_result
        resolver._log_resolution = AsyncMock()

        result = await resolver._resolve_ip_company_parallel(visitor)

        assert result == "pdl-company.com"

    @pytest.mark.asyncio
    @patch("apps.api.services.identity_resolver.settings")
    async def test_ipinfo_fallback_when_pdl_fails(self, mock_settings):
        mock_settings.pdl_api_key = "test-pdl"
        mock_settings.ipinfo_token = "test-ipinfo"

        resolver = _make_resolver()
        visitor = _make_visitor()

        async def pdl_none(v):
            return None

        async def ipinfo_fallback(v):
            return "fallback.com"

        resolver._call_pdl_ip_enrich = pdl_none
        resolver._call_ipinfo_api = ipinfo_fallback
        resolver._log_resolution = AsyncMock()

        result = await resolver._resolve_ip_company_parallel(visitor)

        assert result == "fallback.com"

    @pytest.mark.asyncio
    @patch("apps.api.services.identity_resolver.settings")
    async def test_both_log_resolution(self, mock_settings):
        mock_settings.pdl_api_key = "test-pdl"
        mock_settings.ipinfo_token = "test-ipinfo"

        resolver = _make_resolver()
        visitor = _make_visitor()

        async def pdl_result(v):
            return "some.com"

        async def ipinfo_none(v):
            return None

        resolver._call_pdl_ip_enrich = pdl_result
        resolver._call_ipinfo_api = ipinfo_none
        resolver._log_resolution = AsyncMock()

        await resolver._resolve_ip_company_parallel(visitor)

        assert resolver._log_resolution.call_count == 2
        providers_logged = {call.args[1] for call in resolver._log_resolution.call_args_list}
        assert providers_logged == {"pdl_ip_enrich", "ipinfo"}


class TestBeamIdentityNetwork:
    """Phase 5: cross-customer identity graph."""

    @pytest.mark.asyncio
    async def test_upsert_requires_fingerprint_and_email(self):
        resolver = _make_resolver()

        visitor_no_fp = _make_visitor(fingerprint=None)
        await resolver._upsert_beam_identity(
            visitor_no_fp, {"email": "test@test.com"}, "leadpipe"
        )

        visitor_no_email = _make_visitor()
        await resolver._upsert_beam_identity(
            visitor_no_email, {"full_name": "No Email"}, "leadpipe"
        )

        # Neither should have triggered a DB execute
        resolver.db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_upsert_executes_on_valid_data(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        resolver = _make_resolver(db=db)

        visitor = _make_visitor(fingerprint="fp2_test123")
        await resolver._upsert_beam_identity(
            visitor,
            {"email": "user@company.com", "full_name": "Test User", "confidence_score": 0.9},
            "capturify",
        )

        db.execute.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_handles_db_error_gracefully(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("DB error"))
        db.rollback = AsyncMock()
        resolver = _make_resolver(db=db)

        visitor = _make_visitor()
        # Should not raise
        await resolver._upsert_beam_identity(
            visitor,
            {"email": "user@test.com", "confidence_score": 0.8},
            "rb2b",
        )

        db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_network_returns_none_without_fingerprint(self):
        resolver = _make_resolver()
        visitor = _make_visitor(fingerprint=None)

        result = await resolver._check_beam_identity_network(visitor)

        assert result is None
        resolver.db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_network_queries_by_fingerprint(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        resolver = _make_resolver(db=db)

        visitor = _make_visitor(fingerprint="fp2_lookup_test")

        result = await resolver._check_beam_identity_network(visitor)

        assert result is None
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_network_returns_match_with_discounted_confidence(self):
        mock_node = SimpleNamespace(
            email="known@example.com",
            full_name="Known Person",
            confidence_score=0.95,
            source_site_id="other-site",
            source_provider="leadpipe",
        )

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_node
        db.execute = AsyncMock(return_value=mock_result)
        db.commit = AsyncMock()
        db.add = MagicMock()

        resolver = _make_resolver(db=db)
        resolver._upsert_beam_identity = AsyncMock()

        mock_identified = SimpleNamespace(
            visitor_id="v-matched",
            email="known@example.com",
            confidence_score=0.85,
        )
        resolver._save_identified = AsyncMock(return_value=mock_identified)

        visitor = _make_visitor(fingerprint="fp2_matched")

        result = await resolver._check_beam_identity_network(visitor)

        assert result is not None
        resolver._save_identified.assert_called_once()
        call_args = resolver._save_identified.call_args
        assert call_args[0][1]["confidence_score"] == 0.85

    @pytest.mark.asyncio
    async def test_check_network_handles_db_error(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("Connection lost"))
        resolver = _make_resolver(db=db)

        visitor = _make_visitor(fingerprint="fp2_error_test")

        result = await resolver._check_beam_identity_network(visitor)

        assert result is None  # Graceful failure


class TestGraphTimeout:
    """Phase 4: 5-second timeout on each provider."""

    def test_timeout_constant_is_5_seconds(self):
        assert IdentityResolver._GRAPH_TIMEOUT == 5.0
