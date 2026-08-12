"""Unit tests for the onboarding canary's pure assembly helpers.

Covers the ISP-vs-company ladder rung by rung, the "omit rather than guess"
rule, org-kind mapping, and every degraded geo path (including Null Island).
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.api.services.geoip import GeoResult
from apps.api.services.onboarding_canary import (
    MAX_PAGES,
    build_geo,
    build_network,
    fetch_journey,
)

pytestmark = pytest.mark.unit


def _geo(**kw) -> GeoResult:
    base = dict(
        country_code="VN", region="Hanoi", city="Hanoi",
        lat=21.03, lon=105.85, isp="", org="", as_str="",
    )
    base.update(kw)
    return GeoResult(**base)


def _no_asn():
    """Force the MaxMind rung dead (its DB path defaults to "" in this repo)."""
    return patch("apps.api.services.asn_lookup.lookup_asn", return_value=(None, None))


class TestNetworkLadder:
    def test_rung1_maxmind_asn_org_wins(self):
        with patch("apps.api.services.asn_lookup.lookup_asn",
                   return_value=(7552, "Viettel Group")):
            n = build_network("1.2.3.4", _geo(org="Something Else", isp="Also Else"))
        assert n["label"] == "Viettel Group"

    def test_rung2_ip_api_org_when_asn_dead(self):
        with _no_asn():
            n = build_network("1.2.3.4", _geo(org="Acme Inc", isp="Comcast"))
        assert n["label"] == "Acme Inc"

    def test_rung3_isp_when_org_empty(self):
        with _no_asn():
            n = build_network("1.2.3.4", _geo(org="", isp="Comcast Cable"))
        assert n["label"] == "Comcast Cable"

    def test_rung4_as_string_has_asn_prefix_stripped(self):
        with _no_asn():
            n = build_network("1.2.3.4", _geo(org="", isp="", as_str="AS7552 Viettel Group"))
        assert n["label"] == "Viettel Group"
        assert "AS7552" not in n["label"]

    def test_all_rungs_empty_omits_the_field(self):
        """Never render "Unknown ISP" — omit the line entirely."""
        with _no_asn():
            assert build_network("1.2.3.4", _geo()) is None

    def test_no_geo_and_no_asn_omits_the_field(self):
        with _no_asn():
            assert build_network("1.2.3.4", None) is None


class TestNetworkKind:
    def test_eyeball_with_distinct_org_is_company(self):
        with _no_asn():
            n = build_network("1.2.3.4", _geo(org="Acme Inc", isp="Comcast Cable"))
        assert n["kind"] == "company"

    def test_eyeball_with_org_equal_to_isp_is_isp(self):
        with _no_asn():
            n = build_network("1.2.3.4", _geo(org="Comcast Cable", isp="Comcast Cable"))
        assert n["kind"] == "isp"

    def test_datacenter_asn_maps_to_datacenter(self):
        with _no_asn():
            n = build_network("1.2.3.4", _geo(org="DigitalOcean, LLC",
                                              as_str="AS14061 DigitalOcean, LLC"))
        assert n["kind"] == "datacenter"

    def test_cdn_maps_to_relay(self):
        with _no_asn():
            n = build_network("1.2.3.4", _geo(org="Cloudflare, Inc.",
                                              as_str="AS13335 Cloudflare, Inc."))
        assert n["kind"] == "relay"

    def test_icloud_private_relay_ip_forces_relay(self):
        """Honest beats wrong: the pin is the relay's exit, not the user."""
        with _no_asn():
            n = build_network("2a09:bac3:1234::1", _geo(org="Acme Inc", isp="Comcast"))
        assert n["kind"] == "relay"


