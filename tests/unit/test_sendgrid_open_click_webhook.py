"""Owned-data-layer Phase 2: SendGrid open/click webhook branch.

- existing bounce/dropped/spamreport suppression behavior UNCHANGED (regression)
- open/click are no-ops when identity_signals_enabled is False (default)
- when enabled: site_id derived from echoed custom_args; event skipped (no
  record_signal) when site_id is absent — never guessed
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.routers import webhooks

pytestmark = pytest.mark.unit


class _FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


def _settings(flag_on: bool):
    s = MagicMock()
    s.sendgrid_webhook_secret = "secret"
    s.identity_signals_enabled = flag_on
    return s


async def _call(payload, flag_on):
    db = AsyncMock()
    add_sup = AsyncMock()
    rec = AsyncMock()
    with patch.object(webhooks, "settings", _settings(flag_on)), patch.object(
        webhooks, "add_suppression", add_sup
    ), patch.object(webhooks, "record_signal", rec):
        result = await webhooks.sendgrid_events(
            _FakeRequest(payload), token="secret", db=db
        )
    return result, add_sup, rec


class TestSuppressRegression:
    @pytest.mark.asyncio
    async def test_existing_suppress_events_unchanged(self):
        payload = [{"event": "bounce", "type": "bounce", "email": "b@acme.com"}]
        result, add_sup, rec = await _call(payload, flag_on=True)
        add_sup.assert_awaited_once()
        rec.assert_not_awaited()
        assert result["suppressed"] == 1

    @pytest.mark.asyncio
    async def test_soft_bounce_ignored(self):
        payload = [{"event": "bounce", "type": "deferred", "email": "b@acme.com"}]
        result, add_sup, rec = await _call(payload, flag_on=True)
        add_sup.assert_not_awaited()
        assert result["suppressed"] == 0


class TestOpenClickFlagGating:
    @pytest.mark.asyncio
    async def test_open_click_flag_off_noop(self):
        payload = [
            {"event": "open", "email": "a@acme.com", "ip": "203.0.113.5", "site_id": "s1"},
            {"event": "click", "email": "a@acme.com", "ip": "203.0.113.5", "site_id": "s1"},
        ]
        result, add_sup, rec = await _call(payload, flag_on=False)
        rec.assert_not_awaited()
        assert result["signals"] == 0


class TestSiteIdFromCustomArgsOrSkip:
    @pytest.mark.asyncio
    async def test_records_when_site_id_present(self):
        payload = [
            {"event": "open", "email": "a@acme.com", "ip": "203.0.113.5",
             "site_id": "s1", "visitor_id": "v1"},
        ]
        result, add_sup, rec = await _call(payload, flag_on=True)
        rec.assert_awaited_once()
        kwargs = rec.await_args.kwargs
        assert kwargs["site_id"] == "s1"
        assert kwargs["signal_type"] == "sendgrid_open"
        assert result["signals"] == 1

    @pytest.mark.asyncio
    async def test_skips_when_site_id_absent(self):
        payload = [{"event": "click", "email": "a@acme.com", "ip": "203.0.113.5"}]
        result, add_sup, rec = await _call(payload, flag_on=True)
        rec.assert_not_awaited()
        assert result["signals"] == 0

    @pytest.mark.asyncio
    async def test_skips_when_ip_absent(self):
        payload = [{"event": "click", "email": "a@acme.com", "site_id": "s1"}]
        result, add_sup, rec = await _call(payload, flag_on=True)
        rec.assert_not_awaited()
        assert result["signals"] == 0
