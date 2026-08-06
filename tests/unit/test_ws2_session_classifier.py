"""Unit tests for the WS2 agent-driven session classifier.

Proves: the staged fast-path OR behavioral-AND-gate decision (AC-WS2-1), the
sample-size precondition, the OFF-by-default gate + config defaults (AC-WS2-8 /
AC-G-4), settings-sourced thresholds (no module magic number), structural
isolation from is_emailable_identity / aggregates / the ingest router, and the
no-PII-in-logs guarantee.

Mirrors tests/unit/test_cadence_bot_flag.py (pure-logic + AST structural checks).
"""

import ast
import inspect
import pathlib

import pytest

from apps.api.services.ws2_session_classifier import (
    compute_dead_center_rate,
    evaluate_behavioral_and_gate,
    evaluate_session_classifier,
    is_deterministic_agent,
)

pytestmark = pytest.mark.unit

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PURE_MODULE = _REPO_ROOT / "apps/api/services/ws2_session_classifier.py"
_SWEEP_MODULE = _REPO_ROOT / "apps/api/services/ws2_session_classifier_sweep.py"

# Placeholder thresholds echoing the config defaults (see config.py).
_MAX_ENTROPY = 0.15
_MIN_DEAD_CENTER = 0.6


# ─── AC-WS2-1: deterministic fast-path (Stage 1) ───


@pytest.mark.parametrize(
    "webdriver,ua_ch_headless,expected",
    [
        (True, False, True),
        (False, True, True),
        (True, True, True),
        (False, False, False),
        (None, None, False),
        (None, True, True),
    ],
)
def test_deterministic_fast_path(webdriver, ua_ch_headless, expected):
    assert is_deterministic_agent(webdriver, ua_ch_headless) is expected


# ─── AC-WS2-1: dead-centre rate ───


def test_dead_center_rate_basic():
    assert compute_dead_center_rate(3, 6) == pytest.approx(0.5)


def test_dead_center_rate_all_centered():
    assert compute_dead_center_rate(10, 10) == pytest.approx(1.0)


@pytest.mark.parametrize("clicks", [0, None])
def test_dead_center_rate_no_clicks_never_divides_by_zero(clicks):
    assert compute_dead_center_rate(5, clicks) == 0.0


def test_dead_center_rate_none_centered():
    assert compute_dead_center_rate(None, 8) == 0.0


# ─── AC-WS2-1: behavioral AND-gate quadrant matrix (Stage 2) ───


@pytest.mark.parametrize(
    "quadrant,pointer_entropy,dead_center_rate,expected",
    [
        ("robotic + dead-centre", 0.02, 0.90, True),
        ("robotic + human-clicks", 0.02, 0.10, False),
        ("human-move + dead-centre", 0.80, 0.90, False),
        ("human-move + human-clicks", 0.80, 0.10, False),
    ],
)
def test_behavioral_and_gate_quadrant_matrix(
    quadrant, pointer_entropy, dead_center_rate, expected
):
    """ONLY the low-entropy + high-dead-centre quadrant flags (strict conjunction)."""
    assert (
        evaluate_behavioral_and_gate(
            pointer_entropy,
            dead_center_rate,
            min_clicks_met=True,
            max_pointer_entropy_threshold=_MAX_ENTROPY,
            min_dead_center_rate_threshold=_MIN_DEAD_CENTER,
        )
        is expected
    ), f"quadrant {quadrant} decided wrongly"


def test_behavioral_and_gate_min_clicks_floor_unmet():
    """Below the click floor -> False regardless of how agent-like the signals look."""
    assert (
        evaluate_behavioral_and_gate(
            0.0,
            1.0,
            min_clicks_met=False,
            max_pointer_entropy_threshold=_MAX_ENTROPY,
            min_dead_center_rate_threshold=_MIN_DEAD_CENTER,
        )
        is False
    )


def test_behavioral_and_gate_none_entropy_fails_safe():
    """pointer_entropy None (e.g. entropy dropped from tracker) -> never flags."""
    assert (
        evaluate_behavioral_and_gate(
            None,
            1.0,
            min_clicks_met=True,
            max_pointer_entropy_threshold=_MAX_ENTROPY,
            min_dead_center_rate_threshold=_MIN_DEAD_CENTER,
        )
        is False
    )


# ─── AC-WS2-1: top-level staged decision ───


def test_top_level_fast_path_short_circuits_precondition():
    """A webdriver session flags even with zero clicks (fast-path bypasses Stage 2)."""
    assert (
        evaluate_session_classifier(
            webdriver=True,
            ua_ch_headless=None,
            pointer_entropy=None,
            dead_center_rate=0.0,
            min_clicks_met=False,
            max_pointer_entropy_threshold=_MAX_ENTROPY,
            min_dead_center_rate_threshold=_MIN_DEAD_CENTER,
        )
        is True
    )


def test_top_level_falls_through_to_behavioral():
    assert (
        evaluate_session_classifier(
            webdriver=False,
            ua_ch_headless=False,
            pointer_entropy=0.02,
            dead_center_rate=0.90,
            min_clicks_met=True,
            max_pointer_entropy_threshold=_MAX_ENTROPY,
            min_dead_center_rate_threshold=_MIN_DEAD_CENTER,
        )
        is True
    )


def test_top_level_clean_human_not_flagged():
    assert (
        evaluate_session_classifier(
            webdriver=False,
            ua_ch_headless=False,
            pointer_entropy=0.80,
            dead_center_rate=0.05,
            min_clicks_met=True,
            max_pointer_entropy_threshold=_MAX_ENTROPY,
            min_dead_center_rate_threshold=_MIN_DEAD_CENTER,
        )
        is False
    )


