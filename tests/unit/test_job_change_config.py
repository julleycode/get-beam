"""Config defaults for job-change detection (SPEC AC-1, flag-off deliverable).

Shipping this feature FLAG-OFF is the deliverable. These tests are the guard
that a later edit cannot quietly flip a default and start spending provider
credits (or writing rows) in a real environment without an explicit operator
action.
"""

import pytest

from apps.api.config import Settings

pytestmark = pytest.mark.unit


def test_flag_defaults_false():
    """AC-1: job_change_detection_enabled must default OFF."""
    assert Settings().job_change_detection_enabled is False


def test_budget_cap_default_is_positive_and_bounded():
    """A cap of 0 would silently disable the feature even once enabled; an
    unbounded cap would make the flag a blank cheque against paid providers."""
    cap = Settings().job_change_recheck_daily_cap
    assert isinstance(cap, int)
    assert 0 < cap <= 10_000


def test_staleness_days_matches_company_graph_precedent():
    """Deliberately the same number as company_graph_staleness_days — both
    answer 'how stale is too stale to trust a cached professional snapshot'."""
    s = Settings()
    assert s.job_change_staleness_days == s.company_graph_staleness_days == 75


def test_min_confidence_is_a_real_gate():
    """The threshold must actually exclude the domain-fallback tier (0.2),
    otherwise the corroboration gate is decorative."""
    from apps.api.services.job_change_detector import _SOURCE_CONFIDENCE

    threshold = Settings().job_change_min_confidence
    assert 0.0 < threshold <= 1.0
    assert _SOURCE_CONFIDENCE["domain_fallback"] < threshold
    assert _SOURCE_CONFIDENCE["pdl"] >= threshold
    assert _SOURCE_CONFIDENCE["apollo"] >= threshold


def test_job_change_settings_do_not_alter_resolution_budget_default():
    """AC-4 guard: adding this feature must not have moved the pre-existing
    identify/resolution budget defaults."""
    s = Settings()
    assert s.default_daily_resolution_budget == 50
    assert s.default_daily_enrichment_budget == 3
    # The job-change budget must be its own setting, never a reshaping of the
    # resolution budget (AC-4: two structurally separate stores).
    assert not hasattr(s, "job_change_resolution_budget")
