"""Phase 01 (GDPR/CCPA): honor GPC/DNT opt-out signals.

Unit-level checks (no DB, no network):
- The pixel emits the opt-out signal (GPC + DNT) on every event.
- IdentityResolver.resolve() refuses any visitor flagged do_not_resolve,
  before touching prior signals, budgets, or providers.
- The Event schema defaults optout to False for older pixel builds.
"""

import pathlib
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.services.identity_resolver import IdentityResolver

PIXEL_PATH = pathlib.Path(__file__).parent.parent.parent / "apps" / "pixel" / "src" / "tracker.js"


@pytest.fixture
def pixel_code() -> str:
    assert PIXEL_PATH.exists(), f"Pixel file not found at {PIXEL_PATH}"
    return PIXEL_PATH.read_text(encoding="utf-8")


class TestPixelOptoutSignal:
    def test_reads_global_privacy_control(self, pixel_code: str):
        assert "globalPrivacyControl" in pixel_code

    def test_reads_do_not_track(self, pixel_code: str):
        assert "doNotTrack" in pixel_code

    def test_sends_optout_on_event(self, pixel_code: str):
        # pushEvent stamps optout onto every event, like _fp.
        assert "evt.optout" in pixel_code


def _make_visitor(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "site_id": "test-site",
        "visitor_id": f"v-{uuid.uuid4().hex[:8]}",
        "ip_address": "203.0.113.42",
        "fingerprint": "fp2_abc123def456",
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
    return IdentityResolver(db=db, redis_client=MagicMock())


class TestResolverHonorsOptout:
    @pytest.mark.asyncio
    async def test_opted_out_visitor_returns_none(self):
        resolver = _make_resolver()
        visitor = _make_visitor(do_not_resolve=True)

        # Guard must fire before any prior-signal lookup, so even a visitor with
        # captured emails / fingerprint matches is never resolved.
        resolver._check_prior_signals = AsyncMock(
            side_effect=AssertionError("prior signals must not run for opted-out visitor")
        )

        result = await resolver.resolve(visitor)

        assert result is None
        resolver.db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_opted_out_visitor_proceeds_to_prior_signals(self):
        resolver = _make_resolver()
        visitor = _make_visitor(do_not_resolve=False)

        sentinel = object()
        resolver._check_prior_signals = AsyncMock(return_value=sentinel)

        result = await resolver.resolve(visitor)

        # Guard is open → flow reaches the prior-signal path and returns its result.
        assert result is sentinel
        resolver._check_prior_signals.assert_awaited_once()


class TestEventSchemaDefault:
    def test_optout_defaults_false(self):
        from apps.api.schemas.events import Event

        evt = Event(type="pageview", ts=datetime.now(timezone.utc))
        assert evt.optout is False

    def test_optout_accepts_true(self):
        from apps.api.schemas.events import Event

        evt = Event(type="pageview", ts=datetime.now(timezone.utc), optout=True)
        assert evt.optout is True
