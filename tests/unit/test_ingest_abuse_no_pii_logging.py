"""AC-9: no PII in any log line / counter / alert payload added by the
ingest-abuse-hardening work.

This repo has NO automated PII-lint on structlog call sites — the guardrail is
otherwise a code-review convention only (confirmed at VALIDATE and re-confirmed
at EXECUTE). Per execute-agent instruction E1 this test is therefore MANDATORY:
it is the sole machine enforcement of AC-9 for the surfaces this work added.

Scope is deliberately narrow — the files this work created or added log call
sites to. It does NOT retroactively audit pre-existing call sites elsewhere in
the codebase.

Implemented over the AST rather than a text regex so `logger.warning(...)` kwargs
are matched structurally and a reformatted/multi-line call cannot slip past.
"""

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Modules this work CREATED outright — every logger call in them is new, so the
# strict allowlist applies.
_NEW_MODULES = (
    "apps/api/services/ip_resolution.py",      # P2
    "apps/api/services/ingest_velocity.py",    # P4 velocity
    "apps/api/routers/ingest_health.py",       # P5 observability
    "apps/api/services/rate_limiter.py",       # P3 site ceiling (rewritten)
)

# Pre-existing files this work touched. P1's body-size middleware adds no logger
# call at all (a size rejection carries zero user data by construction), and the
# events.py additions reuse existing keys — so these get the forbidden-key check
# but NOT the allowlist check, which would otherwise fail on unrelated legacy
# call sites in the same file.
_TOUCHED_FILES = (
    "apps/api/main.py",                        # P1 body-size guard
    "apps/api/routers/events.py",              # P3/P4 wiring
)

_NEW_LOG_SURFACES = _NEW_MODULES + _TOUCHED_FILES

# Structured-log keys added by THIS work. Anything outside this set in the files
# above must be justified — the allowlist is what keeps the test from silently
# rotting into a no-op as new keys appear.
_ALLOWED_LOG_KEYS = {
    "site_id",
    "error",
    "fallback",
    "limit_per_minute",
    "distinct_visitors",
    "distinct_fingerprints",
    "window_seconds",
}

# Never acceptable in a log payload: raw person data or free-form user content.
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

_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical"}


def _logger_calls(path: pathlib.Path):
    """Yield (lineno, kwarg_names) for every logger.<level>(...) call in a file."""
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


@pytest.mark.parametrize("rel_path", _NEW_LOG_SURFACES)
def test_new_log_call_sites_carry_no_pii(rel_path):
    """AC-9: no forbidden PII-shaped kwarg on any new log call site."""
    path = _REPO_ROOT / rel_path
    assert path.exists(), f"expected file is missing: {rel_path}"

    for lineno, keys in _logger_calls(path):
        leaked = keys & _FORBIDDEN_LOG_KEYS
        assert not leaked, f"{rel_path}:{lineno} logs PII-shaped kwargs: {sorted(leaked)}"


@pytest.mark.parametrize("rel_path", _NEW_MODULES)
def test_new_log_call_sites_use_only_allowlisted_keys(rel_path):
    """A NEW key in these files must be reviewed and added to the allowlist.

    Without this, the forbidden-list test above quietly stops covering anything
    a future edit invents (e.g. `visitor_name=`), which is exactly how a
    convention-only guardrail decays.
    """
    path = _REPO_ROOT / rel_path
    for lineno, keys in _logger_calls(path):
        unexpected = keys - _ALLOWED_LOG_KEYS
        assert not unexpected, (
            f"{rel_path}:{lineno} logs un-allowlisted keys {sorted(unexpected)} — "
            "confirm they carry no PII, then add them to _ALLOWED_LOG_KEYS"
        )


def test_velocity_counters_key_on_ids_not_pii():
    """Redis key templates must be built from site_id only, never from PII."""
    from apps.api.services import ingest_velocity

    for template in (ingest_velocity._VISITOR_KEY, ingest_velocity._FINGERPRINT_KEY):
        assert "{site_id}" in template
        assert "email" not in template and "name" not in template


def test_ingest_health_response_exposes_no_pii():
    """AC-9: the operator payload is counts + ids + ratios only."""
    src = (_REPO_ROOT / "apps/api/routers/ingest_health.py").read_text(encoding="utf-8")
    for forbidden in ("IdentifiedVisitor", ".email", "full_name"):
        assert forbidden not in src, f"ingest-health surface references {forbidden}"


def test_ac10_no_new_external_service_calls():
    """AC-10: this work adds zero new external/paid provider call sites."""
    for rel_path in (
        "apps/api/services/ip_resolution.py",
        "apps/api/services/ingest_velocity.py",
        "apps/api/routers/ingest_health.py",
    ):
        src = (_REPO_ROOT / rel_path).read_text(encoding="utf-8")
        for forbidden in ("httpx", "requests", "aiohttp", "urllib.request"):
            assert forbidden not in src, f"{rel_path} introduces an external call"
