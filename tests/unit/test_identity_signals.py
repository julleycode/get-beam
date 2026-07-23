"""Owned-data-layer Phase 2: identity_signals corroborating table.

Pure-logic unit coverage (mocked DB, no Postgres):
- decay_confidence formula correctness at 0/30/60/90-day marks
- record_signal write-gate rejection paths (datacenter / proxy / suppressed /
  do_not_resolve) — no insert on any gate failure
- happy path stores encrypted email (ciphertext + bidx), never plaintext
- corroborate_identity NEVER creates/upgrades an IdentifiedVisitor (no writes)
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.models.identity_signal import IdentitySignal
from apps.api.services import identity_signals as sig

pytestmark = pytest.mark.unit


def _mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock()
    return db


class TestDecayConfidence:
    def test_zero_age_is_base(self):
        now = datetime.now(timezone.utc)
        assert sig.decay_confidence(0.6, now, now) == pytest.approx(0.6)

    def test_half_life_30_days(self):
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=30)
        assert sig.decay_confidence(0.6, created, now) == pytest.approx(0.3, rel=1e-3)

    def test_two_half_lives_60_days(self):
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=60)
        assert sig.decay_confidence(0.6, created, now) == pytest.approx(0.15, rel=1e-3)

    def test_90_days(self):
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=90)
        assert sig.decay_confidence(0.6, created, now) == pytest.approx(0.075, rel=1e-3)

    def test_future_timestamp_clamped(self):
        now = datetime.now(timezone.utc)
        created = now + timedelta(days=10)  # future → age clamps to 0
        assert sig.decay_confidence(0.6, created, now) == pytest.approx(0.6)


class TestRecordSignalWriteGates:
    async def _run(self, monkeypatch_targets):
        db = _mock_db()
        with patch.multiple(sig, **monkeypatch_targets):
            await sig.record_signal(db, "site-1", "203.0.113.9", "a@acme.com", "sendgrid_open")
        return db

    @pytest.mark.asyncio
    async def test_rejects_datacenter_ip(self):
        db = await self._run({
            "is_datacenter_ip": AsyncMock(return_value=True),
        })
        db.add.assert_not_called()
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_proxy_vpn(self):
        db = await self._run({
            "is_datacenter_ip": AsyncMock(return_value=False),
            "check_ip_privacy": AsyncMock(return_value={"vpn": True}),
            "is_proxy_or_vpn": MagicMock(return_value=True),
        })
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_suppressed_email(self):
        db = await self._run({
            "is_datacenter_ip": AsyncMock(return_value=False),
            "check_ip_privacy": AsyncMock(return_value=None),
            "is_proxy_or_vpn": MagicMock(return_value=False),
            "is_email_suppressed": AsyncMock(return_value=True),
        })
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_do_not_resolve(self):
        db = await self._run({
            "is_datacenter_ip": AsyncMock(return_value=False),
            "check_ip_privacy": AsyncMock(return_value=None),
            "is_proxy_or_vpn": MagicMock(return_value=False),
            "is_email_suppressed": AsyncMock(return_value=False),
            "_visitor_do_not_resolve": AsyncMock(return_value=True),
        })
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_happy_path_stores_encrypted_email(self):
        db = await self._run({
            "is_datacenter_ip": AsyncMock(return_value=False),
            "check_ip_privacy": AsyncMock(return_value=None),
            "is_proxy_or_vpn": MagicMock(return_value=False),
            "is_email_suppressed": AsyncMock(return_value=False),
            "_visitor_do_not_resolve": AsyncMock(return_value=False),
        })
        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        row = db.add.call_args[0][0]
        assert isinstance(row, IdentitySignal)
        # Never store plaintext email — ciphertext + blind index only.
        assert row.email_ciphertext != "a@acme.com"
        assert row.email_bidx and row.email_bidx != "a@acme.com"
        assert row.signal_type == "sendgrid_open"
        assert row.base_confidence == 0.45

    @pytest.mark.asyncio
    async def test_unknown_signal_type_is_noop(self):
        db = await self._run({
            "is_datacenter_ip": AsyncMock(return_value=False),
        })
        # sendgrid_open passed above; test explicit unknown type here:
        db2 = _mock_db()
        await sig.record_signal(db2, "s", "1.2.3.4", "a@b.com", "bogus_type")
        db2.add.assert_not_called()


class TestCorroborateInvariant:
    @pytest.mark.asyncio
    async def test_returns_decayed_bump_and_never_writes(self):
        db = _mock_db()
        now = datetime.now(timezone.utc)
        rows = [
            SimpleNamespace(base_confidence=0.6, created_at=now, ip="1.2.3.4"),
            SimpleNamespace(base_confidence=0.45, created_at=now - timedelta(days=30), ip="1.2.3.4"),
        ]
        scal = MagicMock()
        scal.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=rows)))
        db.execute = AsyncMock(return_value=scal)

        out = await sig.corroborate_identity(db, "1.2.3.4", "a@acme.com")
        assert out == pytest.approx(0.6, rel=1e-3)  # best (freshest) signal
        # HARD INVARIANT: corroboration performs zero writes.
        db.add.assert_not_called()
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_none_when_no_signals(self):
        db = _mock_db()
        scal = MagicMock()
        scal.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        db.execute = AsyncMock(return_value=scal)
        assert await sig.corroborate_identity(db, "1.2.3.4", "a@acme.com") is None

    def test_module_has_no_identified_visitor_write_import(self):
        """Structural guard: the module must not import _save_identified or any
        IdentifiedVisitor write path — corroboration is read-only by design."""
        import inspect

        src = inspect.getsource(sig)
        # No import of the resolver / its write helper (docstring prose is fine;
        # check for actual code: a call to _save_identified(, an import line).
        assert "identity_resolver" not in src
        assert "_save_identified(" not in src
        # IdentifiedVisitor may appear only in a read-only SELECT for the gate,
        # never in a write (add/insert/update).
        assert "db.add(IdentifiedVisitor" not in src
        assert "insert(IdentifiedVisitor" not in src
        assert "update(IdentifiedVisitor" not in src
