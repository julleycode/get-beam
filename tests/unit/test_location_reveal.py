"""Unit tests for the onboarding canary's pure assembly helpers.

Covers the ISP-vs-company ladder rung by rung, the "omit rather than guess"
rule, org-kind mapping, and every degraded geo path (including Null Island).
"""

from unittest.mock import patch

import pytest

from apps.api.services.geoip import GeoResult
from apps.api.services.onboarding_canary import build_geo, build_network

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
