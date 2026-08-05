"""DNS failures are permanent, so the identity providers must not retry them.

A host with no DNS record fails identically every attempt. Because
`_resolve_identity_graphs_parallel` gathers all providers, retrying one dead host
costs *every* visitor the full timeout budget. Connection-refused looks similar but
is genuinely transient, so the two must stay distinguishable.

The exception shapes below mirror what httpx 0.27.2 actually raises (probed
05-08-26): the `socket.gaierror` is an *argument* of an intermediate
`httpcore.ConnectError`, not reachable through `__cause__` alone.
"""
import socket
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from apps.api.services.identity_providers.base import (
    _is_dns_resolution_failure,
    _is_transient_http_error,
)
from apps.api.services.identity_resolver import IdentityResolver


def _dns_connect_error() -> httpx.ConnectError:
    """Rebuild the exact chain httpx 0.27.2 produces for an unresolvable host."""
    gai = socket.gaierror(11001, "getaddrinfo failed")
    # httpcore wraps gaierror as a positional arg; httpx re-raises with __cause__.
    inner = ConnectionError(gai)
    outer = httpx.ConnectError("[Errno 11001] getaddrinfo failed")
    outer.__cause__ = inner
    return outer


def _refused_connect_error() -> httpx.ConnectError:
    """A reachable name whose port refuses the connection — worth retrying."""
    inner = ConnectionRefusedError(61, "Connection refused")
    outer = httpx.ConnectError("All connection attempts failed")
    outer.__cause__ = inner
    return outer


class TestDnsFailureDetection:
    def test_gaierror_nested_as_argument_is_detected(self):
        assert _is_dns_resolution_failure(_dns_connect_error()) is True

    @pytest.mark.asyncio
    async def test_real_nxdomain_chain_from_httpx_is_detected(self):
        """Provokes a genuine resolver failure instead of trusting the mock shape.

        The hand-built exception above can keep passing if httpx/httpcore change
        how they nest the cause, while production silently reverts to retrying
        dead hosts. `.invalid` is reserved by RFC 2606 and never resolves, so
        this needs no network — only a resolver that says "no".
        """
        with pytest.raises(httpx.ConnectError) as exc_info:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.get("https://nonexistent-host-for-tests.invalid/x")

        assert _is_dns_resolution_failure(exc_info.value) is True
        assert _is_transient_http_error(exc_info.value) is False

    def test_bare_gaierror_is_detected(self):
        assert _is_dns_resolution_failure(socket.gaierror(11001, "getaddrinfo failed")) is True

    def test_connection_refused_is_not_a_dns_failure(self):
        assert _is_dns_resolution_failure(_refused_connect_error()) is False

    def test_cause_chain_walk_terminates_on_self_reference(self):
        """A cyclic __cause__ must not hang the classifier."""
        exc = httpx.ConnectError("boom")
        exc.__cause__ = exc
        assert _is_dns_resolution_failure(exc) is False


class TestTransientClassification:
    def test_dns_failure_is_not_transient(self):
        assert _is_transient_http_error(_dns_connect_error()) is False

    def test_connection_refused_is_still_transient(self):
        assert _is_transient_http_error(_refused_connect_error()) is True

    def test_timeout_is_still_transient(self):
        assert _is_transient_http_error(httpx.ConnectTimeout("timed out")) is True

    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_transient_statuses_unchanged(self, status):
        resp = httpx.Response(status, request=httpx.Request("GET", "https://x.test"))
        exc = httpx.HTTPStatusError("e", request=resp.request, response=resp)
        assert _is_transient_http_error(exc) is True

    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    def test_client_errors_still_not_transient(self, status):
        resp = httpx.Response(status, request=httpx.Request("GET", "https://x.test"))
        exc = httpx.HTTPStatusError("e", request=resp.request, response=resp)
        assert _is_transient_http_error(exc) is False


def _make_visitor():
    return SimpleNamespace(
        id=uuid.uuid4(),
        site_id="test-site",
        visitor_id=f"v-{uuid.uuid4().hex[:8]}",
        ip_address="203.0.113.42",
        fingerprint=None,
        server_visitor_id=None,
        identity_status="anonymous",
        first_seen=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )


def _make_resolver():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    return IdentityResolver(db=db, redis_client=MagicMock())


class TestCapturifyDisabledByDefault:
    @pytest.mark.asyncio
    @patch("apps.api.services.identity_resolver.settings")
    async def test_disabled_capturify_is_never_called_and_logs_nothing(self, mock_settings):
        mock_settings.leadpipe_api_key = "k"
        mock_settings.capturify_api_key = "k"
        mock_settings.rb2b_api_key = "k"
        mock_settings.leadpipe_enabled = True
        mock_settings.rb2b_enabled = True
        mock_settings.capturify_enabled = False  # host has no DNS record

        resolver = _make_resolver()
        resolver._log_resolution = AsyncMock()
        called = []

        def rec(name):
            async def _w(v):
                called.append(name)
                return None
            return _w

        resolver._call_leadpipe_api = rec("leadpipe")
        resolver._call_capturify_api = rec("capturify")
        resolver._call_rb2b_api = rec("rb2b")

        result = await resolver._resolve_identity_graphs_parallel(_make_visitor())

        assert result is None
        assert "capturify" not in called
        assert set(called) == {"leadpipe", "rb2b"}
        logged = {c.args[1] for c in resolver._log_resolution.call_args_list}
        assert "capturify" not in logged

    def test_config_default_is_off(self):
        """Guards against someone flipping the default back without the evidence."""
        from apps.api.config import Settings

        assert Settings.model_fields["capturify_enabled"].default is False
