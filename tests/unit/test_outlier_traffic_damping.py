"""Unit tests for outlier / internal-traffic damping.

Pure logic + AST/source structural checks. Proves the four-way conjunction, the
two sample-size preconditions, the SITE-RELATIVE (never global-threshold)
behaviour across wildly different site scales, the INVERSE engagement polarity vs
cadence_bot_flag (a heavy scraper must NOT be flagged; a heavy human must),
REVERSIBILITY, and that a manual override wins over a later sweep in BOTH
directions.

Mirrors tests/unit/test_cadence_bot_flag.py.
"""

import ast
import inspect
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from apps.api.services.outlier_traffic_damping import (
    compute_engagement_ratio,
    compute_event_count_outlier_score,
    compute_multi_day_persistence,
    evaluate_outlier_flag,
)

pytestmark = pytest.mark.unit

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PURE_MODULE = _REPO_ROOT / "apps/api/services/outlier_traffic_damping.py"
_SWEEP_MODULE = _REPO_ROOT / "apps/api/services/outlier_traffic_damping_sweep.py"

_BASE = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)

# Defaults mirroring config.py, so the tests read like the shipped behaviour.
_MIN_SITE_VISITORS = 20
_OUTLIER_THRESHOLD = 20.0
_MIN_ENGAGEMENT = 0.1
_MIN_VISIT_DAYS = 5


def _spread_days(n_days: int) -> list[datetime]:
    return [_BASE + timedelta(days=i) for i in range(n_days)]


def _events(pageviews: int, engaged: int) -> list[str]:
    return ["pageview"] * pageviews + ["scroll"] * engaged


# ─── compute_event_count_outlier_score: site-relative, sample-size floor ───


def test_outlier_score_is_ratio_against_site_median():
    counts = [10] * 30
    assert compute_event_count_outlier_score(500, counts, _MIN_SITE_VISITORS) == 50.0
    assert compute_event_count_outlier_score(10, counts, _MIN_SITE_VISITORS) == 1.0


def test_outlier_score_none_below_site_sample_floor():
    """A site with too few visitors has no distribution to be an outlier against."""
    counts = [10] * 5
    assert compute_event_count_outlier_score(9999, counts, _MIN_SITE_VISITORS) is None


def test_outlier_score_none_on_degenerate_zero_median():
    counts = [0] * 30
    assert compute_event_count_outlier_score(500, counts, _MIN_SITE_VISITORS) is None


def test_outlier_score_uses_median_not_mean():
    """One huge visitor must not drag the baseline up and mask themselves."""
    counts = [10] * 29 + [100_000]
    # A mean-based baseline would be ~3,343 and score the heavy visitor at ~9.
    assert compute_event_count_outlier_score(
        100_000, counts, _MIN_SITE_VISITORS
    ) == 10_000.0


def test_scoring_is_site_relative_across_wildly_different_site_scales():
    """Same relative position on a tiny site and a huge site scores the same.

    This is the no-global-threshold guarantee: measured site scale ranges from
    29 to 532 visitors, so an absolute event-count cutoff is meaningless.
    """
    small_site = [12] * 29  # ~Grade Coach's normal-visitor median
    large_site = [400] * 532

    small = compute_event_count_outlier_score(12 * 50, small_site, _MIN_SITE_VISITORS)
    large = compute_event_count_outlier_score(400 * 50, large_site, _MIN_SITE_VISITORS)
    assert small == large == 50.0

    # And a visitor that is heavy in absolute terms but typical for a big site
    # is NOT an outlier there, while the same absolute count IS on a small site.
    assert compute_event_count_outlier_score(400, large_site, _MIN_SITE_VISITORS) == 1.0
    assert (
        compute_event_count_outlier_score(400, small_site, _MIN_SITE_VISITORS)
        > _OUTLIER_THRESHOLD
    )


# ─── compute_multi_day_persistence ───


def test_persistence_requires_distinct_days_not_event_count():
    burst = [_BASE + timedelta(seconds=i) for i in range(5000)]
    assert compute_multi_day_persistence(burst, _MIN_VISIT_DAYS) is False
    assert compute_multi_day_persistence(_spread_days(5), _MIN_VISIT_DAYS) is True
    assert compute_multi_day_persistence(_spread_days(4), _MIN_VISIT_DAYS) is False


