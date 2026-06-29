"""Phase 9: the outbound gate — only person-level identities may be emailed /
exported to ad+CRM / alerted.

This is the highest-severity audit finding: hunter/apollo map IP -> company ->
a RANDOM employee, and that 'company-level' label was computed for the dashboard
but never enforced at any send gate (campaign_sender, csv_exporter, hot_alert).
"""

import pytest

from apps.api.services.identity_classification import (
    COMPANY_LEVEL_PROVIDERS,
    PERSON_LEVEL_PROVIDERS,
    identity_level,
    is_emailable_identity,
)


@pytest.mark.parametrize("provider", sorted(COMPANY_LEVEL_PROVIDERS))
def test_company_level_is_not_emailable(provider):
    assert identity_level(provider) == "company"
    assert is_emailable_identity(provider) is False


@pytest.mark.parametrize("provider", sorted(PERSON_LEVEL_PROVIDERS))
def test_person_level_is_emailable(provider):
    assert identity_level(provider) == "person"
    assert is_emailable_identity(provider) is True


@pytest.mark.parametrize("provider", [None, "", "unknown_future", "ipinfo", "pdl_ip_enrich"])
def test_unknown_provider_is_not_emailable(provider):
    # An unclassified provider defaults to NOT emailable — a new provider must be
    # added to PERSON_LEVEL_PROVIDERS explicitly, so the hole can't silently
    # reopen for anything not yet classified.
    assert is_emailable_identity(provider) is False


def test_real_person_providers_stay_emailable():
    # Regression guard: these are saved as resolution_provider for REAL people
    # (the last two were missing from the set originally — would have wrongly
    # blocked legitimate sends).
    for p in ("form_capture", "pdl_person_enrich", "rb2b", "leadpipe",
              "capturify", "manual", "fingerprint_match", "beam_identity_network"):
        assert is_emailable_identity(p) is True, p


def test_hunter_apollo_blocked():
    assert is_emailable_identity("hunter") is False
    assert is_emailable_identity("apollo") is False
