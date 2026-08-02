"""Phase 9 + P0: outbound gate — only EMAILABLE_PROVIDERS may be emailed /
exported to ad+CRM / alerted.

Company-level (hunter/apollo) and probabilistic paid person-graphs
(rb2b/leadpipe/capturify) are never outreach targets.
"""

import pytest

from apps.api.services.identity_classification import (
    COMPANY_LEVEL_PROVIDERS,
    EMAILABLE_PROVIDERS,
    PAID_PERSON_GRAPH_PROVIDERS,
    PERSON_LEVEL_PROVIDERS,
    identity_level,
    is_emailable_identity,
)


@pytest.mark.parametrize("provider", sorted(COMPANY_LEVEL_PROVIDERS))
def test_company_level_is_not_emailable(provider):
    assert identity_level(provider) == "company"
    assert is_emailable_identity(provider) is False


@pytest.mark.parametrize("provider", sorted(EMAILABLE_PROVIDERS))
def test_emailable_providers_are_emailable(provider):
    assert identity_level(provider) == "person"
    assert is_emailable_identity(provider) is True


@pytest.mark.parametrize("provider", sorted(PAID_PERSON_GRAPH_PROVIDERS))
def test_paid_person_graphs_not_emailable(provider):
    assert identity_level(provider) == "person"
    assert is_emailable_identity(provider) is False


@pytest.mark.parametrize("provider", [None, "", "unknown_future", "ipinfo", "pdl_ip_enrich"])
def test_unknown_provider_is_not_emailable(provider):
    # An unclassified provider defaults to NOT emailable — a new provider must be
    # added to EMAILABLE_PROVIDERS explicitly, so the hole can't silently
    # reopen for anything not yet classified.
    assert is_emailable_identity(provider) is False


def test_real_owned_providers_stay_emailable():
    for p in (
        "form_capture",
        "pdl_person_enrich",
        "manual",
        "fingerprint_match",
        "beam_identity_network",
        "svid_reconcile",
    ):
        assert p in EMAILABLE_PROVIDERS
        assert is_emailable_identity(p) is True, p
    # Paid graphs remain person-level for display but are not outreach targets.
    for p in ("rb2b", "leadpipe", "capturify"):
        assert p in PERSON_LEVEL_PROVIDERS
        assert is_emailable_identity(p) is False, p


def test_hunter_apollo_blocked():
    assert is_emailable_identity("hunter") is False
    assert is_emailable_identity("apollo") is False
