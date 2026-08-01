"""Handoff Detection H3 — intent-signal unit tests (Fully-Automated gates).

Covers AC-H3-1 (commercial-page classification + live alert trigger/dedup/copy),
AC-H3-2 (spike detection), AC-H3-3 (company-correlation is read-only metadata,
no outreach write path), AC-H3-4 (alert copy is SITE-level only + HTML-escaped,
correlation query is site-scoped). No DB, no Docker — pure functions + mocked
Redis/EmailSender, plus C5-style literal-field-name tripwires mirroring
tests/unit/test_handoff_emailability_separation.py.
"""

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import apps.api.main  # noqa: F401 — registers ALL ORM models (mapper config).
from apps.api.services.agent_intent_signals import (
    COMMERCIAL_PAGE_PREFIXES,
    detect_spike,
    is_commercial_page,
)

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]


# --- AC-H3-1 precondition: commercial-page classification --------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/pricing", True),           # exact match
        ("/pricing/enterprise", True),  # sub-path
        ("/pricing/", True),          # trailing slash normalized
        ("/PRICING", True),           # case-insensitive
        ("/vs/competitor", True),     # another prefix, sub-path
        ("/demo", True),
        ("/pricing-blog", False),     # FALSE-POSITIVE GUARD — no "/" boundary
        ("/pricingx", False),         # no boundary
        ("/blog", False),
        ("/", False),                 # empty after rstrip
        ("", False),
        (None, False),                # no path
    ],
)
def test_is_commercial_page(path, expected):
    assert is_commercial_page(path) is expected


def test_commercial_prefixes_are_the_locked_seven():
    assert COMMERCIAL_PAGE_PREFIXES == frozenset(
        {"/pricing", "/demo", "/signup", "/compare", "/vs", "/plans", "/trial"}
    )


# --- AC-H3-2: spike detection (floor-then-multiplier) ------------------------


def test_detect_spike():
    # Floor case: 2 hits over a 0 baseline → floor (>=3) unmet → NOT a spike.
    assert detect_spike(2, 0.0) is False
    # Multiplier case: 3 hits over a 1.0/day avg → floor met AND 3 >= 2*1 → spike.
    assert detect_spike(3, 1.0) is True
    # Zero-baseline floor case: 3 hits over a 0 baseline → floor met, 3 >= 0 → spike.
    assert detect_spike(3, 0.0) is True
    # Floor met but under the 2x multiplier → NOT a spike.
    assert detect_spike(3, 2.0) is False
    # Comfortably above both → spike.
    assert detect_spike(10, 2.0) is True


# --- AC-H3-1 / AC-H3-4: alert trigger, dedup, SITE-level copy, escaping ------


def _fake_site(enabled=True, name="Acme"):
    site = MagicMock()
    site.hot_alert_enabled = enabled
    site.site_id = "site-1"
    site.user_id = uuid.uuid4()
    site.name = name
    return site


def _fake_db_with_owner(email="owner@example.com"):
    owner = MagicMock()
    owner.email = email
    result = MagicMock()
    result.scalar_one_or_none.return_value = owner
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


class _FakeRedis:
    """In-memory NX/EX SET so dedup behaves like real Redis for the test."""

    def __init__(self):
        self._store: dict[str, str] = {}

    async def set(self, key, val, nx=False, ex=None):
        if nx and key in self._store:
            return None
        self._store[key] = val
        return True


@pytest.fixture
def _patched_alert(monkeypatch):
    """Patch hot_alert's get_redis + EmailSender; capture sent emails."""
    from apps.api.services import hot_alert

    sent: list[dict] = []
    fake_redis = _FakeRedis()

    monkeypatch.setattr(hot_alert, "get_redis", lambda: fake_redis)

    class _FakeSender:
        async def send(self, **kwargs):
            sent.append(kwargs)

    monkeypatch.setattr(hot_alert, "EmailSender", _FakeSender)
    return hot_alert, sent


async def test_commercial_page_triggers_alert(_patched_alert):
    hot_alert, sent = _patched_alert
    db = _fake_db_with_owner()

    ok = await hot_alert.maybe_send_intent_alert(
        db, site=_fake_site(), page_path="/pricing", vendor="openai",
        hit_count=5, window_minutes=1440,
    )
    assert ok is True
    assert len(sent) == 1

    # Dedup: same (site, page) within TTL → suppressed, no second email.
    ok2 = await hot_alert.maybe_send_intent_alert(
        db, site=_fake_site(), page_path="/pricing", vendor="openai",
        hit_count=6, window_minutes=1440,
    )
    assert ok2 is False
    assert len(sent) == 1


