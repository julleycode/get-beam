"""Unit tests for the cadence bot flag (AC-1, AC-2, AC-3, AC-5, AC-11, AC-12, AC-13).

Pure logic + AST-level structural checks. Proves the two-signal conjunction, the
sample-size preconditions, the OFF-by-default gate, the settings-sourced
thresholds, the structural isolation from is_abuse_flagged/agent_visits, and the
no-PII-in-logs guarantee.

Mirrors tests/unit/test_ingest_velocity.py (pure-logic style) and
tests/unit/test_ingest_abuse_no_pii_logging.py (AST log-site reflection).
"""

import ast
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from apps.api.services.cadence_bot_flag import (
    compute_cadence_variance,
    compute_engagement_ratio,
    evaluate_cadence_bot_flag,
)

pytestmark = pytest.mark.unit

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PURE_MODULE = _REPO_ROOT / "apps/api/services/cadence_bot_flag.py"
_SWEEP_MODULE = _REPO_ROOT / "apps/api/services/cadence_bot_flag_sweep.py"

_BASE = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)


def _cron_like_series(n: int = 10) -> list[datetime]:
    """Near-identical 24h gaps — what a daily cron job produces."""
    return [_BASE + timedelta(days=i, seconds=(i % 3)) for i in range(n)]


def _organic_series() -> list[datetime]:
    """Human jitter: irregular gaps of hours-to-days."""
    offsets_hours = [0, 5, 31, 33, 100, 101, 260, 400, 405, 900]
    return [_BASE + timedelta(hours=h) for h in offsets_hours]


# ─── AC-1: cadence variance ───


def test_compute_cadence_variance_cron_like():
    variance = compute_cadence_variance(_cron_like_series())
    assert variance is not None
    assert variance < 0.01, f"cron-like series should have near-zero CV, got {variance}"


def test_compute_cadence_variance_organic():
    variance = compute_cadence_variance(_organic_series())
    assert variance is not None
    assert variance > 0.15, f"organic series should have high CV, got {variance}"


@pytest.mark.parametrize("count", [0, 1, 2])
def test_compute_cadence_variance_insufficient_data(count):
    """Fewer than 2 computable gaps -> None (sample-size floor)."""
    assert compute_cadence_variance(_cron_like_series(count)) is None


def test_compute_cadence_variance_identical_timestamps_is_none():
    """A zero mean gap is not a cadence — never divide by zero."""
    assert compute_cadence_variance([_BASE, _BASE, _BASE, _BASE]) is None


def test_compute_cadence_variance_is_order_independent():
    ordered = _cron_like_series()
    shuffled = [ordered[3], ordered[0], ordered[7], ordered[1], *ordered[4:7], ordered[2]]
    assert compute_cadence_variance(shuffled) == pytest.approx(
        compute_cadence_variance(sorted(shuffled))
    )


# ─── AC-2: engagement ratio ───


def test_compute_engagement_ratio_pageview_only():
    assert compute_engagement_ratio(["pageview"] * 20) == 0.0


def test_compute_engagement_ratio_mixed():
    events = ["pageview", "pageview", "click", "scroll"]
    assert compute_engagement_ratio(events) == pytest.approx(0.5)


def test_compute_engagement_ratio_empty_never_divides_by_zero():
    assert compute_engagement_ratio([]) == 0.0


# ─── AC-3: conjunction-only decision ───


@pytest.mark.parametrize(
    "quadrant,variance,engagement_ratio,expected",
    [
        ("rigid + low-engagement", 0.02, 0.00, True),
        ("rigid + engaged", 0.02, 0.40, False),
        ("irregular + low-engagement", 0.90, 0.00, False),
        ("irregular + engaged", 0.90, 0.40, False),
    ],
)
def test_evaluate_quadrant_matrix(quadrant, variance, engagement_ratio, expected):
    """ONLY the rigid-cadence + low-engagement quadrant flags."""
    assert (
        evaluate_cadence_bot_flag(
            variance,
            engagement_ratio,
            min_visits_met=True,
            max_variance_threshold=0.15,
            max_engagement_ratio=0.05,
        )
        is expected
    ), f"quadrant {quadrant} decided wrongly"


# ─── AC-13: false-positive guard ───


def test_rigid_engaged_power_user_not_flagged():
    """A human who checks the site every morning AND actually reads/clicks."""
    timestamps = _cron_like_series(14)
    event_types = ["pageview", "scroll", "click", "time_on_page"] * 14

    variance = compute_cadence_variance(timestamps)
    engagement_ratio = compute_engagement_ratio(event_types)

    assert variance is not None and variance < 0.15, "power user IS rigid by construction"
    assert engagement_ratio > 0.05, "power user IS engaged by construction"
    assert (
        evaluate_cadence_bot_flag(
            variance,
            engagement_ratio,
            min_visits_met=True,
            max_variance_threshold=0.15,
            max_engagement_ratio=0.05,
        )
        is False
    )


def test_min_visits_floor_unmet():
    """Below the floor -> False regardless of how bot-like the signals look."""
    assert (
        evaluate_cadence_bot_flag(
            0.0,
            0.0,
            min_visits_met=False,
            max_variance_threshold=0.15,
            max_engagement_ratio=0.05,
        )
        is False
    )


def test_variance_none_is_never_flagged():
    assert (
        evaluate_cadence_bot_flag(
            None,
            0.0,
            min_visits_met=True,
            max_variance_threshold=0.15,
            max_engagement_ratio=0.05,
        )
        is False
    )


# ─── AC-11: config gate + settings-sourced thresholds ───