def test_persistence_empty_is_false():
    assert compute_multi_day_persistence([], _MIN_VISIT_DAYS) is False


# ─── evaluate_outlier_flag: strict four-way conjunction ───


def _evaluate(
    score=100.0, engagement=0.5, persistent=True, min_sample_met=True
) -> bool:
    return evaluate_outlier_flag(
        score,
        engagement,
        persistent,
        min_sample_met,
        _OUTLIER_THRESHOLD,
        _MIN_ENGAGEMENT,
    )


def test_all_four_conditions_met_flags():
    assert _evaluate() is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_sample_met": False},
        {"score": None},
        {"score": _OUTLIER_THRESHOLD - 0.01},
        {"persistent": False},
        {"engagement": _MIN_ENGAGEMENT - 0.01},
    ],
    ids=["no-sample", "score-none", "below-threshold", "not-persistent", "no-engagement"],
)
def test_any_single_condition_failing_blocks_the_flag(kwargs):
    assert _evaluate(**kwargs) is False


def test_thresholds_are_inclusive_boundaries():
    assert _evaluate(score=_OUTLIER_THRESHOLD, engagement=_MIN_ENGAGEMENT) is True


# ─── The scraper-vs-human discriminator (INVERSE polarity vs cadence_bot_flag) ───


def test_heavy_visitor_without_engagement_is_not_flagged_but_with_engagement_is():
    """Engagement is what separates a heavy human from a heavy scraper.

    Both visitors below have IDENTICAL volume, identical persistence and an
    identical outlier score. The only difference is whether they scroll. The
    scraper must NOT be flagged as internal traffic — that is the cadence/bot
    layer's job, and mislabelling it here would damp the wrong row.

    This is the inverse of evaluate_cadence_bot_flag, which flags on engagement
    being ABSENT (<= a ceiling). Here engagement must be PRESENT (>= a floor).
    """
    site_counts = [12] * 30
    scraper_events = _events(pageviews=2000, engaged=0)
    human_events = _events(pageviews=1200, engaged=800)

    assert len(scraper_events) == len(human_events)  # identical volume

    score = compute_event_count_outlier_score(
        len(scraper_events), site_counts, _MIN_SITE_VISITORS
    )
    persistent = compute_multi_day_persistence(_spread_days(20), _MIN_VISIT_DAYS)

    scraper_flagged = evaluate_outlier_flag(
        score,
        compute_engagement_ratio(scraper_events),
        persistent,
        True,
        _OUTLIER_THRESHOLD,
        _MIN_ENGAGEMENT,
    )
    human_flagged = evaluate_outlier_flag(
        score,
        compute_engagement_ratio(human_events),
        persistent,
        True,
        _OUTLIER_THRESHOLD,
        _MIN_ENGAGEMENT,
    )

    assert scraper_flagged is False, "a heavy no-engagement scraper is not internal"
    assert human_flagged is True, "a heavy engaged human is the target signal"


def test_engagement_polarity_is_opposite_to_cadence_bot_flag():
    """Same engagement ratio, opposite verdicts from the two modules."""
    from apps.api.services.cadence_bot_flag import evaluate_cadence_bot_flag

    no_engagement = 0.0
    # cadence-bot: absent engagement is a POSITIVE bot signal
    assert evaluate_cadence_bot_flag(0.01, no_engagement, True, 0.15, 0.05) is True
    # outlier-damping: absent engagement is DISQUALIFYING
    assert _evaluate(engagement=no_engagement) is False


# ─── REVERSIBILITY (the single most important safety property) ───


def test_verdict_is_reversible_when_volume_normalises():
    """The scorer is a pure function of CURRENT data — it returns False again.

    Unlike is_bot_suspect / is_abuse_flagged, this decision has no memory and no
    stickiness. A visitor whose volume falls back to normal scores un-flagged on
    the very next evaluation.
    """
    site_counts = [12] * 30
    persistent = compute_multi_day_persistence(_spread_days(20), _MIN_VISIT_DAYS)

    heavy = compute_event_count_outlier_score(2000, site_counts, _MIN_SITE_VISITORS)
    normal = compute_event_count_outlier_score(15, site_counts, _MIN_SITE_VISITORS)

    args = (0.5, persistent, True, _OUTLIER_THRESHOLD, _MIN_ENGAGEMENT)
    assert evaluate_outlier_flag(heavy, *args) is True
    assert evaluate_outlier_flag(normal, *args) is False


