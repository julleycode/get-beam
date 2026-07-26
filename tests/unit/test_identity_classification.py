"""Tests for apps.api.services.identity_classification.identity_level."""

import pytest
from apps.api.services.identity_classification import (
    identity_level,
    is_emailable_identity,
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
