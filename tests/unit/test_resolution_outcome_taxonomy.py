"""A provider outage is not a resolution attempt.

`resolution_logs` doubles as the 30-day retry lock and the daily budget meter, so
writing a row for a vendor outage punishes the visitor for the vendor's downtime:
6/7 unidentified US visitors sit inside that lock with zero successful matches
(`docs/identity-us-current-handoff.md`). These tests pin the separation — outages
go to `api_usage_logs` only.

Which provider wrote those locking rows is deliberately NOT asserted here: the
same doc records `leadpipe logs = 0`, so the outage that is easiest to observe is
not necessarily the one that did the locking. The taxonomy has to be right for
every provider regardless of which one is currently misbehaving.
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from apps.api.models.visitor import ResolutionLog
from apps.api.services.identity_providers.base import (
    RESOLUTION_OUTCOME_MATCH,
    RESOLUTION_OUTCOME_NO_MATCH,
    RESOLUTION_OUTCOME_PROVIDER_UNAVAILABLE,
    ProviderUnavailableError,
)
from apps.api.services.identity_resolver import IdentityResolver


def _make_visitor(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "site_id": "test-site",
        "visitor_id": f"v-{uuid.uuid4().hex[:8]}",
        "ip_address": "203.0.113.42",
        "fingerprint": None,
        "server_visitor_id": None,
        "identity_status": "anonymous",
        "country_code": None,
        "user_agent": "Mozilla/5.0",
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
    db.flush = AsyncMock()
    return IdentityResolver(db=db, redis_client=MagicMock())


def _resolution_logs_added(resolver) -> list:
    return [
        c.args[0]
        for c in resolver.db.add.call_args_list
        if isinstance(c.args[0], ResolutionLog)
    ]


class TestLogResolutionLedgerSplit:
    """The single decision point: which ledger receives the row."""

    @pytest.mark.asyncio
    async def test_outage_writes_no_resolution_log(self):
        resolver = _make_resolver()
        with patch("apps.api.services.identity_resolver.log_api_call", new=AsyncMock()) as api_log:
            await resolver._log_resolution(
                _make_visitor(), "leadpipe", False, 0.0, 12,
                outcome=RESOLUTION_OUTCOME_PROVIDER_UNAVAILABLE,
                detail="HTTP 403: Organization is expired",
            )

        assert _resolution_logs_added(resolver) == [], (
            "an outage must not arm the 30-day retry lock"
        )
        # ...but it must still be observable in the cost ledger.
        api_log.assert_awaited_once()
        kwargs = api_log.await_args.kwargs
        assert kwargs["meta"]["outcome"] == RESOLUTION_OUTCOME_PROVIDER_UNAVAILABLE
        assert "Organization is expired" in kwargs["meta"]["detail"]
        assert kwargs["success"] is False
        assert kwargs["cost_usd"] == 0.0

    @pytest.mark.asyncio
    async def test_real_no_match_still_writes_resolution_log(self):
        """A provider that answered "nobody" SHOULD lock — that is the design."""
        resolver = _make_resolver()
        with patch("apps.api.services.identity_resolver.log_api_call", new=AsyncMock()) as api_log:
            await resolver._log_resolution(_make_visitor(), "leadpipe", False, 0.0, 12)

        rows = _resolution_logs_added(resolver)
        assert len(rows) == 1
        assert rows[0].success is False
        assert api_log.await_args.kwargs["meta"]["outcome"] == RESOLUTION_OUTCOME_NO_MATCH

    @pytest.mark.asyncio
    async def test_match_writes_resolution_log_and_tags_outcome(self):
        resolver = _make_resolver()
        with patch("apps.api.services.identity_resolver.log_api_call", new=AsyncMock()) as api_log:
            await resolver._log_resolution(_make_visitor(), "rb2b", True, 0.09, 30)

        rows = _resolution_logs_added(resolver)
        assert len(rows) == 1
        assert rows[0].success is True
        assert rows[0].cost_usd == 0.09
        assert api_log.await_args.kwargs["meta"]["outcome"] == RESOLUTION_OUTCOME_MATCH

    @pytest.mark.asyncio
    async def test_existing_positional_call_signature_is_unchanged(self):
        """The 7 production call sites and 13 test mocks pass no `outcome`.

        Keyword-only with a derived default is what keeps them byte-identical.
        """
        resolver = _make_resolver()
        with patch("apps.api.services.identity_resolver.log_api_call", new=AsyncMock()):
            await resolver._log_resolution(_make_visitor(), "pdl_ip_enrich", False, 0.0, 5)
        assert len(_resolution_logs_added(resolver)) == 1


class TestPersistedDetailIsSafe:
    """`meta.detail` is durable and outside the DSAR erase path — keep it clean.

    Providers pass credentials as query params (ipinfo `?token=`, hunter
    `api_key=`) and the visitor IP in the path, and httpx puts the whole request
    URL into `HTTPStatusError.__str__`. Interpolating `str(exc)` would write a
    live API token and PII straight into `api_usage_logs`.
    """

    def _status_error(self, url: str, status: int = 429) -> httpx.HTTPStatusError:
        resp = httpx.Response(status, request=httpx.Request("GET", url))
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return exc
        raise AssertionError("expected raise_for_status to raise")

    def test_api_token_never_reaches_the_detail(self):
        from apps.api.services.identity_providers.base import safe_failure_detail

        exc = self._status_error("https://ipinfo.io/203.0.113.42?token=SECRET_TOKEN_123")
        detail = safe_failure_detail(exc)
        assert "SECRET_TOKEN_123" not in detail
        assert detail == "HTTPStatusError: HTTP 429"

    def test_visitor_ip_never_reaches_the_detail(self):
        from apps.api.services.identity_providers.base import safe_failure_detail

        exc = self._status_error("https://api.peopledatalabs.com/v5/ip/enrich?ip=203.0.113.42")
        assert "203.0.113.42" not in safe_failure_detail(exc)

    def test_detail_still_carries_enough_to_diagnose(self):
        from apps.api.services.identity_providers.base import safe_failure_detail

        assert safe_failure_detail(self._status_error("https://x.test/a", 503)) == (
            "HTTPStatusError: HTTP 503"
        )
        assert safe_failure_detail(httpx.ConnectTimeout("boom")) == "ConnectTimeout"
        assert safe_failure_detail(
            ProviderUnavailableError("leadpipe", "HTTP 403")
        ) == "ProviderUnavailableError: HTTP 403"

    def test_provider_errors_do_not_embed_response_bodies(self):
        """Third-party response bodies are unbounded, untrusted text."""
        from apps.api.services.identity_providers.base import safe_failure_detail

        exc = ProviderUnavailableError("rb2b", "HTTP 403")
        assert "<html" not in safe_failure_detail(exc)
        assert exc.detail == "HTTP 403"

    @pytest.mark.asyncio
    async def test_unknown_outcome_is_rejected_rather_than_silently_ignored(self):
        resolver = _make_resolver()
        with patch("apps.api.services.identity_resolver.log_api_call", new=AsyncMock()):
            with pytest.raises(ValueError, match="unknown resolution outcome"):
                await resolver._log_resolution(
                    _make_visitor(), "leadpipe", False, 0.0, 1,
                    outcome="provider_unavailble",  # typo on purpose
                )


class TestUnexpectedErrorsStillLock:
    """A bug in OUR parser must not read as a vendor outage.

    phase-02's risk table: lean toward `no_match` when unsure, because "never
    lock" turns a parse bug into a retry storm that re-hits the provider on
    every sweep.
    """

    @pytest.mark.asyncio
    @patch("apps.api.services.identity_resolver.settings")
    async def test_parse_bug_is_no_match_not_outage(self, mock_settings):
        mock_settings.leadpipe_api_key = "k"
        mock_settings.capturify_api_key = ""
        mock_settings.rb2b_api_key = ""
        mock_settings.leadpipe_enabled = True
        mock_settings.capturify_enabled = False
        mock_settings.rb2b_enabled = False

        resolver = _make_resolver()
        resolver._log_resolution = AsyncMock()

        async def _our_bug(v):
            raise KeyError("full_name")

        resolver._call_leadpipe_api = _our_bug
        await resolver._resolve_identity_graphs_parallel(_make_visitor())

        call = resolver._log_resolution.call_args_list[0]
        assert call.kwargs["outcome"] is None, (
            "a KeyError in our parser is not a provider outage"
        )

    @pytest.mark.asyncio
    @patch("apps.api.services.identity_resolver.settings")
    async def test_transport_error_is_still_an_outage(self, mock_settings):
        mock_settings.leadpipe_api_key = "k"
        mock_settings.capturify_api_key = ""
        mock_settings.rb2b_api_key = ""
        mock_settings.leadpipe_enabled = True
        mock_settings.capturify_enabled = False
        mock_settings.rb2b_enabled = False

        resolver = _make_resolver()
        resolver._log_resolution = AsyncMock()

        async def _down(v):
            raise httpx.ConnectError("no route to host")

        resolver._call_leadpipe_api = _down
        await resolver._resolve_identity_graphs_parallel(_make_visitor())

        call = resolver._log_resolution.call_args_list[0]
        assert call.kwargs["outcome"] == RESOLUTION_OUTCOME_PROVIDER_UNAVAILABLE
        assert call.kwargs["detail"] == "ConnectError"


class TestKeylessProviderIsNeverAnAttempt:
    """A provider with no API key is never called — so it never "failed".

    Both `_call_pdl_ip_enrich` and `_call_ipinfo_api` return None immediately on
    an empty key. Writing a ResolutionLog for that arms the 30-day lock and burns
    a daily budget slot because of a config gap, not because of the visitor.
    """

    @pytest.mark.asyncio
    @patch("apps.api.services.identity_resolver.settings")
    async def test_missing_keys_write_no_ledger_rows(self, mock_settings):
        mock_settings.pdl_ip_enabled = True   # enabled...
        mock_settings.ipinfo_enabled = True
        mock_settings.people_data_labs_api_key = ""  # ...but keyless
        mock_settings.ipinfo_token = ""

        resolver = _make_resolver()
        resolver._log_resolution = AsyncMock()
        called = []
        resolver._call_pdl_ip_enrich = lambda v: called.append("pdl")
        resolver._call_ipinfo_api = lambda v: called.append("ipinfo")

        domain = await resolver._resolve_ip_company_parallel(_make_visitor())

        assert domain is None
        assert called == [], "a keyless provider must not be called"
        resolver._log_resolution.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("apps.api.services.identity_resolver.settings")
    async def test_keyed_provider_still_logs_normally(self, mock_settings):
        mock_settings.pdl_ip_enabled = True
        mock_settings.ipinfo_enabled = False
        mock_settings.people_data_labs_api_key = "k"
        mock_settings.ipinfo_token = ""

        resolver = _make_resolver()
        resolver._log_resolution = AsyncMock()

        async def _no_match(v):
            return None

        resolver._call_pdl_ip_enrich = _no_match

        await resolver._resolve_ip_company_parallel(_make_visitor())

        logged = [c.args[1] for c in resolver._log_resolution.call_args_list]
        assert logged == ["pdl_ip_enrich"]


class TestProviderUnavailableSignal:
    """Mixins must raise, not return None, when they never got an answer."""

    def _resp(self, status: int, text: str = "") -> httpx.Response:
        return httpx.Response(
            status, text=text, request=httpx.Request("GET", "https://x.test")
        )

    @pytest.mark.asyncio
    async def test_rb2b_403_raises_instead_of_returning_none(self):
        """RB2B returning None for 403 is the exact bug: an outage read as no-match."""
        from apps.api.services.identity_providers.rb2b import RB2BMixin

        class _R(RB2BMixin):
            pass

        client = AsyncMock()
        client.post = AsyncMock(return_value=self._resp(403, "Forbidden"))
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=client)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("apps.api.services.identity_providers.rb2b.settings") as s, \
             patch("httpx.AsyncClient", return_value=cm):
            s.rb2b_api_key = "k"
            with pytest.raises(ProviderUnavailableError) as exc:
                await _R()._call_rb2b_api.__wrapped__(_R(), _make_visitor())

        assert exc.value.provider == "rb2b"

    @pytest.mark.asyncio
    async def test_rb2b_404_still_returns_none(self):
        """404 is a real answer — it must keep locking."""
        from apps.api.services.identity_providers.rb2b import RB2BMixin

        class _R(RB2BMixin):
            pass

        client = AsyncMock()
        client.post = AsyncMock(return_value=self._resp(404))
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=client)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("apps.api.services.identity_providers.rb2b.settings") as s, \
             patch("httpx.AsyncClient", return_value=cm):
            s.rb2b_api_key = "k"
            result = await _R()._call_rb2b_api.__wrapped__(_R(), _make_visitor())

        assert result is None


class TestWaterfallClassifiesOutages:
    """End-to-end through _resolve_identity_graphs_parallel."""

    @pytest.mark.asyncio
    @patch("apps.api.services.identity_resolver.settings")
    async def test_unavailable_provider_logged_as_outage(self, mock_settings):
        mock_settings.leadpipe_api_key = "k"
        mock_settings.capturify_api_key = ""
        mock_settings.rb2b_api_key = "k"
        mock_settings.leadpipe_enabled = True
        mock_settings.capturify_enabled = False
        mock_settings.rb2b_enabled = True

        resolver = _make_resolver()
        resolver._log_resolution = AsyncMock()

        async def _down(v):
            raise ProviderUnavailableError("leadpipe", "HTTP 403: Organization is expired")

        async def _no_match(v):
            return None

        resolver._call_leadpipe_api = _down
        resolver._call_rb2b_api = _no_match

        result = await resolver._resolve_identity_graphs_parallel(_make_visitor())
        assert result is None

        by_provider = {
            c.args[1]: c.kwargs.get("outcome")
            for c in resolver._log_resolution.call_args_list
        }
        assert by_provider["leadpipe"] == RESOLUTION_OUTCOME_PROVIDER_UNAVAILABLE
        # The healthy provider genuinely found nobody — it must NOT be an outage.
        assert by_provider["rb2b"] is None

    @pytest.mark.asyncio
    @patch("apps.api.services.identity_resolver.settings")
    async def test_timeout_is_treated_as_unavailable(self, mock_settings):
        mock_settings.leadpipe_api_key = "k"
        mock_settings.capturify_api_key = ""
        mock_settings.rb2b_api_key = ""
        mock_settings.leadpipe_enabled = True
        mock_settings.capturify_enabled = False
        mock_settings.rb2b_enabled = False

        resolver = _make_resolver()
        resolver._log_resolution = AsyncMock()
        resolver._GRAPH_TIMEOUT = 0.01

        async def _hang(v):
            import asyncio
            await asyncio.sleep(5)

        resolver._call_leadpipe_api = _hang

        await resolver._resolve_identity_graphs_parallel(_make_visitor())

        call = resolver._log_resolution.call_args_list[0]
        assert call.kwargs["outcome"] == RESOLUTION_OUTCOME_PROVIDER_UNAVAILABLE
        assert call.kwargs["detail"] == "timeout"


class TestRejectionCounters:
    """Every drop reason must be countable, not scattered across debug logs."""

    def test_tally_counts_no_timestamp_and_outside_window(self):
        from apps.api.services.identity_providers.matching import (
            REJECTION_NO_TIMESTAMP,
            REJECTION_OUTSIDE_WINDOW,
            MatchingMixin,
            new_rejection_tally,
        )

        class _M(MatchingMixin):
            pass

        m = _M()
        now = datetime.now(timezone.utc)
        visitor = _make_visitor(last_seen=now)
        tally = new_rejection_tally()

        # No usable timestamp field at all.
        m._record_matches_visitor({"ip": "203.0.113.42"}, visitor, "leadpipe", tally=tally)
        # Timestamped far outside the 30-minute window.
        old = (now - __import__("datetime").timedelta(hours=9)).isoformat()
        m._record_matches_visitor({"timestamp": old}, visitor, "leadpipe", tally=tally)

        assert tally[REJECTION_NO_TIMESTAMP] == 1
        assert tally[REJECTION_OUTSIDE_WINDOW] == 1

    def test_tally_is_optional_so_existing_callers_are_unaffected(self):
        from apps.api.services.identity_providers.matching import MatchingMixin

        class _M(MatchingMixin):
            pass

        matched, weak = _M()._record_matches_visitor(
            {"ip": "203.0.113.42"}, _make_visitor(), "leadpipe"
        )
        assert (matched, weak) == (False, False)

    def test_every_reason_starts_at_zero_so_it_reports_explicitly(self):
        from apps.api.services.identity_providers.matching import (
            REJECTION_REASONS,
            new_rejection_tally,
        )

        tally = new_rejection_tally()
        assert set(tally) == set(REJECTION_REASONS)
        assert all(v == 0 for v in tally.values())

    @pytest.mark.asyncio
    async def test_ip_mismatch_is_tallied_by_a_real_leadpipe_scan(self):
        """The IP filter lives in leadpipe.py, not matching.py — count it there.

        Drives the actual `_call_leadpipe_api` loop against a feed of records
        from other people's IPs, then asserts the summary it emitted.
        """
        from apps.api.services.identity_providers.leadpipe import LeadpipeMixin
        from apps.api.services.identity_providers.matching import (
            REJECTION_IP_MISMATCH,
            MatchingMixin,
        )

        class _L(MatchingMixin, LeadpipeMixin):
            async def _site_domain(self, site_id):
                return "example.com"

        visitor = _make_visitor(ip_address="203.0.113.42")
        feed = {
            "data": [
                {"email": "a@x.com", "ip": "198.51.100.1"},   # someone else's IP
                {"email": "b@x.com", "ip": "198.51.100.2"},   # someone else's IP
                {"email": "c@x.com", "ipAddress": "198.51.100.3"},
                {"email": "d@x.com"},                          # no IP at all
            ]
        }
        resp = httpx.Response(
            200, json=feed, request=httpx.Request("GET", "https://x.test")
        )
        client = AsyncMock()
        client.get = AsyncMock(return_value=resp)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=client)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("apps.api.services.identity_providers.leadpipe.settings") as s, \
             patch("httpx.AsyncClient", return_value=cm), \
             patch("apps.api.services.identity_providers.matching.logger") as log:
            s.leadpipe_api_key = "k"
            result = await _L()._call_leadpipe_api.__wrapped__(_L(), visitor)

        assert result is None
        log.info.assert_called_once()
        kwargs = log.info.call_args.kwargs
        # Three held someone else's IP, one had no IP field — all four are
        # "cannot attach on IP", which is the same bucket.
        assert kwargs[REJECTION_IP_MISMATCH] == 4
        assert kwargs["scanned"] == 4
        # Every scanned record is accounted for by some reason.
        assert kwargs["rejected"] == kwargs["scanned"]

    @pytest.mark.asyncio
    async def test_records_without_email_are_counted_not_silently_dropped(self):
        """A bare `continue` with no tally makes scanned/rejected disagree."""
        from apps.api.services.identity_providers.leadpipe import LeadpipeMixin
        from apps.api.services.identity_providers.matching import (
            REJECTION_NO_EMAIL,
            MatchingMixin,
        )

        class _L(MatchingMixin, LeadpipeMixin):
            async def _site_domain(self, site_id):
                return "example.com"

        feed = {"data": [{"ip": "203.0.113.42"}, {"emails": []}]}  # no usable email
        resp = httpx.Response(
            200, json=feed, request=httpx.Request("GET", "https://x.test")
        )
        client = AsyncMock()
        client.get = AsyncMock(return_value=resp)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=client)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("apps.api.services.identity_providers.leadpipe.settings") as s, \
             patch("httpx.AsyncClient", return_value=cm), \
             patch("apps.api.services.identity_providers.matching.logger") as log:
            s.leadpipe_api_key = "k"
            await _L()._call_leadpipe_api.__wrapped__(_L(), _make_visitor())

        kwargs = log.info.call_args.kwargs
        assert kwargs[REJECTION_NO_EMAIL] == 2
        assert kwargs["rejected"] == kwargs["scanned"] == 2

    def test_clean_scan_logs_nothing(self):
        from apps.api.services.identity_providers.matching import (
            log_rejection_tally,
            new_rejection_tally,
        )

        with patch("apps.api.services.identity_providers.matching.logger") as log:
            log_rejection_tally("leadpipe", "v-abc12345", new_rejection_tally(), 0)
            log.info.assert_not_called()

    def test_dirty_scan_logs_at_info_not_debug(self):
        from apps.api.services.identity_providers.matching import (
            REJECTION_IP_MISMATCH,
            log_rejection_tally,
            new_rejection_tally,
        )

        tally = new_rejection_tally()
        tally[REJECTION_IP_MISMATCH] = 3
        with patch("apps.api.services.identity_providers.matching.logger") as log:
            log_rejection_tally("leadpipe", "v-abc12345", tally, 50)
            log.info.assert_called_once()
            log.debug.assert_not_called()
            assert log.info.call_args.kwargs[REJECTION_IP_MISMATCH] == 3
            assert log.info.call_args.kwargs["scanned"] == 50
