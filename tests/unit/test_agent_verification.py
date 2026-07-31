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


@pytest.fixture
def empty_runtime_dir(monkeypatch, tmp_path):
    """Point the real branch's runtime dataset at an empty directory.

    The refresh job writes real CIDRs into ``_RUNTIME_DIR`` (gitignored), and the
    real branch reads it before the shipped placeholders. A real-branch test that
    does not redirect it asserts against whatever that job last wrote, so it
    passes on a clean checkout and fails on any machine where the job has run.
    Redirecting to an empty dir makes the shipped placeholder the only input,
    which is what these tests are actually about.
    """
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setattr(agent_verification, "_RUNTIME_DIR", runtime)
    return runtime


# ─── verify_ip ───────────────────────────────────────────────────────────────


def test_verify_ip_matches_mock_cidr_returns_ip_verified(mock_mode):
    assert agent_verification.verify_ip("gptbot", "10.99.0.5") == "ip-verified"


def test_verify_ip_outside_published_ranges_is_a_mismatch(mock_mode):
    """A UA claiming a vendor that publishes ranges, from an IP in none of them,
    is what a forged User-Agent looks like — and it has to be distinguishable
    from "not checked yet"."""
    assert agent_verification.verify_ip("gptbot", "8.8.8.8") == "ip-mismatch"


def test_verify_ip_anthropic_is_never_judged(mock_mode):
    # Structural ceiling: no anthropic dataset entry exists. It must return None
    # (no conclusion), NEVER "ip-mismatch" — absence of published ranges is not
    # evidence of forgery, and conflating them would invent evidence.
    assert agent_verification.verify_ip("claudebot", "10.99.0.5") is None
    assert agent_verification.verify_ip("claudebot", "8.8.8.8") is None


def test_verify_ip_malformed_ip_returns_none(mock_mode):
    assert agent_verification.verify_ip("gptbot", "not-an-ip") is None
    assert agent_verification.verify_ip("gptbot", "") is None


def test_verify_ip_malformed_cidr_returns_none(monkeypatch):
    # A malformed CIDR entry must be skipped, never raise.
    monkeypatch.setattr(
        agent_verification,
        "load_ip_ranges",
        lambda: {"gptbot": ["garbage/99", "10.99.0.0/24"]},
    )
    # Still matches the valid entry after skipping the malformed one.
    assert agent_verification.verify_ip("gptbot", "10.99.0.5") == "ip-verified"
    # And a non-matching IP with only a malformed CIDR present → None, no raise.
    # Only a malformed CIDR present → nothing was really checked, so the verdict
    # must be "no conclusion", never a mismatch.
    monkeypatch.setattr(
        agent_verification, "load_ip_ranges", lambda: {"gptbot": ["garbage/99"]}
    )
    assert agent_verification.verify_ip("gptbot", "10.99.0.5") is None


# ─── load_ip_ranges ──────────────────────────────────────────────────────────


def test_load_ip_ranges_is_keyed_per_agent_not_per_vendor(mock_mode):
    """OpenAI publishes a separate document per agent. Keeping them apart is what
    makes "GPTBot arrived on ChatGPT-User's range" observable; a merged per-vendor
    set would silently answer "yes, that's OpenAI" and lose the anomaly."""
    ranges = agent_verification.load_ip_ranges()
    assert ranges.get("gptbot") == ["10.99.0.0/16"]
    assert ranges.get("chatgpt-user") == ["10.99.0.0/16"]
    assert "openai" not in ranges  # never a merged vendor bucket
    assert "claudebot" not in ranges  # Anthropic publishes nothing


def test_load_ip_ranges_real_branch_is_empty_until_refreshed(
    monkeypatch, empty_runtime_dir
):
    """The shipped datasets are placeholders — real ranges arrive from the
    refresh job. Empty must mean "no conclusion", so an unfetched agent is
    dropped from the mapping entirely rather than presenting an empty range list
    that would read as "checked, matched nothing"."""
    monkeypatch.setattr(settings, "mock_external_apis", False)
    ranges = agent_verification.load_ip_ranges()
    assert ranges == {}
    assert agent_verification.verify_ip("gptbot", "8.8.8.8") is None


def test_load_ip_ranges_fail_open_on_load_error(monkeypatch):
    # Point BOTH dataset dirs at nonexistent paths → every vendor file missing →
    # fail-open empty dict, no raise. The runtime dir is read first on the real
    # branch, so leaving it live would test the refresh job's output instead of
    # the missing-file path.
    from pathlib import Path

    monkeypatch.setattr(
        agent_verification, "_DATA_DIR", Path("/nonexistent/agent_ip_ranges")
    )
    monkeypatch.setattr(
        agent_verification, "_RUNTIME_DIR", Path("/nonexistent/agent_ip_ranges/runtime")
    )
    monkeypatch.setattr(settings, "mock_external_apis", False)
    assert agent_verification.load_ip_ranges() == {}


# ─── run_verification_sweep (mocked AsyncSession, per-row fail-open) ──────────


@pytest.mark.asyncio
async def test_run_verification_sweep_isolates_per_row_failure(mock_mode, monkeypatch):
    # Three fake rows: one gptbot match, one Anthropic token (never judged --
    # not even reached by the token filter, included to prove verify_ip → None),
    # one gptbot whose write call is forced to raise. Sweep must complete
    # without raising and still process the other rows.
    good = SimpleNamespace(
        id=uuid.uuid4(), product_or_ua_token="gptbot", ip_address="10.99.0.5",
    )
    anthro = SimpleNamespace(
        id=uuid.uuid4(), product_or_ua_token="claudebot", ip_address="10.99.0.5",
    )
    boom = SimpleNamespace(
        id=uuid.uuid4(), product_or_ua_token="gptbot", ip_address="10.99.0.9",
    )

    db = MagicMock(spec_set=["execute"])
    result = MagicMock()
    result.scalars.return_value.all.return_value = [good, anthro, boom]
    db.execute = AsyncMock(return_value=result)

    calls: list = []

    async def fake_set(_db, row_id, method):
        calls.append((row_id, method))
        if row_id == boom.id:
            raise RuntimeError("simulated per-row upgrade failure")

    monkeypatch.setattr(agent_verification, "set_verification_method", fake_set)

    # Must not raise despite the boom row failing.
    await agent_verification.run_verification_sweep(db)

    # good + boom both matched gptbot's mock CIDR → both attempted; anthropic
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
