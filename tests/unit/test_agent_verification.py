"""Unit tests for EvalLayer Phase 4 IP-range verification (no deps, offline).

Covers pure-logic ``verify_ip``, the fail-open ``load_ip_ranges`` mock/error
branches, and the ``run_verification_sweep`` per-row fail-open isolation using a
mocked ``AsyncSession`` (no real DB, no Docker). Also asserts the hot path
(``routers/events.py``) never imports ``agent_verification``.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.config import settings
from apps.api.services import agent_verification

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_mode(monkeypatch):
    """Force the mock dataset branch (10.99.0.0/24 for openai)."""
    monkeypatch.setattr(settings, "mock_external_apis", True)


# ─── verify_ip ───────────────────────────────────────────────────────────────


def test_verify_ip_matches_mock_cidr_returns_ip_verified(mock_mode):
    assert agent_verification.verify_ip("openai", "10.99.0.5") == "ip-verified"


def test_verify_ip_non_matching_returns_none(mock_mode):
    assert agent_verification.verify_ip("openai", "8.8.8.8") is None


def test_verify_ip_anthropic_always_none(mock_mode):
    # Structural ceiling: no anthropic dataset entry exists, so even an IP that
    # would match openai's mock block returns None for anthropic.
    assert agent_verification.verify_ip("anthropic", "10.99.0.5") is None


def test_verify_ip_malformed_ip_returns_none(mock_mode):
    assert agent_verification.verify_ip("openai", "not-an-ip") is None
    assert agent_verification.verify_ip("openai", "") is None


def test_verify_ip_malformed_cidr_returns_none(monkeypatch):
    # A malformed CIDR entry must be skipped, never raise.
    monkeypatch.setattr(
        agent_verification,
        "load_ip_ranges",
        lambda: {"openai": ["garbage/99", "10.99.0.0/24"]},
    )
    # Still matches the valid entry after skipping the malformed one.
    assert agent_verification.verify_ip("openai", "10.99.0.5") == "ip-verified"
    # And a non-matching IP with only a malformed CIDR present → None, no raise.
    monkeypatch.setattr(
        agent_verification, "load_ip_ranges", lambda: {"openai": ["garbage/99"]}
    )
    assert agent_verification.verify_ip("openai", "10.99.0.5") is None


# ─── load_ip_ranges ──────────────────────────────────────────────────────────


def test_load_ip_ranges_mock_branch(mock_mode):
    ranges = agent_verification.load_ip_ranges()
    assert ranges.get("openai") == ["10.99.0.0/24"]
    assert "anthropic" not in ranges  # structural ceiling


def test_load_ip_ranges_real_branch(monkeypatch):
    monkeypatch.setattr(settings, "mock_external_apis", False)
    ranges = agent_verification.load_ip_ranges()
    # Real dataset present with published ranges; anthropic never present.
    assert ranges.get("openai")
    assert ranges.get("perplexity")
    assert "anthropic" not in ranges


def test_load_ip_ranges_fail_open_on_load_error(monkeypatch):
    # Point the data dir at a nonexistent path → every vendor file missing →
    # fail-open empty dict, no raise.
    from pathlib import Path

    monkeypatch.setattr(
        agent_verification, "_DATA_DIR", Path("/nonexistent/agent_ip_ranges")
    )
    monkeypatch.setattr(settings, "mock_external_apis", False)
    assert agent_verification.load_ip_ranges() == {}


# ─── run_verification_sweep (mocked AsyncSession, per-row fail-open) ──────────


@pytest.mark.asyncio
async def test_run_verification_sweep_isolates_per_row_failure(mock_mode, monkeypatch):
    # Three fake rows: one openai match, one anthropic (structural no-match, not
    # even queried by vendor filter but included here to prove verify_ip → None),
    # one openai whose upgrade call is forced to raise. Sweep must complete
    # without raising and still process the other rows.
    good = SimpleNamespace(
        id=uuid.uuid4(), vendor="openai", ip_address="10.99.0.5",
    )
    anthro = SimpleNamespace(
        id=uuid.uuid4(), vendor="anthropic", ip_address="10.99.0.5",
    )
    boom = SimpleNamespace(
        id=uuid.uuid4(), vendor="openai", ip_address="10.99.0.9",
    )

    db = MagicMock(spec_set=["execute"])
    result = MagicMock()
    result.scalars.return_value.all.return_value = [good, anthro, boom]
    db.execute = AsyncMock(return_value=result)

    calls: list = []

    async def fake_upgrade(_db, row_id, method):
        calls.append((row_id, method))
        if row_id == boom.id:
            raise RuntimeError("simulated per-row upgrade failure")

    monkeypatch.setattr(agent_verification, "upgrade_verification_method", fake_upgrade)

    # Must not raise despite the boom row failing.
    await agent_verification.run_verification_sweep(db)

    # good + boom both matched openai's mock CIDR → both attempted; anthropic
    # never upgraded (structural ceiling).
    upgraded_ids = {c[0] for c in calls}
    assert good.id in upgraded_ids
    assert boom.id in upgraded_ids
    assert anthro.id not in upgraded_ids
    assert all(c[1] == "ip-verified" for c in calls)


# ─── static-safety: hot path never imports agent_verification ────────────────


def test_events_router_does_not_import_agent_verification():
    from pathlib import Path

    events_path = (
        Path(agent_verification.__file__).resolve().parent.parent
        / "routers"
        / "events.py"
    )
    source = events_path.read_text(encoding="utf-8")
    assert "agent_verification" not in source
