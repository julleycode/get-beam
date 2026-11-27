"""G1 — closed-won read-back (closed-won-lookalikes). Mock + pure helpers only."""

import logging
from datetime import datetime, timezone

import pytest

from apps.api.config import settings
from apps.api.services.crm import get_crm_connector
from apps.api.services.crm import hubspot as hs
from apps.api.services.crm.pipedrive import pipedrive_deal_contacts
from apps.api.services.crm.salesforce import closed_won_soql, salesforce_opportunity_contacts
from apps.api.services.closed_won_seed import parse_closed_won_csv

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_on(monkeypatch):
    monkeypatch.setattr(settings, "mock_external_apis", True)


@pytest.mark.parametrize("provider", ["hubspot", "pipedrive", "salesforce"])
async def test_should_parse_mock_closed_won_deals_for_each_crm(mock_on, provider, caplog):
    caplog.set_level(logging.DEBUG)
    fetched = await get_crm_connector(provider).fetch_closed_won(
        access_token="t", instance_url="https://x.example", scopes=[hs.DEALS_SCOPE]
    )
    assert len(fetched.deals) == 3
    assert {d.external_deal_id for d in fetched.deals} == {
        f"mock-{provider}-deal-{i}" for i in (1, 2, 3)
    }
    for d in fetched.deals:
        assert d.email not in caplog.text


async def test_generic_webhook_has_no_poll_readback():
    with pytest.raises(NotImplementedError):
        await get_crm_connector("generic_webhook").fetch_closed_won()


def test_hubspot_won_stages_come_from_pipeline_metadata_not_literal():
    payload = {
        "results": [
            {
                "stages": [
                    {"id": "closedwon", "metadata": {"isClosed": "true", "probability": "1.0"}},
                    {"id": "custom_won_7", "metadata": {"isClosed": "true", "probability": "1.0"}},
                    {"id": "closedlost", "metadata": {"isClosed": "true", "probability": "0.0"}},
                    {"id": "open", "metadata": {"isClosed": "false", "probability": "1.0"}},
                    {"id": "broken", "metadata": {"isClosed": "true"}},
                ]
            }
        ]
    }
    assert hs.won_stage_ids(payload) == ["closedwon", "custom_won_7"]
    assert hs.won_stage_ids({"results": [{"stages": [{"id": "closedwon", "metadata": {}}]}]}) == []


def test_hubspot_search_body_filters_won_stages_and_rewindows_by_modified_time():
    since = datetime(2026, 11, 1, tzinfo=timezone.utc)
    body = hs.deals_search_body(["s1", "s2"], since, after="200")
    filters = body["filterGroups"][0]["filters"]
    assert filters[0] == {"propertyName": "dealstage", "operator": "IN", "values": ["s1", "s2"]}
    assert filters[1]["propertyName"] == "hs_lastmodifieddate"
    assert filters[1]["operator"] == "GTE"
    assert filters[1]["value"] == str(int(since.timestamp() * 1000))
    assert body["sorts"] == [{"propertyName": "hs_lastmodifieddate", "direction": "ASCENDING"}]
    assert body["after"] == "200"
    assert hs.SEARCH_RESULT_CAP == 10_000


def test_hubspot_scope_string_includes_deals_read():
    assert "crm.objects.deals.read" in hs._SCOPES.split()


async def test_hubspot_old_token_without_deals_scope_needs_reconnect(monkeypatch):
    monkeypatch.setattr(settings, "mock_external_apis", False)
    fetched = await get_crm_connector("hubspot").fetch_closed_won(
        access_token="tok", scopes=["crm.objects.contacts.read"]
    )
    assert fetched.needs_reconnect is True
    assert fetched.deals == []


async def test_hubspot_rewindows_past_search_cap(monkeypatch):
    """Simulate > cap results: after the cap the search restarts from window_max."""
    monkeypatch.setattr(settings, "mock_external_apis", False)
    monkeypatch.setattr(hs, "SEARCH_RESULT_CAP", 200)
    conn = hs.HubSpotConnector()
    calls: list[dict] = []
    t1 = "2026-11-02T00:00:00Z"
    t2 = "2026-11-03T00:00:00Z"

    async def fake_get(url, token):
        if "pipelines" in url:
            return {"results": [{"stages": [{"id": "w", "metadata": {"isClosed": "true", "probability": 1}}]}]}
        return {"results": []}

    async def fake_post(url, token, body):
        calls.append(body)
        window = body["filterGroups"][0]["filters"]
        has_since = len(window) > 1
        if not has_since:
            return {
                "results": [{"id": "d1", "properties": {"hs_lastmodifieddate": t1}}] * 100,
                "paging": {"next": {"after": "100"}},
            }
        return {"results": [{"id": "d2", "properties": {"hs_lastmodifieddate": t2}}]}

    monkeypatch.setattr(conn, "_get_json", fake_get)
    monkeypatch.setattr(conn, "_post_json", fake_post)
    fetched = await conn.fetch_closed_won(access_token="tok", scopes=[hs.DEALS_SCOPE])
    assert len(calls) >= 3
    assert calls[-1]["filterGroups"][0]["filters"][1]["value"] == str(
        int(datetime(2026, 11, 2, tzinfo=timezone.utc).timestamp() * 1000)
    )
    assert fetched.cursor == datetime(2026, 11, 3, tzinfo=timezone.utc)


def test_pipedrive_and_salesforce_parsers():
    deal = {
        "id": 42,
        "won_time": "2026-11-05 10:00:00",
        "person_id": {"email": [{"value": "a@b.example"}, {"value": ""}]},
    }
    out = pipedrive_deal_contacts(deal)
    assert [(d.external_deal_id, d.email) for d in out] == [("42", "a@b.example")]
    record = {
        "Id": "006X",
        "CloseDate": "2026-11-05",
        "OpportunityContactRoles": {"records": [{"Contact": {"Email": "c@d.example"}}]},
    }
    sf = salesforce_opportunity_contacts(record)
    assert [(d.external_deal_id, d.email) for d in sf] == [("006X", "c@d.example")]
    soql = closed_won_soql(datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert "IsWon = true" in soql and "OpportunityContactRoles" in soql
    assert "LastModifiedDate >= 2026-11-01T00:00:00Z" in soql


def test_csv_parser_requires_email_and_caps_rows():
    deals = parse_closed_won_csv("Email,Country\nx@y.example,us\n")
    assert deals[0].email == "x@y.example" and deals[0].country == "us"
    with pytest.raises(ValueError):
        parse_closed_won_csv("name\nbob\n")
    big = "email\n" + "\n".join(f"u{i}@x.example" for i in range(10_001)) + "\n"
    with pytest.raises(ValueError):
        parse_closed_won_csv(big)
