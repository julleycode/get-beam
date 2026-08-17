"""AC-3 / AC-9 / AC-10 / AC-13 / AC-14: benchmark shape and safety assertions.

Structural gates that do not need a database:

* the `campaign_benchmarks` model exposes NO tenant-identifying column;
* no new module reaches `send_campaign_emails` (the send path stays read-only);
* `apps/api/services/auto_drafter.py` is unmodified and unimported (it is a
  SOCIAL-reply drafter — campaign metrics there would be a category error);
* no benchmark surface computes a period-over-period delta;
* `/outcomes` kept its grouped-aggregate shape through the campaign_stats
  refactor (no row materialization, per-campaign grouping, `conv_rows` intact).
"""

import ast
import pathlib
import re

import pytest

import apps.api.main  # noqa: F401 — configures the SQLAlchemy mapper registry
from apps.api.models.campaign_benchmark import CampaignBenchmark
from apps.api.services.campaign_benchmark import BENCHMARK_K_FLOOR

pytestmark = pytest.mark.unit


def _code_only(path: pathlib.Path) -> str:
    """Source with docstrings and `#` comments stripped.

    These gates assert what the code DOES. Prose that merely explains a rule
    (e.g. a docstring saying "never a median") must not satisfy — or trip — a
    behavioral assertion.
    """
    source = path.read_text()
    source = re.sub(r'"""(?:.|\n)*?"""', '""', source)
    source = re.sub(r"'''(?:.|\n)*?'''", "''", source)
    return "\n".join(line.split("#", 1)[0] for line in source.splitlines())

_REPO = pathlib.Path(__file__).resolve().parents[2]
_API = _REPO / "apps" / "api"

# The modules this phase added or edited that could publish benchmark numbers.
_BENCHMARK_SURFACES = (
    _API / "services" / "campaign_benchmark.py",
    _API / "services" / "campaign_stats.py",
    _API / "services" / "outcome_digest.py",
    _API / "routers" / "outcomes.py",
)
_NEW_MODULES = (
    _API / "services" / "campaign_benchmark.py",
    _API / "services" / "campaign_stats.py",
    _API / "models" / "campaign_benchmark.py",
)


# ── AC-3: zero-PII schema shape ──


def test_benchmark_table_exposes_no_tenant_identifying_column():
    names = {c.name for c in CampaignBenchmark.__table__.columns}
    assert names == {
        "id",
        "category_normalized",
        "period",
        "sends",
        "opens",
        "clicks",
        "conversions",
        "site_count",
        "created_at",
        "updated_at",
    }
    forbidden = ("site", "visitor", "email", "user", "ip", "domain", "company")
    offenders = [n for n in names if any(f in n for f in forbidden)]
    # site_count is a pooled anonymity parameter, not a site reference.
    assert offenders == ["site_count"]


def test_benchmark_table_has_no_foreign_keys():
    # A FK would be a tenant reference by another name.
    assert not any(c.foreign_keys for c in CampaignBenchmark.__table__.columns)


def test_benchmark_row_round_trips_with_no_tenant_identifying_value():
    row = CampaignBenchmark(
        category_normalized="saas",
        period="2026-W33",
        sends=100,
        opens=20,
        clicks=5,
        conversions=2,
        site_count=7,
    )
    values = {
        c.name: getattr(row, c.name, None) for c in CampaignBenchmark.__table__.columns
    }
    assert values["category_normalized"] == "saas"
    # Everything persisted is an int, a closed-vocabulary token, or a period
    # label — no free text from a tenant anywhere.
    assert all(
        isinstance(v, (int, type(None))) or k in ("category_normalized", "period")
        for k, v in values.items()
    )


def test_k_floor_is_at_least_five():
    assert BENCHMARK_K_FLOOR >= 5


# ── AC-10: the send path stays read-only ──


def test_new_modules_never_reference_send_campaign_emails():
    for path in _NEW_MODULES:
        assert "send_campaign_emails" not in path.read_text(), path


def test_campaign_planner_stat_injection_does_not_reach_the_send_path():
    source = _code_only(_API / "agents" / "campaign_planner.py")
    assert "send_campaign_emails" not in source
    assert "campaign_sender" not in source


# ── AC-9: auto_drafter is excluded by design ──


def test_auto_drafter_lives_under_services_and_is_unimported_by_new_modules():
    drafter = _API / "services" / "auto_drafter.py"
    # Path assertion is load-bearing: a gate globbing apps/api/agents/
    # auto_drafter.py would be vacuously green — no such file exists.
    assert drafter.exists()
    assert not (_API / "agents" / "auto_drafter.py").exists()
    for path in _NEW_MODULES:
        assert "auto_drafter" not in path.read_text(), path


