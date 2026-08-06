"""Tests for apps.api.services.identity_classification.identity_level."""

import pytest
from apps.api.services.identity_classification import (
    COMPANY_LEVEL_PROVIDERS,
    GRAPH_CANDIDATE_PROVIDERS,
    identity_level,
    is_emailable_identity,
    is_graph_candidate_provider,
    is_verified_identity,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("provider", ["hunter", "apollo"])
def test_company_level_providers(provider):
    assert identity_level(provider) == "company"


@pytest.mark.parametrize("provider", [
    "form_capture", "pdl_person_enrich", "rb2b", "leadpipe", "capturify", "manual",
])
def test_person_level_providers(provider):
    assert identity_level(provider) == "person"


@pytest.mark.parametrize("provider", [None, "", "unknown_provider", "pdl_ip_enrich"])
def test_unknown_or_missing_is_none(provider):
    assert identity_level(provider) is None


# ───────────── ingest-abuse-hardening AC-4 (abuse-flag emailability gate) ─────────────


@pytest.mark.parametrize("provider", [
    "form_capture", "pdl_person_enrich", "rb2b", "leadpipe", "capturify", "manual",
    "fingerprint_match", "beam_identity_network", "svid_reconcile",
    "hunter", "apollo", None, "", "unknown_provider",
])
def test_is_emailable_identity_abuse_flag_overrides_provider(provider):
    """AC-4: an abuse-flagged identity is NEVER emailable, whatever its provider.

    Includes every person-level provider — the override must hold even for the
    providers that would otherwise be unconditionally emailable, which is the
    only version of this guard that is actually defense in depth.
    """
    assert is_emailable_identity(provider, None, True) is False


def test_abuse_flag_default_false_preserves_existing_behavior():
    """Regression: the new third parameter must not change any existing call."""
    assert is_emailable_identity("rb2b") is True
    assert is_emailable_identity("hunter") is False
    assert is_emailable_identity("rb2b", "agent-visit-uuid") is False


def test_agent_marker_and_abuse_flag_are_independent_guards():
    """Either marker alone is sufficient to refuse outreach."""
    assert is_emailable_identity("rb2b", "agent-visit-uuid", False) is False
    assert is_emailable_identity("rb2b", None, True) is False
    assert is_emailable_identity("rb2b", None, False) is True


# ───────────── identity-honesty Phase 1 (candidate tier) ─────────────


@pytest.mark.parametrize(
    "provider", ["rb2b", "leadpipe", "capturify", "beam_identity_network"]
)
def test_graph_providers_are_candidate_tier(provider):
    """AC1: every identity-GRAPH provider is candidate-tier."""
    assert provider in GRAPH_CANDIDATE_PROVIDERS
    assert is_graph_candidate_provider(provider) is True


@pytest.mark.parametrize(
    "provider",
    [
        "form_capture",       # first-party: the visitor typed it
        "pdl_person_enrich",  # enrich of a captured email
        "manual",             # a human typed it
        "svid_reconcile",     # deterministic continuity, inherits origin tier
        "fingerprint_match",  # deterministic continuity, inherits origin tier
        "hunter",             # company-level, caught by the orthogonal axis
        "apollo",
        None,
        "",
    ],
)
def test_non_graph_providers_are_not_candidate_tier(provider):
    assert is_graph_candidate_provider(provider) is False


def test_candidate_set_does_not_overlap_company_level_axis():
    """The two classification axes must stay orthogonal — hunter/apollo are
    handled by emailability, never by the candidate tier."""
    assert GRAPH_CANDIDATE_PROVIDERS.isdisjoint(COMPANY_LEVEL_PROVIDERS)


def test_only_identified_is_verified():
    assert is_verified_identity("identified") is True


@pytest.mark.parametrize(
    "status",
    ["candidate", "anonymous", "unresolvable", "merged", "vpn_filtered", None, ""],
)
def test_everything_else_is_not_verified(status):
    """AC2: `candidate` is explicitly NOT a verified identity."""
    assert is_verified_identity(status) is False


@pytest.mark.parametrize("provider", ["rb2b", "leadpipe", "capturify"])
def test_candidates_remain_emailable(provider):
    """AC3: candidate-tier is an HONESTY signal, not a suppression signal.

    Locked SPEC decision: candidates stay emailable/exportable. This test exists
    to catch a future change that "helpfully" folds the candidate tier into
    is_emailable_identity — that would silently break outreach volume.
    """
    assert is_emailable_identity(provider, None, False) is True


def test_is_emailable_identity_still_takes_exactly_three_params():
    """Hard constraint: this phase must not widen the emailability signature."""
    import inspect

    params = list(inspect.signature(is_emailable_identity).parameters)
    assert params == ["provider", "source_agent_visit_id", "is_abuse_flagged"]