async def test_intent_alert_gated_on_hot_alert_enabled(_patched_alert):
    hot_alert, sent = _patched_alert
    db = _fake_db_with_owner()
    ok = await hot_alert.maybe_send_intent_alert(
        db, site=_fake_site(enabled=False), page_path="/pricing",
        vendor="openai", hit_count=5, window_minutes=1440,
    )
    assert ok is False
    assert sent == []


async def test_spike_alert_uses_separate_dedup_key(_patched_alert):
    # A baseline alert AND a spike alert for the same page in the same day can
    # both fire (separate dedup scopes) — spike is additive, not deduped out.
    hot_alert, sent = _patched_alert
    db = _fake_db_with_owner()
    await hot_alert.maybe_send_intent_alert(
        db, site=_fake_site(), page_path="/pricing", vendor="openai",
        hit_count=5, window_minutes=1440,
    )
    await hot_alert.maybe_send_intent_alert(
        db, site=_fake_site(), page_path="/pricing", vendor="openai",
        hit_count=5, window_minutes=1440, is_spike=True, multiplier=3.0,
    )
    assert len(sent) == 2
    assert "spike" in sent[1]["body_html"].lower()


async def test_intent_alert_copy_is_site_level_only(_patched_alert):
    hot_alert, sent = _patched_alert
    db = _fake_db_with_owner(email="owner@example.com")

    # Malicious page_path with HTML metacharacters — must be escaped, not raw.
    await hot_alert.maybe_send_intent_alert(
        db, site=_fake_site(name="Acme"), page_path="/pricing<script>",
        vendor="openai", hit_count=5, window_minutes=1440,
    )
    body = sent[0]["body_html"]

    # SITE-level content present.
    assert "openai" in body
    assert "Acme" in body
    assert "5" in body

    # NO person-level identifier tokens — not the owner's email, no person name.
    assert "owner@example.com" not in body
    assert "@" not in body  # no email address anywhere in the copy

    # HTML-escaping (PVL correction): the injected tag is escaped, never raw.
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


# --- AC-H3-4 site-scoping + AC-H3-3 read-only fallback -----------------------


async def test_correlation_returns_empty_when_company_graph_disabled(monkeypatch):
    from apps.api.services import agent_aggregator

    monkeypatch.setattr(
        agent_aggregator.settings, "company_graph_enabled", False
    )
    db = MagicMock()
    db.execute = AsyncMock()  # must NOT be called on the fallback path.

    out = await agent_aggregator.fetch_recent_ai_researched_companies(db, "site-1")
    assert out == []
    db.execute.assert_not_awaited()


def test_correlation_query_is_site_scoped():
    # Structural tripwire: the correlation fetch enforces site scoping on BOTH the
    # agent-fetch side and the company side (AC-H3-4). CompanyGraphNode is
    # cross-tenant, so the Company.site_id filter is what isolates the tenant.
    src = (_REPO_ROOT / "apps/api/services/agent_aggregator.py").read_text(encoding="utf-8")
    assert "AgentFetchEvent.site_id == site_id" in src
    assert "Company.site_id == site_id" in src


# --- AC-H3-3: company-correlation is metadata-only (C5-style tripwire) -------

_H3_FILES = [
    "apps/api/services/agent_intent_signals.py",
    "apps/api/services/agent_aggregator.py",
]

_OUTREACH_WRITE_TERMS = ["Campaign(", "Segment(", "CampaignRecipient(", "Draft("]


@pytest.mark.parametrize("rel_path", _H3_FILES)
def test_company_correlation_is_metadata_only(rel_path):
    # No write path from the H3 intent/correlation surface into any campaign,
    # segment, or outreach table. Pure text tripwire — a future edit that wires a
    # write in fails loudly instead of silently coupling intent signals to sends.
    text = (_REPO_ROOT / rel_path).read_text(encoding="utf-8")
    for term in _OUTREACH_WRITE_TERMS:
        assert term not in text, (
            f"{rel_path} constructs '{term}' — the H3 intent-signal surface must "
            "stay read-only metadata (AC-H3-3), never a write path into outreach."
        )


def test_recent_ai_research_entry_is_not_a_db_table():
    # The correlation entry is a pydantic BaseModel, never persisted to a table.
    from apps.api.schemas.agents import RecentAiResearchEntry

    assert not hasattr(RecentAiResearchEntry, "__tablename__")
    assert not hasattr(RecentAiResearchEntry, "__table__")


def test_correlation_field_absent_from_outreach_agents():
    # The intent/correlation field must not leak into the segmenter/planner — they
    # never read Company today, and must not start reading the AI-research signal.
    for rel_path in (
        "apps/api/agents/segmenter.py",
        "apps/api/agents/campaign_planner.py",
    ):
        text = (_REPO_ROOT / rel_path).read_text(encoding="utf-8")
        assert "recent_ai_researched" not in text