def test_auto_drafter_contains_no_campaign_benchmark_injection():
    source = (_API / "services" / "auto_drafter.py").read_text()
    for token in ("campaign_stats", "campaign_benchmark", "OPEN_RATE_CAVEAT"):
        assert token not in source


# ── AC-14: no period-over-period differencing anywhere ──

_DELTA_TOKENS = (
    "previous_period",
    "prior_period",
    "period_delta",
    "period_over_period",
    "last_period",
    "vs_last_week",
    "week_over_week",
    "delta_pct",
)


def test_no_benchmark_surface_computes_a_period_over_period_delta():
    for path in _BENCHMARK_SURFACES:
        source = path.read_text()
        lowered = source.lower()
        for token in _DELTA_TOKENS:
            assert token not in lowered, f"{path.name} references {token}"
        # AST leg: no subtraction between two benchmark-ish period values.
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
                text = ast.dump(node)
                assert "period" not in text.lower(), f"{path.name}: {text[:120]}"


def test_digest_and_report_never_say_median():
    # D1: the schema supports only a pooled mean. "median" would be a false
    # claim about what the numbers are.
    for path in _BENCHMARK_SURFACES:
        assert not re.search(r"\bmedian\b", _code_only(path), re.I), path.name


# ── AC-13: /outcomes kept its aggregate shape ──


def test_outcomes_imports_the_shared_predicate_set():
    source = (_API / "routers" / "outcomes.py").read_text()
    for expr in ("sent_count_expr", "opened_count_expr", "clicked_count_expr"):
        assert expr in source
    # The predicates now live in exactly one place.
    assert "CampaignTouchpoint.opened_at.is_not(None)" not in source


def test_outcomes_preserves_grouped_aggregate_shape_and_conv_rows():
    source = (_API / "routers" / "outcomes.py").read_text()
    # No row materialization introduced for the funnel: still grouped in SQL.
    assert "group_by(Campaign.id, Campaign.name)" in source
    # conv_rows is explicitly out of scope of the refactor.
    assert "conv_rows" in source
    assert "func.count(func.distinct(Conversion.visitor_id))" in source
    # /outcomes must never filter on channel — it never has.
    assert 'channel == "email"' not in source
    assert "CampaignTouchpoint.channel" not in source


def test_shared_expressions_reproduce_the_existing_sent_vs_opened_asymmetry():
    source = (_API / "services" / "campaign_stats.py").read_text()
    # `sent` carries the status predicate; opened/clicked deliberately do not.
    assert 'CampaignTouchpoint.status == "sent"' in source
    tree = ast.parse(source)
    fns = {
        n.name: ast.unparse(n)
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef)
    }
    assert 'status ==' in fns["sent_count_expr"]
    assert 'status ==' not in fns["opened_count_expr"]
    assert 'status ==' not in fns["clicked_count_expr"]
    for name in ("sent_count_expr", "opened_count_expr", "clicked_count_expr"):
        assert "sent_at >= cutoff" in fns[name]


# ── C6: write-nothing-when-blocked, and consent-path separation ──


def test_aggregation_reads_only_opted_in_sites_via_the_benchmark_flag():
    source = _code_only(_API / "services" / "campaign_benchmark.py")
    assert "Site.benchmark_contribution_enabled.is_(True)" in source
    # D3 purpose limitation: the identity co-op's consent basis is never read.
    assert "contribution_enabled" in source  # the benchmark one
    assert "Site.contribution_enabled" not in source
    assert "coop_terms_version" not in source
    assert "identity_contribution_consent_acceptances" not in source


def test_site_update_router_keeps_the_coop_consent_block_intact():
    source = (_API / "routers" / "sites.py").read_text()
    # Symbol-anchored (NOT a line range — every line number in this file is
    # stale from concurrent uncommitted work).
    assert "if body.contribution_enabled is not None:" in source
    assert "settings.coop_terms_version" in source
    assert "record_consent_acceptance(" in source
    # And the benchmark flip is a structurally separate, unconditional branch
    # with its own structlog consent audit.
    assert "if body.benchmark_contribution_enabled is not None:" in source
    assert "benchmark_contribution_toggled" in source


def test_benchmark_toggle_audit_logs_no_pii():
    source = (_API / "routers" / "sites.py").read_text()
    start = source.index("benchmark_contribution_toggled")
    block = source[start : start + 300]
    for forbidden in ("email", "visitor", "name="):
        assert forbidden not in block