@pytest.mark.asyncio
async def test_flag_disabled_is_noop(monkeypatch):
    """cadence_bot_flag_enabled=False -> zero queries, zero calls, zero writes."""
    from apps.api.config import settings
    from apps.api.services import cadence_bot_flag_sweep

    monkeypatch.setattr(settings, "cadence_bot_flag_enabled", False, raising=False)

    calls: list[str] = []

    class _ExplodingSession:
        async def execute(self, *args, **kwargs):  # pragma: no cover - must not run
            calls.append("execute")
            raise AssertionError("sweep queried the DB while the flag was OFF")

    monkeypatch.setattr(
        cadence_bot_flag_sweep,
        "evaluate_cadence_bot_flag",
        lambda *a, **k: calls.append("evaluate"),
    )

    counters = await cadence_bot_flag_sweep.run_cadence_bot_flag_sweep(
        _ExplodingSession()
    )

    assert counters == {"sites": 0, "flagged": 0}
    assert calls == []


def test_thresholds_read_from_settings():
    """The sweep must pass settings values into the decision, never literals."""
    source = _SWEEP_MODULE.read_text(encoding="utf-8")
    assert "settings.cadence_bot_flag_max_variance_threshold" in source
    assert "settings.cadence_bot_flag_max_engagement_ratio" in source
    assert "settings.cadence_bot_flag_min_visits" in source
    assert "settings.cadence_bot_flag_lookback_days" in source

    # The pure module must carry no threshold magic numbers of its own.
    tree = ast.parse(_PURE_MODULE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "evaluate_cadence_bot_flag":
            defaults = node.args.defaults + node.args.kw_defaults
            assert not [d for d in defaults if d is not None], (
                "evaluate_cadence_bot_flag must not default its thresholds — "
                "callers are forced to source them from settings"
            )


def test_config_defaults_off_and_bounded():
    from apps.api.config import Settings

    defaults = Settings()
    assert defaults.cadence_bot_flag_enabled is False
    assert defaults.cadence_bot_flag_lookback_days > 0
    assert defaults.cadence_bot_flag_min_visits > 0


# ─── AC-5: structural isolation ───


def test_no_agent_visit_import():
    """Neither module may reference agent_visits or write is_abuse_flagged."""
    for module in (_PURE_MODULE, _SWEEP_MODULE):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert "agent_visit" not in (node.module or ""), (
                    f"{module.name} imports agent_visit — AC-5 forbids it"
                )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "agent_visit" not in alias.name

            # No assignment or keyword may target is_abuse_flagged/do_not_resolve.
            if isinstance(node, ast.keyword):
                assert node.arg not in {"is_abuse_flagged", "do_not_resolve"}, (
                    f"{module.name} writes {node.arg} — AC-5/AC-6 forbid it"
                )
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"is_abuse_flagged", "do_not_resolve"}, (
                    f"{module.name} touches {node.attr} — AC-5/AC-6 forbid it"
                )


def test_pure_module_has_no_db_or_io_imports():
    tree = ast.parse(_PURE_MODULE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)

    forbidden = imported & {"sqlalchemy", "apps", "httpx", "redis"}
    assert not forbidden, f"pure detection module must stay I/O-free, found {forbidden}"


def test_ingest_router_untouched_by_this_feature():
    """AC-4: nothing in the ingest write path may reference the new modules."""
    events_router = (_REPO_ROOT / "apps/api/routers/events.py").read_text(encoding="utf-8")
    assert "cadence_bot_flag" not in events_router
    assert "is_bot_suspect" not in events_router


def test_emailability_and_aggregator_do_not_read_the_flag():
    """AC-6/AC-7: the flag must be invisible to eligibility and aggregates."""
    for rel_path in (
        "apps/api/services/identity_classification.py",
        "apps/api/services/visitor_aggregator.py",
    ):
        source = (_REPO_ROOT / rel_path).read_text(encoding="utf-8")
        assert "is_bot_suspect" not in source, f"{rel_path} must not read the new flag"

    import inspect

    from apps.api.services.identity_classification import is_emailable_identity

    assert len(inspect.signature(is_emailable_identity).parameters) == 3


# ─── AC-12: no PII in logs ───

_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical"}

_ALLOWED_LOG_KEYS = {
    "site_id",
    "visitor_id",
    "variance",
    "engagement_ratio",
    "distinct_visit_days",
    "error",
}

_FORBIDDEN_LOG_KEYS = {
    "email",
    "email_address",
    "visitor_email",
    "full_name",
    "first_name",
    "last_name",
    "name",
    "phone",
    "address",
    "page_title",
    "url",
    "referrer",
    "user_agent",
    "element_text",
    "element_href",
    "body",
    "payload",
    "password",
}


def _logger_calls(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in _LOG_METHODS:
            continue
        target = func.value
        if not (isinstance(target, ast.Name) and target.id == "logger"):
            continue
        yield node.lineno, {kw.arg for kw in node.keywords if kw.arg}


def test_no_pii_in_log_calls():
    """Every new structlog call site logs ids, counts and signal values only."""
    seen_any = False
    for module in (_PURE_MODULE, _SWEEP_MODULE):
        for lineno, keys in _logger_calls(module):
            seen_any = True
            leaked = keys & _FORBIDDEN_LOG_KEYS
            assert not leaked, f"{module.name}:{lineno} logs PII-shaped kwargs {sorted(leaked)}"
            unexpected = keys - _ALLOWED_LOG_KEYS
            assert not unexpected, (
                f"{module.name}:{lineno} logs un-allowlisted keys {sorted(unexpected)} — "
                "confirm they carry no PII, then add them to _ALLOWED_LOG_KEYS"
            )
    assert seen_any, "expected at least one logger call site in the sweep module"
