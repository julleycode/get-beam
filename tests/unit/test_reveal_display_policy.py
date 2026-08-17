"""The reveal display policy: map only when we are sure (plan D1-D3, D8).

The whole point of `choose_display_mode` being pure is that the policy table is
an exhaustive unit test rather than something only observable by holding a VPN in
the right city. Eight of the nine rows are testable at this boundary — row 7
(country disagreement) collapses to `geo is None` inside `build_geo` BEFORE the
decider runs, so at this function's boundary it is indistinguishable from row 8;
it is proven instead by the both-routes `reason` pair in the integration lane.
"""

import pytest

from apps.api.services.onboarding_canary import (
    apply_display_mode,
    build_geo,
    choose_display_mode,
)

pytestmark = pytest.mark.unit


def _geo(confidence="high", **kw):
    payload = {
        "lat": 21.0184,
        "lng": 105.8461,
        "accuracy_km": 25,
        "city": "Hanoi",
        "region": "Hanoi",
        "country_code": "VN",
        "confidence": confidence,
    }
    payload.update(kw)
    return payload


def _net(kind="isp"):
    return {"label": "Some Network", "kind": kind}


class TestDecisionTable:
    @pytest.mark.parametrize("kind", ["isp", "company", "network"])
    def test_row_1_map_when_high_user_owned_not_mobile(self, kind):
        assert choose_display_mode(_geo(), _net(kind), mobile=False) == "map"

    @pytest.mark.parametrize("kind", ["isp", "company", "network"])
    def test_row_2_mobile_downgrades_even_at_high_confidence(self, kind):
        """The mobile-agree centroid trap: both providers agree AND are wrong."""
        assert choose_display_mode(_geo(), _net(kind), mobile=True) == "country"

    @pytest.mark.parametrize("kind", ["relay", "datacenter", "cdn"])
    @pytest.mark.parametrize("mobile", [True, False])
    def test_row_3_relay_kinds_never_map(self, kind, mobile):
        assert choose_display_mode(_geo(), _net(kind), mobile=mobile) == "country"

    @pytest.mark.parametrize("kind", ["isp", "company", "network"])
    def test_row_4_unverified_is_country(self, kind):
        assert (
            choose_display_mode(_geo("unverified"), _net(kind), mobile=False) == "country"
        )

    @pytest.mark.parametrize("kind", ["relay", "datacenter", "cdn"])
    def test_row_5_unverified_relay_is_country(self, kind):
        assert (
            choose_display_mode(_geo("unverified"), _net(kind), mobile=True) == "country"
        )

    @pytest.mark.parametrize("kind", ["isp", "company", "network", "relay", "datacenter"])
    @pytest.mark.parametrize("mobile", [True, False])
    def test_row_6_low_is_always_country(self, kind, mobile):
        assert choose_display_mode(_geo("low"), _net(kind), mobile=mobile) == "country"

    def test_row_8_unusable_geo_is_none(self):
        assert choose_display_mode(None, _net(), mobile=False) == "none"
        assert choose_display_mode({}, _net(), mobile=False) == "none"

    def test_row_9_absent_network_label_still_maps(self):
        """No label at all is not a hosting claim — rung-5 empty must not block."""
        assert choose_display_mode(_geo(), None, mobile=False) == "map"
        assert choose_display_mode(_geo("low"), None, mobile=False) == "country"

    def test_relay_precedence_beats_mobile(self):
        """A VPN on a phone must read as a VPN, not as a phone."""
        assert choose_display_mode(_geo(), _net("relay"), mobile=True) == "country"


class TestApplyDisplayMode:
    def test_map_mode_passes_everything_through(self):
        geo = _geo()
        assert apply_display_mode(geo, "map") == geo

    def test_none_mode_returns_none(self):
        assert apply_display_mode(_geo(), "none") is None
        assert apply_display_mode(None, "none") is None

    def test_country_mode_omits_coordinates_entirely(self):
        out = apply_display_mode(_geo(), "country")
        assert "lat" not in out
        assert "lng" not in out
        assert "accuracy_km" not in out

    def test_country_mode_blanks_city_and_region_but_keeps_country(self):
        out = apply_display_mode(_geo(), "country")
        assert out["city"] == ""
        assert out["region"] == ""
        assert out["country_code"] == "VN"
        assert out["confidence"] == "high"

    def test_country_mode_preserves_disagree_km_when_present(self):
        out = apply_display_mode(_geo("low", disagree_km=93), "country")
        assert out["disagree_km"] == 93

    def test_country_mode_omits_disagree_km_when_absent(self):
        assert "disagree_km" not in apply_display_mode(_geo(), "country")


class _Geo:
    """Minimal GeoResult duck-type."""

    def __init__(self, **kw):
        self.lat = kw.get("lat", 21.0184)
        self.lon = kw.get("lon", 105.8461)
        self.city = kw.get("city", "Hanoi")
        self.region = kw.get("region", "Hanoi")
        self.country_code = kw.get("country_code", "VN")
        self.accuracy_km = kw.get("accuracy_km")


class TestCountryDisagreementCollapse:
    """Row 7 is decided in build_geo, not in the decider — this is where it lives."""

    def test_positive_disagreement_withholds_the_whole_payload(self):
        assert build_geo(_Geo(), country_agreed=False) is None

    def test_unknown_country_is_allowed(self):
        assert build_geo(_Geo(), country_agreed=None) is not None

    def test_agreed_country_is_allowed(self):
        assert build_geo(_Geo(), country_agreed=True) is not None

    def test_collapsed_row_7_reaches_the_decider_as_row_8(self):
        geo = build_geo(_Geo(), country_agreed=False)
        assert choose_display_mode(geo, _net(), mobile=False) == "none"