# ─── AC-WS2-8 / AC-G-4: OFF-by-default gate + config defaults ───


@pytest.mark.asyncio
async def test_flag_disabled_is_noop(monkeypatch):
    """ws2_classifier_enabled=False -> zero queries, zero calls, zero writes."""
    from apps.api.config import settings
    from apps.api.services import ws2_session_classifier_sweep

    monkeypatch.setattr(settings, "ws2_classifier_enabled", False, raising=False)

    calls: list[str] = []

    class _ExplodingSession:
        async def execute(self, *args, **kwargs):  # pragma: no cover - must not run
            calls.append("execute")
            raise AssertionError("sweep queried the DB while the flag was OFF")

    monkeypatch.setattr(
        ws2_session_classifier_sweep,
        "evaluate_session_classifier",
        lambda *a, **k: calls.append("evaluate"),
    )

    counters = await ws2_session_classifier_sweep.run_ws2_classifier_sweep(
        _ExplodingSession()
    )

    assert counters == {"sites": 0, "flagged": 0}
    assert calls == []


def test_config_defaults_off_and_bounded():
    from apps.api.config import Settings

    defaults = Settings()
    assert defaults.ws2_classifier_enabled is False
    assert defaults.ws2_classifier_lookback_days > 0
    assert defaults.ws2_classifier_min_clicks > 0
    assert 0.0 <= defaults.ws2_classifier_max_pointer_entropy <= 1.0
    assert 0.0 <= defaults.ws2_classifier_min_dead_center_rate <= 1.0


def test_thresholds_read_from_settings():
    """The sweep must pass settings values into the decision, never literals."""
    source = _SWEEP_MODULE.read_text()
    assert "settings.ws2_classifier_max_pointer_entropy" in source
    assert "settings.ws2_classifier_min_dead_center_rate" in source
    assert "settings.ws2_classifier_min_clicks" in source
    assert "settings.ws2_classifier_lookback_days" in source

    # The pure module must carry no threshold defaults of its own — callers are
    # forced to source them from settings.
    tree = ast.parse(_PURE_MODULE.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "evaluate_behavioral_and_gate",
            "evaluate_session_classifier",
        ):
            defaults = node.args.defaults + node.args.kw_defaults
            assert not [d for d in defaults if d is not None], (
                f"{node.name} must not default its thresholds"
            )


# ─── AC-WS2-8 / AC-G-4: structural isolation (label never gates) ───


def test_pure_module_has_no_db_or_io_imports():
    tree = ast.parse(_PURE_MODULE.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
    forbidden = imported & {"sqlalchemy", "apps", "httpx", "redis"}
    assert not forbidden, f"pure detection module must stay I/O-free, found {forbidden}"


def test_neither_module_writes_emailability_or_guardrail_columns():
    for module in (_PURE_MODULE, _SWEEP_MODULE):
        tree = ast.parse(module.read_text(), filename=str(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword):
                assert node.arg not in {"is_abuse_flagged", "do_not_resolve"}, (
                    f"{module.name} writes {node.arg} — visibility-only forbids it"
                )
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"is_abuse_flagged", "do_not_resolve"}, (
                    f"{module.name} touches {node.attr} — visibility-only forbids it"
                )


def test_emailability_and_aggregator_do_not_read_the_flag():
    """AC-WS2-8: the flag must be invisible to eligibility and aggregates."""
    for rel_path in (
        "apps/api/services/identity_classification.py",
        "apps/api/services/visitor_aggregator.py",
    ):
        source = (_REPO_ROOT / rel_path).read_text()
        assert "is_agent_operated" not in source, f"{rel_path} must not read the flag"

    from apps.api.services.identity_classification import is_emailable_identity

    # Signature unchanged — WS2 added NO 4th guard parameter (guardrail 4).
    assert len(inspect.signature(is_emailable_identity).parameters) == 3


def test_ingest_router_untouched_by_this_feature():
    """Batch-only: nothing in the ingest write path may reference the new modules."""
    events_router = (_REPO_ROOT / "apps/api/routers/events.py").read_text()
    assert "ws2_session_classifier" not in events_router
    assert "is_agent_operated" not in events_router


# ─── no PII in logs ───

_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical"}

_ALLOWED_LOG_KEYS = {
    "site_id",
    "visitor_id",
    "pointer_entropy",
    "dead_center_rate",
    "click_ct",
    "error",
}

_FORBIDDEN_LOG_KEYS = {
    "email",
    "full_name",
    "name",
    "phone",
    "page_title",
    "url",
    "referrer",
    "user_agent",
    "element_text",
    "element_href",
    "body",
    "payload",
}


def _logger_calls(path: pathlib.Path):
    tree = ast.parse(path.read_text(), filename=str(path))
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
    seen_any = False
    for module in (_PURE_MODULE, _SWEEP_MODULE):
        for lineno, keys in _logger_calls(module):
            seen_any = True
            leaked = keys & _FORBIDDEN_LOG_KEYS
            assert not leaked, f"{module.name}:{lineno} logs PII-shaped kwargs {sorted(leaked)}"
            unexpected = keys - _ALLOWED_LOG_KEYS
            assert not unexpected, (
                f"{module.name}:{lineno} logs un-allowlisted keys {sorted(unexpected)}"
            )
    assert seen_any, "expected at least one logger call site in the sweep module"
