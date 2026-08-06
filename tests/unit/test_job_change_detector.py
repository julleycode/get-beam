"""Unit tests for job-change detection pure logic + safety gates (v1, same-tenant).

Structural template: tests/unit/test_identity_signals.py — the 4-gate shape
(datacenter IP / proxy-VPN / suppression / do_not_resolve) is deliberately
mirrored so the two gate implementations stay testably consistent.

Covers SPEC AC-5 (compare_company), AC-6 (corroborate), AC-13 (do_not_resolve
excluded), AC-14 (no plaintext-email column) and the Redis budget counter (AC-4
unit half; the isolation half is an integration test).
"""

import pytest

# Registers every ORM mapper before any model class is constructed. Without this
# SQLAlchemy raises InvalidRequestError on the first Visitor() below.
import apps.api.main  # noqa: F401

from apps.api.models.job_change_event import JobChangeEvent
from apps.api.models.visitor import Visitor
from apps.api.services import job_change_detector as jcd

pytestmark = pytest.mark.unit


# ─────────────────────────── AC-5: compare_company ───────────────────────────


@pytest.mark.parametrize(
    "prior,new",
    [
        ("Acme Inc.", "Acme, Inc"),
        ("Acme Inc", "ACME INC."),
        ("  Acme Corp  ", "Acme Corporation"),
        ("Beam LLC", "beam llc"),
        ("Foo Ltd.", "Foo Limited"),
        ("Bar Co", "Bar Co."),
    ],
)
def test_compare_company_normalization_equivalent_pairs_not_flagged(prior, new):
    """Normalization-equivalent pairs must NOT be reported as a job change."""
    assert jcd.compare_company(prior, new) is False


@pytest.mark.parametrize(
    "prior,new",
    [
        ("Acme Inc.", "Globex Inc."),
        ("Acme", "Acme Labs"),
        ("Beam", "Retention"),
    ],
)
def test_compare_company_normalization_real_differences_flagged(prior, new):
    """A genuinely different employer must be reported as a change."""
    assert jcd.compare_company(prior, new) is True


@pytest.mark.parametrize("prior,new", [(None, "Acme"), ("Acme", None), (None, None), ("", "Acme"), ("Acme", "")])
def test_compare_company_missing_side_is_never_a_change(prior, new):
    """A missing side is a first-time enrichment, not a job change."""
    assert jcd.compare_company(prior, new) is False


# ──────────────────────────── AC-6: corroborate ─────────────────────────────


def test_corroborate_high_confidence_with_work_email_domain_passes():
    passes, confidence, signal = jcd.corroborate(
        source="pdl", work_email_domain="acme.com", company_graph_hit=False
    )
    assert passes is True
    assert confidence >= 0.5
    assert signal == "work_email_domain"


def test_corroborate_high_confidence_with_company_graph_hit_passes():
    passes, confidence, signal = jcd.corroborate(
        source="pdl", work_email_domain=None, company_graph_hit=True
    )
    assert passes is True
    assert signal == "company_graph_ip"


def test_corroborate_both_signals_reports_both():
    passes, _, signal = jcd.corroborate(
        source="pdl", work_email_domain="acme.com", company_graph_hit=True
    )
    assert passes is True
    assert signal == "work_email_domain+company_graph_ip"


def test_corroborate_low_confidence_source_rejected():
    """Domain-fallback-only confidence sits below the gate threshold."""
    passes, confidence, _ = jcd.corroborate(
        source="domain_fallback", work_email_domain="acme.com", company_graph_hit=True
    )
    assert passes is False
    assert confidence < 0.5


def test_corroborate_personal_email_only_always_rejected():
    """AC-6 hard rule: a personal mailbox with no other signal never confirms,
    regardless of how confident the provider is."""
    passes, confidence, _ = jcd.corroborate(
        source="pdl", work_email_domain="gmail.com", company_graph_hit=False
    )
    assert passes is False
    # The rejection is structural, not a threshold artefact: confidence is high.
    assert confidence >= 0.5


def test_corroborate_no_signal_at_all_rejected():
    passes, _, _ = jcd.corroborate(
        source="pdl", work_email_domain=None, company_graph_hit=False
    )
    assert passes is False


def test_corroborate_unknown_source_rejected():
    passes, confidence, _ = jcd.corroborate(
        source="nonsense", work_email_domain="acme.com", company_graph_hit=True
    )
    assert passes is False
    assert confidence == 0.0


# ───────────────────── 4 safety gates (AC-13 + siblings) ─────────────────────


def _visitor(**kw) -> Visitor:
    defaults = dict(
        site_id="site_1",
        visitor_id="v_1",
        ip_address="8.8.8.8",
        do_not_resolve=False,
    )
    defaults.update(kw)
    return Visitor(**defaults)


class _FakeDB:
    """Stand-in AsyncSession — the gate helpers only pass it through."""


@pytest.fixture
def gate_stubs(monkeypatch):
    """All 4 gates open by default; each test closes exactly one."""
    async def _not_datacenter(ip):
        return False

    async def _privacy(ip):
        return {}

    def _not_proxy(privacy):
        return False

    async def _not_suppressed(db, email, scope):
        return False

    monkeypatch.setattr(jcd, "is_datacenter_ip", _not_datacenter)
    monkeypatch.setattr(jcd, "check_ip_privacy", _privacy)
    monkeypatch.setattr(jcd, "is_proxy_or_vpn", _not_proxy)
    monkeypatch.setattr(jcd, "is_email_suppressed", _not_suppressed)
    return monkeypatch


