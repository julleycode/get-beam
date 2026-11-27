"""G7 — structural census for the company exclusion guard.

Every outreach chokepoint must carry a flag-guarded exclusion check
(``settings.company_exclusion_enabled`` + an exclusion helper call in the same
function). Every caller of a guarded chokepoint must be either a guarded site
itself or in the covered-via allow-list. Owner-facing surfaces stay ungated.
"""

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

API = pathlib.Path(__file__).resolve().parents[2] / "apps" / "api"
HELPERS = {"excluded_visitor_ids", "filter_visitor_ids", "draft_is_company_excluded"}

# (file, function) that MUST carry the guard.
GUARDED = {
    ("services/campaign_sender.py", "send_campaign_emails"),
    ("services/csv_exporter.py", "_get_segment_visitors"),
    ("agents/segmenter.py", "run_segmentation"),
    ("routers/campaigns.py", "create_campaign_from_segment"),
    ("routers/campaigns.py", "_resolve_linkedin_targets"),
    ("services/auto_drafter.py", "generate_for_visitor"),
    ("routers/drafts.py", "approve_draft"),
    ("routers/drafts.py", "retry_draft"),
    ("services/sender.py", "send_draft"),
    ("routers/visitors.py", "list_visitors"),
}

# Callers of a guarded chokepoint that are covered because the callee filters.
COVERED_VIA = {
    "_get_segment_visitors": {
        "services/csv_exporter.py", "services/ads_push.py", "services/crm_push.py",
        "services/crm/contact_mapper.py", "routers/exports.py",
    },
    "run_segmentation": {
        # inputs already filtered by run_segmentation
        "tasks/segmentation_tasks.py", "routers/segments.py",
    },
    "_resolve_linkedin_targets": {"routers/campaigns.py"},
    "generate_for_visitor": {"tasks/resolution_tasks.py", "services/job_change_detector.py"},
    "send_draft": {"routers/drafts.py"},
}

# Owner-facing — deliberately ungated (user decision 5).
UNGATED = ["services/hot_alert.py", "services/outcome_digest.py", "services/daily_digest.py"]


def _funcs(path: pathlib.Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _is_guarded(fn) -> bool:
    flag = helper = False
    for n in ast.walk(fn):
        if isinstance(n, ast.Attribute) and n.attr == "company_exclusion_enabled":
            flag = True
        if isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
            if name in HELPERS:
                helper = True
    return flag and helper


def test_should_wire_exclusion_at_every_outreach_chokepoint():
    missing = []
    for rel, name in sorted(GUARDED):
        fns = [f for f in _funcs(API / rel) if f.name == name]
        assert fns, f"{rel}:{name} not found"
        if not any(_is_guarded(f) for f in fns):
            missing.append(f"{rel}:{name}")
    assert not missing, f"unguarded chokepoints: {missing}"


def test_every_caller_is_guarded_or_allow_listed():
    unknown = []
    for path in API.rglob("*.py"):
        if "migrations" in path.parts or "__pycache__" in path.parts:
            continue
        rel = str(path.relative_to(API))
        src = path.read_text()
        for callee, allowed in COVERED_VIA.items():
            if callee not in src:
                continue
            tree = ast.parse(src)
            for n in ast.walk(tree):
                if isinstance(n, ast.Call):
                    f = n.func
                    name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
                    if name == callee and rel not in allowed:
                        unknown.append(f"{rel} -> {callee}")
    assert not unknown, f"new un-reviewed callers: {sorted(set(unknown))}"


@pytest.mark.parametrize("rel", UNGATED)
def test_owner_facing_surfaces_stay_ungated(rel):
    p = API / rel
    if p.exists():
        assert "company_exclusion" not in p.read_text()


def test_is_emailable_identity_signature_untouched():
    import inspect

    from apps.api.services.identity_classification import is_emailable_identity

    assert len(inspect.signature(is_emailable_identity).parameters) == 3
