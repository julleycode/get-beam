"""G2b — Google lookalike_user_list payload (closed-won-lookalikes)."""

from types import SimpleNamespace

import httpx
import pytest

from apps.api.config import settings
from apps.api.services.ads import google
from apps.api.services.ads.base import LookalikeSpec

pytestmark = pytest.mark.unit

SPEC = LookalikeSpec(country="US", expansion="BALANCED")


def test_should_build_google_lookalike_user_list_payload():
    body = google.build_google_lookalike_request("customers/1/userLists/99", SPEC)
    lal = body["operations"][0]["create"]["lookalikeUserList"]
    assert lal == {"seedUserListIds": ["99"], "expansionLevel": "BALANCED", "countryCodes": ["US"]}


@pytest.mark.parametrize("country", ["DE", "FR", "NO", ""])
async def test_eea_and_unknown_country_fail_closed(monkeypatch, country):
    monkeypatch.setattr(settings, "mock_external_apis", True)
    res = await google.GoogleAdsProvider().create_lookalike(
        SimpleNamespace(), "seed", LookalikeSpec(country=country, expansion="BROAD")
    )
    assert res.status == "error" and "EEA" in res.error and not res.audience_id


async def test_duplicate_lookalike_is_treated_as_exists(monkeypatch):
    monkeypatch.setattr(settings, "mock_external_apis", False)
    monkeypatch.setattr(google, "_access_token", lambda c: "tok")
    monkeypatch.setattr(google, "_customer_id", lambda c: "1")

    async def fake_post(self, url, payload, token):
        req = httpx.Request("POST", url)
        resp = httpx.Response(400, text='{"error":{"details":[{"errorCode":"DUPLICATE_LOOKALIKE"}]}}', request=req)
        raise httpx.HTTPStatusError("bad", request=req, response=resp)

    monkeypatch.setattr(google.GoogleAdsProvider, "_ads_post", fake_post)
    res = await google.GoogleAdsProvider().create_lookalike(SimpleNamespace(), "customers/1/userLists/9", SPEC)
    assert res.status == "exists"


async def test_mock_create_has_demand_gen_note(monkeypatch):
    monkeypatch.setattr(settings, "mock_external_apis", True)
    res = await google.GoogleAdsProvider().create_lookalike(SimpleNamespace(), "seed", SPEC)
    assert res.audience_id and "Demand Gen" in res.warning


def test_small_seed_warning():
    assert google.google_seed_warning(settings.google_lookalike_min_seed - 1)
    assert google.google_seed_warning(settings.google_lookalike_min_seed) == ""