async def test_gates_pass_when_all_clear(gate_stubs):
    assert await jcd._passes_recheck_gates(_FakeDB(), _visitor(), "a@acme.com") is True


async def test_rejects_datacenter_ip(gate_stubs):
    async def _yes(ip):
        return True

    gate_stubs.setattr(jcd, "is_datacenter_ip", _yes)
    assert await jcd._passes_recheck_gates(_FakeDB(), _visitor(), "a@acme.com") is False


async def test_rejects_proxy_vpn(gate_stubs):
    gate_stubs.setattr(jcd, "is_proxy_or_vpn", lambda privacy: True)
    assert await jcd._passes_recheck_gates(_FakeDB(), _visitor(), "a@acme.com") is False


async def test_rejects_suppressed_email(gate_stubs):
    async def _yes(db, email, scope):
        return True

    gate_stubs.setattr(jcd, "is_email_suppressed", _yes)
    assert await jcd._passes_recheck_gates(_FakeDB(), _visitor(), "a@acme.com") is False


async def test_do_not_resolve_excluded(gate_stubs):
    """AC-13: the same opt-out guard as first-time identification, no weaker
    rule for re-checks."""
    v = _visitor(do_not_resolve=True)
    assert await jcd._passes_recheck_gates(_FakeDB(), v, "a@acme.com") is False


async def test_gates_never_raise_on_provider_error(gate_stubs):
    """A gate lookup blowing up must fail CLOSED and never propagate — a
    re-check may never break the calling event/task path."""
    async def _boom(ip):
        raise RuntimeError("ipinfo down")

    gate_stubs.setattr(jcd, "is_datacenter_ip", _boom)
    assert await jcd._passes_recheck_gates(_FakeDB(), _visitor(), "a@acme.com") is False


# ───────────────────────── AC-4 (unit half): budget ─────────────────────────


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, int] = {}
        self.expires: dict[str, int] = {}

    async def get(self, key):
        return self.store.get(key)

    async def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def decr(self, key):
        self.store[key] = self.store.get(key, 0) - 1
        return self.store[key]

    async def expire(self, key, ttl):
        self.expires[key] = ttl


async def test_budget_allows_until_cap_then_refuses(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(jcd, "get_redis", lambda: fake)
    monkeypatch.setattr(jcd.settings, "job_change_recheck_daily_cap", 3)

    assert [await jcd.check_job_change_recheck_budget("site_1") for _ in range(3)] == [
        True,
        True,
        True,
    ]
    assert await jcd.check_job_change_recheck_budget("site_1") is False
    # Refusal must not keep inflating the counter.
    key = jcd._recheck_count_key("site_1")
    assert fake.store[key] == 3


async def test_budget_sets_self_expiring_ttl_on_first_increment(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(jcd, "get_redis", lambda: fake)
    monkeypatch.setattr(jcd.settings, "job_change_recheck_daily_cap", 10)

    await jcd.check_job_change_recheck_budget("site_1")
    assert fake.expires[jcd._recheck_count_key("site_1")] == 2 * 86400


async def test_budget_is_per_site(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(jcd, "get_redis", lambda: fake)
    monkeypatch.setattr(jcd.settings, "job_change_recheck_daily_cap", 1)

    assert await jcd.check_job_change_recheck_budget("site_a") is True
    assert await jcd.check_job_change_recheck_budget("site_b") is True
    assert await jcd.check_job_change_recheck_budget("site_a") is False


async def test_budget_key_shape_is_site_and_utc_day():
    key = jcd._recheck_count_key("site_1")
    assert key.startswith("job_change_recheck:site_1:")


async def test_budget_fails_closed_on_redis_error(monkeypatch):
    """A Redis outage must NOT open the spend gate — every recheck costs a paid
    provider call, so an unreadable counter means 'refuse', not 'allow'."""
    class _Broken:
        async def incr(self, key):
            raise RuntimeError("redis down")

    monkeypatch.setattr(jcd, "get_redis", lambda: _Broken())
    assert await jcd.check_job_change_recheck_budget("site_1") is False


# ─────────────────────────── AC-14: no plaintext PII ─────────────────────────


def test_no_plaintext_email_column():
    """AC-14: JobChangeEvent must carry no email/name-shaped column."""
    names = {c.name for c in JobChangeEvent.__table__.columns}
    forbidden_substrings = ("email", "full_name", "first_name", "last_name", "phone")
    offenders = [n for n in names if any(s in n for s in forbidden_substrings)]
    assert offenders == [], f"PII-shaped columns on job_change_events: {offenders}"


def test_job_change_event_references_person_by_id_only():
    names = {c.name for c in JobChangeEvent.__table__.columns}
    assert {"site_id", "visitor_id"} <= names


def test_site_visitor_index_is_not_unique():
    """A visitor may legitimately change jobs more than once (AC-7)."""
    idx = {i.name: i for i in JobChangeEvent.__table__.indexes}
    assert idx["idx_job_change_site_visitor"].unique is False


def test_detector_module_never_imports_beam_identity_graph():
    """AC-11 static half: no beam_identity_graph import exists in this module.

    Comments/docstrings may NAME the table (they explain the invariant); what
    must not exist is an actual import of a graph read/write path — the same
    "structurally cannot" enforcement identity_signals.py uses for
    IdentifiedVisitor writes."""
    import inspect

    code_lines = [
        ln
        for ln in inspect.getsource(jcd).splitlines()
        if ln.strip().startswith(("import ", "from "))
    ]
    offenders = [ln for ln in code_lines if "beam_identity" in ln.lower()]
    assert offenders == [], f"beam_identity_graph import found: {offenders}"
