"""D5/D10 — the `candidate_outreach_enabled` confirm-gate WRAPPER.

The gate is deliberately NOT a parameter on `is_emailable_identity()` (that
helper keeps its 3-parameter signature, enforced by
`test_identity_classification.py::test_is_emailable_identity_still_takes_exactly_three_params`).
It lives as a wrapper at exactly 3 outreach call sites:

  * `services/campaign_sender.py`   — email send gate
  * `services/csv_exporter.py`      — ad/CRM export
  * `routers/campaigns.py`          — LinkedIn target resolution

`services/hot_alert.py` and `services/outcome_digest.py` are EXPLICITLY excluded:
both use `is_emailable_identity()` to decide what the SITE OWNER sees (name
reveal / digest ranking), never to send anything to the candidate.

These tests exercise the wrapper's decision logic directly (pure, no DB), which
is the same expression pasted at all 3 sites, plus structural assertions that the
wiring is actually present at those 3 sites and absent from the 2 excluded ones.
"""

import inspect

import pytest

import apps.api.main  # noqa: F401 — register ORM mappers
from apps.api.config import settings
from apps.api.services.identity_classification import (
    COMPANY_LEVEL_PROVIDERS,
    GRAPH_CANDIDATE_PROVIDERS,
    PERSON_LEVEL_PROVIDERS,
    is_emailable_identity,
    is_graph_candidate_provider,
    is_verified_identity,
)

pytestmark = pytest.mark.unit


def _gate(provider, identity_status, flag_on, *, agent_marker=None, abuse=False):
    """The exact wrapper expression used at all 3 in-scope call sites."""
    emailable = is_emailable_identity(provider, agent_marker, abuse)
    if emailable and is_graph_candidate_provider(provider) and not flag_on:
        emailable = is_verified_identity(identity_status)
    return emailable


# --- default posture --------------------------------------------------------


def test_flag_defaults_off():
    """Merging this reconciliation must not widen prod outreach by itself."""
    assert settings.candidate_outreach_enabled is False


# --- OFF state --------------------------------------------------------------


@pytest.mark.parametrize("provider", sorted(GRAPH_CANDIDATE_PROVIDERS))
def test_off_blocks_unconfirmed_graph_candidate(provider):
    assert _gate(provider, "candidate", flag_on=False) is False


@pytest.mark.parametrize("provider", sorted(GRAPH_CANDIDATE_PROVIDERS))
@pytest.mark.parametrize("status", ["anonymous", "unresolvable", "merged", None, ""])
def test_off_blocks_every_non_identified_status(provider, status):
    """Fails safe: anything that is not explicitly confirmed is held back."""
    assert _gate(provider, status, flag_on=False) is False


@pytest.mark.parametrize("provider", sorted(GRAPH_CANDIDATE_PROVIDERS))
def test_off_allows_human_confirmed_candidate(provider):
    """The confirm workflow is a real, deliberate exception to the OFF state —
    a human clicking confirm sets identity_status="identified" and that identity
    becomes contactable regardless of the flag. This is D9/§9, by design."""
    assert _gate(provider, "identified", flag_on=False) is True


@pytest.mark.parametrize(
    "provider", sorted(PERSON_LEVEL_PROVIDERS - GRAPH_CANDIDATE_PROVIDERS)
)
def test_off_does_not_touch_non_graph_providers(provider):
    """form_capture / manual / pdl_person_enrich / svid_reconcile /
    fingerprint_match / contact_import are deterministic or human-entered — the
    confirm-gate must not narrow them even on a candidate-ish status."""
    assert _gate(provider, "candidate", flag_on=False) is True
    assert _gate(provider, None, flag_on=False) is True


# --- ON state ---------------------------------------------------------------


@pytest.mark.parametrize("provider", sorted(GRAPH_CANDIDATE_PROVIDERS))
@pytest.mark.parametrize("status", ["candidate", "anonymous", "identified", None])
def test_on_restores_the_wide_d2_rule(provider, status):
    assert _gate(provider, status, flag_on=True) is True


# --- the wrapper can only narrow, never widen -------------------------------


@pytest.mark.parametrize("provider", sorted(COMPANY_LEVEL_PROVIDERS) + [None, "unknown"])
@pytest.mark.parametrize("flag_on", [True, False])
def test_wrapper_never_widens_a_non_emailable_provider(provider, flag_on):
    assert is_emailable_identity(provider) is False
    assert _gate(provider, "identified", flag_on=flag_on) is False


@pytest.mark.parametrize("provider", sorted(GRAPH_CANDIDATE_PROVIDERS))
@pytest.mark.parametrize("flag_on", [True, False])
def test_agent_origin_guardrail_survives_the_wrapper(provider, flag_on):
    """AC10: the agent-origin veto is unconditional and the wrapper (which only
    ever ANDs a further restriction) can never reopen it."""
    assert _gate(provider, "identified", flag_on, agent_marker="fake-uuid") is False


@pytest.mark.parametrize("provider", sorted(GRAPH_CANDIDATE_PROVIDERS))
@pytest.mark.parametrize("flag_on", [True, False])
def test_abuse_flag_guardrail_survives_the_wrapper(provider, flag_on):
    assert _gate(provider, "identified", flag_on, abuse=True) is False


# --- structural wiring: the 3 in-scope sites, and the 2 exclusions ----------


def _source_of(module_path, attr):
    import importlib

    mod = importlib.import_module(module_path)
    return inspect.getsource(getattr(mod, attr))


@pytest.mark.parametrize(
    "module_path,attr",
    [
        ("apps.api.services.campaign_sender", "send_campaign_emails"),
        ("apps.api.services.csv_exporter", "_get_segment_visitors"),
        ("apps.api.routers.campaigns", "_resolve_linkedin_targets"),
    ],
)
def test_in_scope_call_sites_carry_the_wrapper(module_path, attr):
    src = _source_of(module_path, attr)
    assert "candidate_outreach_enabled" in src, attr
    assert "is_graph_candidate_provider" in src, attr
    assert "is_verified_identity" in src, attr


@pytest.mark.parametrize(
    "module_path",
    ["apps.api.services.hot_alert", "apps.api.services.outcome_digest"],
)
def test_excluded_sites_do_not_carry_the_wrapper(module_path):
    """Owner-facing name-reveal / digest ranking must NOT be gated behind an
    outreach-consent flag — gating them would suppress a legitimate alert."""
    import importlib

    src = inspect.getsource(importlib.import_module(module_path))
    assert "candidate_outreach_enabled" not in src, module_path


def test_is_emailable_identity_signature_untouched():
    """Hard constraint (D3): the shared helper keeps exactly 3 parameters. The
    confirm-gate is a wrapper, never a 4th parameter here."""
    params = list(inspect.signature(is_emailable_identity).parameters)
    assert params == ["provider", "source_agent_visit_id", "is_abuse_flagged"]