class TestAccessNetworkIsNotACompany:
    """Regression: an access-pool / registry `org` must never read as an employer.

    Both cases below were observed live on getbeam.fyi's own onboarding and both
    rendered as "looks like you're on X's network".
    """

    def test_registry_org_does_not_become_a_company(self):
        with _no_asn():
            n = build_network(
                "1.2.3.4",
                _geo(org="Vietnam Internet Network Information Center", isp=""),
            )
        assert n["kind"] != "company"

    def test_dynamic_pool_org_prefers_the_carrier(self):
        """`org` is the pool, `isp` is the real carrier — print the carrier."""
        with _no_asn():
            n = build_network("1.2.3.4", _geo(org="FPT DYNAMIC IP", isp="FPT Telecom"))
        assert n["kind"] == "isp"
        assert n["label"] == "FPT Telecom"

    def test_unspaced_pool_label_still_matched(self):
        """Real payloads arrive unspaced ("FPTDYNAMICIP") — substring, not word."""
        with _no_asn():
            n = build_network("1.2.3.4", _geo(org="FPTDYNAMICIP", isp=""))
        assert n["kind"] != "company"

    def test_pool_org_without_a_clean_isp_makes_no_claim(self):
        """No carrier to fall back on: use a kind both clients print bare."""
        with _no_asn():
            n = build_network("1.2.3.4", _geo(org="Some Broadband Pool", isp=""))
        assert n["kind"] == "network"
        assert n["label"] == "Some Broadband Pool"

    def test_real_company_still_promoted(self):
        """The guard must not swallow the case the feature exists for."""
        with _no_asn():
            n = build_network("1.2.3.4", _geo(org="Acme Inc", isp="Comcast Cable"))
        assert n["kind"] == "company"

    def test_nic_does_not_fire_inside_an_unrelated_word(self):
        with _no_asn():
            n = build_network("1.2.3.4", _geo(org="Technicolor SA", isp="Orange"))
        assert n["kind"] == "company"


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    """Returns visitor ids on the first execute, event rows on the second.

    The event rows are handed back NEWEST-FIRST, mirroring the `created_at DESC`
    the query now issues — the point of the assertions below.
    """

    def __init__(self, rows):
        self._results = [_FakeResult(["v1"]), _FakeResult(rows)]

    async def execute(self, _q):
        return self._results.pop(0)


def _pageview(path: str, at: datetime):
    return SimpleNamespace(
        event_type="pageview", page_path=path, page_title="", url="https://x" + path,
        time_on_page=0, created_at=at,
    )


class TestJourneyWindow:
    """The window must be anchored to NOW, never to the start of the hour."""

    @pytest.mark.asyncio
    async def test_keeps_the_newest_pages_not_the_oldest(self):
        base = datetime(2026, 8, 12, 10, 0, 0)
        total = MAX_PAGES + 4
        # Newest first, as the DESC query returns them.
        rows = [_pageview(f"/p{i}", base + timedelta(minutes=i)) for i in range(total)][::-1]

        pages = await fetch_journey(_FakeSession(rows), "fp2_abc", site_id="site_x")

        assert len(pages) == MAX_PAGES
        # The four oldest fell off — under the old head-slice these were the ONLY
        # ones kept, so a fresh visit could never be reported.
        assert [p["path"] for p in pages] == [f"/p{i}" for i in range(4, total)]

    @pytest.mark.asyncio
    async def test_result_is_in_reading_order(self):
        base = datetime(2026, 8, 12, 10, 0, 0)
        rows = [_pageview("/b", base + timedelta(minutes=1)), _pageview("/a", base)]

        pages = await fetch_journey(_FakeSession(rows), "fp2_abc", site_id="site_x")

        assert [p["path"] for p in pages] == ["/a", "/b"]
        assert pages[0]["at"] < pages[1]["at"]

    @pytest.mark.asyncio
    async def test_non_fp2_fingerprint_short_circuits(self):
        assert await fetch_journey(_FakeSession([]), "fp3_abc", site_id="site_x") == []


class TestBuildGeo:
    def test_full_geo(self):
        g = build_geo(_geo())
        assert g["lat"] == 21.03 and g["lng"] == 105.85
        assert g["city"] == "Hanoi" and g["country_code"] == "VN"
        assert g["accuracy_km"] > 0

    def test_none_input(self):
        assert build_geo(None) is None

    def test_missing_coordinates(self):
        assert build_geo(_geo(lat=None, lon=None)) is None

    def test_null_island_rejected(self):
        """0,0 is the Gulf of Guinea — never render a pin there."""
        assert build_geo(_geo(lat=0.0, lon=0.0)) is None

    def test_zero_lat_with_real_lon_is_kept(self):
        g = build_geo(_geo(lat=0.0, lon=105.85))
        assert g is not None and g["lng"] == 105.85
