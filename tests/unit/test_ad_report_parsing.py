"""G2 / AC-2 — docs-shaped Meta/Google report parsing + mock determinism.

No network: every fixture is docs-derived (KG-1: live shapes unconfirmed).
"""

import asyncio
from datetime import date

import pytest

from apps.api.services.ads.google import (
    GoogleAdsProvider,
    build_google_ad_report_query,
    parse_google_search_stream,
)
from apps.api.services.ads.meta import (
    MetaAdsProvider,
    meta_conversions,
    meta_creative_text,
    parse_meta_insights,
)

pytestmark = pytest.mark.unit

META_PAGE = {
    "data": [
        {
            "ad_id": "23850001", "ad_name": "Ad A", "adset_name": "s", "campaign_name": "Camp",
            "impressions": "1500", "clicks": "45", "ctr": "3.0",
            "actions": [
                {"action_type": "link_click", "value": "45"},
                {"action_type": "lead", "value": "4"},
                {"action_type": "offsite_conversion.fb_pixel_lead", "value": "4"},
            ],
            "date_start": "2026-11-01", "date_stop": "2026-11-01",
        },
        {"ad_id": "23850002", "impressions": "not-a-number", "date_start": "2026-11-02"},
        {"ad_id": "23850003", "impressions": "10", "date_start": "garbage"},
        {"impressions": "10", "date_start": "2026-11-02"},
    ],
    "paging": {"cursors": {"after": "x"}},
}

META_CREATIVES = {
    "23850001": {"creative": {"object_story_spec": {"link_data": {
        "name": "Story headline", "message": "Story body", "link": "https://ex.com/pricing?utm=1"}}}},
    "23850002": {"creative": {"asset_feed_spec": {
        "titles": [{"text": ""}, {"text": "Dynamic title"}],
        "bodies": [{"text": "Dynamic body"}],
        "link_urls": [{"website_url": "https://ex.com/dyn"}]}}},
}

GOOGLE_STREAM = [
    {"results": [{
        "adGroupAd": {"ad": {
            "id": "777",
            "responsiveSearchAd": {
                "headlines": [{"text": "H1", "pinnedField": "HEADLINE_1"}, {"text": "H2"}, {"text": "H3"}, {"text": "H4"}],
                "descriptions": [{"text": "D1"}, {"text": "D2"}, {"text": "D3"}],
            },
            "finalUrls": ["https://ex.com/landing"],
        }},
        "campaign": {"name": "Search"},
        "segments": {"date": "2026-11-03"},
        "metrics": {"impressions": "2000", "clicks": "80", "ctr": 0.04, "conversions": 3.5,
                    "unknownMetric": "x"},
    }], "fieldMask": "..."},
    {"results": [{
        "adGroupAd": {"ad": {"id": "778"}},
        "segments": {"date": "2026-11-03"},
        "metrics": {},
    }]},
    {"results": [{"adGroupAd": {"ad": {}}, "segments": {"date": "2026-11-03"}}]},
]


def test_meta_parses_string_numerics_and_first_match_lead_without_summing():
    rows = parse_meta_insights([META_PAGE], META_CREATIVES)
    by_id = {r.platform_ad_id: r for r in rows}
    assert set(by_id) == {"23850001", "23850002"}  # bad date + missing ad_id dropped
    a = by_id["23850001"]
    assert (a.impressions, a.clicks, a.conversions) == (1500, 45, 4.0)  # NOT 8 (no summing)
    assert a.date == date(2026, 11, 1)
    assert (a.headline, a.body, a.landing_url) == ("Story headline", "Story body", "https://ex.com/pricing?utm=1")
    assert by_id["23850002"].impressions == 0  # junk numeric tolerated


def test_meta_asset_feed_spec_dynamic_creative():
    assert meta_creative_text(META_CREATIVES["23850002"]) == ("Dynamic title", "Dynamic body", "https://ex.com/dyn")
    assert meta_creative_text({}) == ("", "", "")


def test_meta_conversion_action_order_is_operator_configured(monkeypatch):
    from apps.api.config import settings

    actions = [{"action_type": "lead", "value": "2"}, {"action_type": "purchase", "value": "7"}]
    monkeypatch.setattr(settings, "ad_insights_meta_conversion_action_types", ["purchase", "lead"])
    assert meta_conversions(actions) == 7.0
    monkeypatch.setattr(settings, "ad_insights_meta_conversion_action_types", ["lead"])
    assert meta_conversions(actions) == 2.0
    assert meta_conversions(None) == 0.0


def test_meta_falls_back_to_ad_name_when_no_creative():
    rows = parse_meta_insights({"data": [{"ad_id": "9", "ad_name": "Named", "date_start": "2026-11-01"}]}, {})
    assert rows[0].headline == "Named"


def test_google_search_stream_array_of_batches():
    rows = parse_google_search_stream(GOOGLE_STREAM)
    assert [r.platform_ad_id for r in rows] == ["777", "778"]
    g = rows[0]
    assert (g.impressions, g.clicks, g.conversions) == (2000, 80, 3.5)
    assert g.headline == "H1 | H2 | H3" and g.body == "D1 D2"
    assert g.landing_url == "https://ex.com/landing" and g.campaign_name == "Search"
    assert rows[1].impressions == 0 and rows[1].headline == ""


def test_google_query_selects_fields_and_date_range():
    q = build_google_ad_report_query(date(2026, 10, 1), date(2026, 10, 31))
    assert "FROM ad_group_ad" in q and "'2026-10-01' AND '2026-10-31'" in q
    assert "campaign.name" in q and "metrics.conversions" in q


def test_mock_mode_is_deterministic_and_offline(monkeypatch):
    import httpx

    from apps.api.config import settings

    monkeypatch.setattr(settings, "mock_external_apis", True)

    def _boom(*a, **k):
        raise AssertionError("network used in mock mode")

    monkeypatch.setattr(httpx.AsyncClient, "send", _boom)

    async def run():
        m1 = await MetaAdsProvider().fetch_ad_performance(object(), date(2026, 11, 1), date(2026, 11, 2))
        m2 = await MetaAdsProvider().fetch_ad_performance(object(), date(2026, 11, 1), date(2026, 11, 2))
        g1 = await GoogleAdsProvider().fetch_ad_performance(object(), date(2026, 11, 1), date(2026, 11, 2))
        return m1, m2, g1

    m1, m2, g1 = asyncio.run(run())
    assert m1 == m2 and len(m1) == 8 and len(g1) == 2


def test_linkedin_reporting_not_supported():
    from apps.api.services.ads.linkedin import LinkedInAdsProvider

    with pytest.raises(NotImplementedError):
        asyncio.run(LinkedInAdsProvider().fetch_ad_performance(None, date.today(), date.today()))
