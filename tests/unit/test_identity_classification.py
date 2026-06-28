"""Tests for apps.api.services.identity_classification.identity_level."""

import pytest
from apps.api.services.identity_classification import identity_level


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
