"""P3 (own-data): per-provider on/off toggles + demote PDL-enrich-on-owned-email.

Disabling a provider (env flag, key kept) must skip it entirely — no call, no
ledger row. A captured/owned email must NOT spend a PDL credit unless explicitly
enabled; otherwise it's saved as a $0 form_capture.
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    return IdentityResolver(db=db, redis_client=MagicMock())


def _result_returning(obj):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=obj)
    return r


class TestGraphProviderToggle:
    @pytest.mark.asyncio
    @patch("apps.api.services.identity_resolver.settings")
    async def test_rb2b_disabled_is_never_called(self, mock_settings):
        mock_settings.leadpipe_api_key = "k"
        mock_settings.capturify_api_key = "k"
        mock_settings.rb2b_api_key = "k"
        mock_settings.leadpipe_enabled = True
        mock_settings.capturify_enabled = True
        mock_settings.rb2b_enabled = False  # demoted — keep the key, skip the call

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
        assert "rb2b" not in called
        assert set(called) == {"leadpipe", "capturify"}
        # No ledger row for the skipped provider.
        logged = {c.args[1] for c in resolver._log_resolution.call_args_list}
        assert "rb2b" not in logged


class TestCapturedEmailPdlGate:
    async def _run_check1(self, enrich_flag: bool):
        resolver = _make_resolver()
        visitor = _make_visitor()
        # Check 1's VisitorEmail lookup returns a captured email.
        resolver.db.execute = AsyncMock(return_value=_result_returning("owner@acme.com"))
        resolver._enrich_email_pdl = AsyncMock(return_value="ENRICHED")
        resolver._save_identified = AsyncMock(return_value="FORM_CAPTURE")
        with patch("apps.api.services.identity_resolver.settings") as s:
            s.enrich_captured_email_pdl = enrich_flag
            result = await resolver._check_prior_signals(visitor)
        return resolver, result

    @pytest.mark.asyncio
    async def test_owned_email_skips_pdl_by_default(self):
        resolver, result = await self._run_check1(enrich_flag=False)
        resolver._enrich_email_pdl.assert_not_called()
        # Saved as a free form_capture identification instead.
        assert result == "FORM_CAPTURE"
        args, _ = resolver._save_identified.call_args
        assert args[2] == "form_capture"

    @pytest.mark.asyncio
    async def test_owned_email_uses_pdl_when_enabled(self):
        resolver, result = await self._run_check1(enrich_flag=True)
        resolver._enrich_email_pdl.assert_awaited_once()
        assert result == "ENRICHED"
