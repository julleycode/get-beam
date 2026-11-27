"""G1 — account rollup: pricing rule, param validation, null known-gap fields."""

import pytest
from pydantic import ValidationError

from apps.api.schemas.account_rollup import (
    KNOWN_GAPS,
    AccountDetail,
    AccountListParams,
    AccountListResponse,
    AccountRow,
)
from apps.api.services.account_rollup import is_pricing_url, normalize_path

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "url",
    [
        "/pricing",
        "/pricing/",
        "/pricing/teams",
        "https://acme.com/pricing?x=1",
        "https://acme.com/pricing/#plans",
        "HTTPS://ACME.com/Pricing",
        "http://www.acme.com:8080/pricing?utm=1#a",
    ],
)
def test_pricing_matches(url):
    assert is_pricing_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "/pricing-blog",
        "https://acme.com/pricing-blog",
        "https://acme.com/blog/pricing",
        "https://acme.com/?next=/pricing",
        "/",
        "",
        None,
    ],
)
def test_pricing_rejects(url):
    assert not is_pricing_url(url)


def test_normalize_path():
    assert normalize_path("https://acme.com/pricing?x=1#f") == "/pricing"
    assert normalize_path("/pricing?x=1") == "/pricing"
    assert normalize_path("https://acme.com") == "/"


def test_params_defaults_and_bounds():
    p = AccountListParams()
    assert (p.days, p.sort, p.page, p.page_size) == (30, "last_seen", 1, 25)
    for bad in ({"days": 0}, {"days": 366}, {"sort": "email"}, {"page": 0},
                {"page_size": 0}, {"page_size": 101}):
        with pytest.raises(ValidationError):
            AccountListParams(**bad)


def test_null_known_gap_fields_and_reasons():
    row = AccountRow(domain="acme.com")
    assert row.replies is None and row.pipeline_value_cents is None
    resp = AccountListResponse(accounts=[row], total=1, page=1, page_size=25, days=30,
                               sort="visitors")
    assert resp.known_gaps == KNOWN_GAPS
    assert any(g.startswith("replies") for g in resp.known_gaps)
    assert any(g.startswith("pipeline_value_cents") for g in resp.known_gaps)
    detail = AccountDetail(domain="acme.com", days=30)
    assert detail.replies is None and detail.campaigns == []


def test_shapes_carry_no_pii_fields():
    banned = {"email", "full_name", "phone", "ip_address", "visitor_id"}
    for model in (AccountRow, AccountDetail, AccountListResponse):
        assert not banned & set(model.model_fields)