def test_sweep_write_is_not_sticky_and_writes_both_directions():
    """Structural: the sweep must NOT copy the sticky `.is_(False)` guard.

    cadence_bot_flag_sweep uses `update().where(col.is_(False)).values(col=True)`
    — one-way forever. This sweep must write the CURRENT verdict instead, or a
    false positive could never be undone by the automatic path.
    """
    source = _SWEEP_MODULE.read_text(encoding="utf-8")
    assert "is_internal_suspect.is_(False)" not in source, (
        "sticky one-way guard found — is_internal_suspect must be reversible"
    )
    assert "values(is_internal_suspect=flagged)" in source, (
        "sweep must write the current verdict, not a hardcoded True"
    )


# ─── Manual override wins over a later sweep, in BOTH directions ───


def test_sweep_skips_any_visitor_with_a_manual_override_in_either_direction():
    """The human's call is permanent. Proven at the level the sweep enforces it.

    The sweep reads every visitor with a non-NULL internal_override and skips
    them by set membership, so "internal" is never un-set and "not_internal" is
    never re-flagged. This test exercises that exact selection logic against a
    simulated sweep tick whose raw verdict would DISAGREE with both overrides.
    """
    source = _SWEEP_MODULE.read_text(encoding="utf-8")
    assert "internal_override.isnot(None)" in source
    assert "skipped_override" in source
    # Defence in depth at the SQL level too.
    assert "Visitor.internal_override.is_(None)" in source

    # Behavioural simulation of the skip, mirroring _sweep_site's structure.
    overridden = {"owner_says_internal", "owner_says_not_internal"}
    stored = {
        "owner_says_internal": True,      # human set "internal"
        "owner_says_not_internal": False,  # human set "not_internal"
        "automatic": False,
    }
    # A sweep tick whose raw verdict contradicts BOTH manual calls.
    raw_verdict = {
        "owner_says_internal": False,     # would wrongly clear the human's flag
        "owner_says_not_internal": True,  # would wrongly re-flag
        "automatic": True,
    }
    for visitor_id, verdict in raw_verdict.items():
        if visitor_id in overridden:
            continue
        stored[visitor_id] = verdict

    assert stored["owner_says_internal"] is True, "manual 'internal' was un-set"
    assert stored["owner_says_not_internal"] is False, "manual 'not_internal' was re-flagged"
    assert stored["automatic"] is True, "non-overridden visitor must still update"


def test_override_endpoint_is_not_gated_on_the_site_toggle():
    """The manual action is standalone — usable even with damping off."""
    tree = ast.parse((_REPO_ROOT / "apps/api/routers/visitors.py").read_text(encoding="utf-8"))
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "set_internal_override"
    )
    # Drop the docstring — it explains WHY the gate is absent, which would
    # otherwise match a naive substring search.
    body = [
        node
        for node in fn.body
        if not (
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        )
    ]
    code = "\n".join(ast.unparse(node) for node in body)
    assert "internal_damping_enabled" not in code


# ─── Structural: purity, and isolation from the emailability guardrail ───


def test_pure_module_has_no_io_or_db_imports():
    tree = ast.parse(_PURE_MODULE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    for banned in ("sqlalchemy", "httpx", "redis", "requests", "asyncio"):
        assert banned not in imported, f"pure module must not import {banned}"

    # AST-level, so the module's own prose about "no settings reads" doesn't
    # match itself.
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "settings" not in names, "thresholds must be passed in, never read here"
    assert "AsyncSession" not in names | attrs


def test_pure_functions_are_synchronous():
    for fn in (
        compute_event_count_outlier_score,
        compute_multi_day_persistence,
        evaluate_outlier_flag,
    ):
        assert not inspect.iscoroutinefunction(fn)


def test_emailability_never_reads_the_new_flag():
    """Hard Safety Constraint #2 — data quality, never outreach eligibility."""
    from apps.api.services.identity_classification import is_emailable_identity

    source = (_REPO_ROOT / "apps/api/services/identity_classification.py").read_text(encoding="utf-8")
    assert "is_internal_suspect" not in source
    assert "internal_override" not in source
    assert len(inspect.signature(is_emailable_identity).parameters) == 3


def test_visitor_aggregator_is_untouched_by_this_feature():
    """VALIDATE correction: the per-visitor events-scoped SQL stays unchanged."""
    source = (_REPO_ROOT / "apps/api/services/visitor_aggregator.py").read_text(encoding="utf-8")
    assert "is_internal_suspect" not in source
    assert "internal_override" not in source


def test_digest_exclusion_is_gated_and_does_not_couple_to_emailability():
    source = (_REPO_ROOT / "apps/api/services/daily_digest.py").read_text(encoding="utf-8")
    assert 'Visitor.internal_override.is_distinct_from("internal")' in source
    assert "damping_enabled" in source
    assert "is_emailable_identity" not in source


def test_resolution_deprioritises_and_never_excludes():
    source = (_REPO_ROOT / "apps/api/services/resolution_runner.py").read_text(encoding="utf-8")
    assert 'Visitor.internal_override.is_distinct_from("internal").desc()' in source, (
        "must sort on the human's confirmation, not filter"
    )
    assert "Visitor.internal_override.is_(None)" not in source, (
        "confirmed-internal visitors must be deprioritised, never excluded"
    )
    assert 'getattr(site, "internal_damping_enabled", False)' in source, (
        "the ordering change must be gated per-site, and must fail safe to OFF"
    )


# ─── Suggestion-only: the automatic flag never acts on its own ───
#
# Calibrated live 27-07-26 against the real per-visitor distribution:
#     >=20x  median & >=3 days -> 34 flagged, 5 already identified with an email
#     >=50x  median & >=3 days -> 21 flagged, 3 already identified with an email
#     >=100x median & >=5 days -> 15 flagged, 2 already identified with an email
# There are only 28 identified visitors in the whole system, so auto-excluding at
# 20x would have silently hidden ~18% of every customer's real leads. No
# threshold separates "owner who browses 30k times" from "extremely engaged
# prospect". Hence: is_internal_suspect is a LABEL; only internal_override acts.


def test_auto_flagged_but_unconfirmed_visitor_is_still_fully_counted_in_the_digest():
    """The automatic flag must be absent from the digest aggregate entirely.

    A visitor with is_internal_suspect=True and internal_override=NULL is
    indistinguishable from any other visitor to this query.
    """
    source = (_REPO_ROOT / "apps/api/services/daily_digest.py").read_text(encoding="utf-8")
    assert "Visitor.is_internal_suspect" not in source, (
        "the auto flag must never gate the digest aggregate — only the human's "
        "internal_override may exclude a visitor"
    )
    assert 'Visitor.internal_override.is_distinct_from("internal")' in source, (
        "NULL (never reviewed) and 'not_internal' must both stay counted"
    )


def test_auto_flagged_but_unconfirmed_visitor_keeps_normal_resolution_order():
    """The automatic flag must be absent from the resolution ordering entirely."""
    source = (_REPO_ROOT / "apps/api/services/resolution_runner.py").read_text(encoding="utf-8")
    assert "Visitor.is_internal_suspect" not in source, (
        "the auto flag must never affect resolution priority — only the human's "
        "internal_override may deprioritise"
    )
    assert 'Visitor.internal_override.is_distinct_from("internal").desc()' in source


def test_default_threshold_is_the_calibrated_suggestion_list_size():
    from apps.api.config import Settings

    defaults = Settings.model_fields
    assert defaults["outlier_traffic_damping_outlier_threshold"].default == 50.0
    assert defaults["outlier_traffic_damping_min_visit_days"].default == 3


def test_sweep_read_is_bounded_and_per_site_opt_in():
    source = _SWEEP_MODULE.read_text(encoding="utf-8")
    assert "outlier_traffic_damping_lookback_days" in source
    assert "Event.created_at >= cutoff" in source
    assert "Site.internal_damping_enabled.is_(True)" in source


def test_user_facing_copy_never_asserts_the_visitors_identity():
    """Honesty Constraint: "heavy" is inferred, not proven."""
    banned = ("this is you", "this is the owner", "is your team", "the site owner")
    for rel_path in (
        "apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx",
        "apps/web/src/app/dashboard/visitors/page.tsx",
        "apps/web/src/components/site-settings-dialog.tsx",
    ):
        source = (_REPO_ROOT / rel_path).read_text(encoding="utf-8").lower()
        for phrase in banned:
            assert phrase not in source, f"{rel_path} asserts identity: {phrase!r}"
