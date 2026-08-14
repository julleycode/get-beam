"""Unit tests for the two-provider geo cross-check and the claim it weakens.

The bug this whole path exists for, measured on a real residential FPT address
(AS18403): ip-api says Hanoi, ipinfo says Haiphong, the human is in Ho Chi Minh
City. So the fixture coordinates below are the REAL ones from that incident
rather than round numbers — a regression here should fail against the case that
actually happened.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from apps.api.services.geoip import GeoResult
from apps.api.services.geoip_crosscheck import (
    CrossCheck,
    _point_from,
    crosscheck_geo,
    haversine_km,
)
from apps.api.services.onboarding_canary import build_geo

pytestmark = pytest.mark.unit

# The three answers for 42.117.132.191.
HANOI = (21.0184, 105.8461)      # ip-api
HAIPHONG = (20.8648, 106.6834)   # ipinfo
HCMC = (10.8231, 106.6297)       # the actual human


def _geo(**kw) -> GeoResult:
    base = dict(
        country_code="VN", region="Hanoi", city="Hanoi",
        lat=HANOI[0], lon=HANOI[1],
    )
    base.update(kw)
    return GeoResult(**base)


def _settings(**kw):
    """Patch only the cross-check knobs, leaving the rest of Settings alone."""
    base = dict(
        geo_crosscheck_enabled=True,
        geo_crosscheck_disagree_km=50,
        geo_crosscheck_max_radius_km=300,
        mock_external_apis=False,
        ipinfo_token="",
    )
    base.update(kw)
    return patch.multiple("apps.api.services.geoip_crosscheck.settings", **base)


class TestHaversine:
    def test_zero_distance(self):
        assert haversine_km(*HANOI, *HANOI) == 0.0

    def test_hanoi_to_haiphong_is_about_90km(self):
        # The disagreement that must FAIL the 50km gate.
        d = haversine_km(*HANOI, *HAIPHONG)
        assert 80 < d < 100, d

    def test_hanoi_to_hcmc_is_about_1150km(self):
        d = haversine_km(*HANOI, *HCMC)
        assert 1100 < d < 1200, d

    def test_symmetric(self):
        assert haversine_km(*HANOI, *HCMC) == pytest.approx(
            haversine_km(*HCMC, *HANOI)
        )

    def test_antipodal_does_not_domain_error(self):
        # asin() of a float that rounds just past 1.0 raises without the clamp.
        assert haversine_km(0.0, 0.0, 0.0, 180.0) == pytest.approx(20015, abs=5)

    def test_east_west_shorter_than_north_south_at_20n(self):
        """The reason this is haversine and not a flat euclidean metric."""
        ns = haversine_km(20.0, 105.0, 21.0, 105.0)
        ew = haversine_km(20.0, 105.0, 20.0, 106.0)
        assert ew < ns


class TestPointParsing:
    def test_parses_ipinfo_loc_string(self):
        assert _point_from({"loc": "20.8648,106.6834", "city": "Haiphong"}) == (
            20.8648, 106.6834, "Haiphong",
        )

    def test_missing_loc(self):
        assert _point_from({"city": "Haiphong"}) is None

    def test_malformed_loc(self):
        assert _point_from({"loc": "not-a-pair"}) is None
        assert _point_from({"loc": "20.8,"}) is None
        assert _point_from({"loc": 12345}) is None

    def test_null_island_rejected(self):
        """0,0 is ipinfo's "no idea" and would fake a 10,000km disagreement."""
        assert _point_from({"loc": "0,0"}) is None

    def test_missing_city_is_empty_not_none(self):
        assert _point_from({"loc": "1,2"})[2] == ""


class TestCrossCheckGeo:
    @pytest.mark.asyncio
    async def test_disabled_flag_returns_unchecked(self):
        with _settings(geo_crosscheck_enabled=False):
            result = await crosscheck_geo("1.2.3.4", _geo())
        assert result == CrossCheck()
        assert result.checked is False

    @pytest.mark.asyncio
    async def test_primary_without_coordinates_returns_unchecked(self):
        with _settings():
            result = await crosscheck_geo("1.2.3.4", _geo(lat=None, lon=None))
        assert result.checked is False

    @pytest.mark.asyncio
    async def test_mock_mode_agrees_without_network(self):
        """MOCK_EXTERNAL_APIS must never render the degraded copy locally."""
        with _settings(mock_external_apis=True):
            result = await crosscheck_geo("1.2.3.4", _geo())
        assert result.checked is True
        assert result.agreed is True

    @pytest.mark.asyncio
    async def test_agreement_within_threshold(self):
        near = (HANOI[0] + 0.05, HANOI[1] + 0.05, "Hanoi")
        with _settings(), patch(
            "apps.api.services.geoip_crosscheck._lookup_second",
            AsyncMock(return_value=near),
        ):
            result = await crosscheck_geo("1.2.3.4", _geo())
        assert result.checked is True
        assert result.agreed is True

    @pytest.mark.asyncio
    async def test_the_real_incident_disagrees(self):
        with _settings(), patch(
            "apps.api.services.geoip_crosscheck._lookup_second",
            AsyncMock(return_value=(*HAIPHONG, "Haiphong")),
        ):
            result = await crosscheck_geo("42.117.132.191", _geo())
        assert result.checked is True
        assert result.agreed is False
        assert 80 < result.distance_km < 100
        assert result.second_city == "Haiphong"

    @pytest.mark.asyncio
    async def test_second_provider_down_is_unchecked_not_disagreed(self):
        """A dead provider must not degrade the claim — that is a false alarm."""
        with _settings(), patch(
            "apps.api.services.geoip_crosscheck._lookup_second",
            AsyncMock(return_value=None),
        ):
            result = await crosscheck_geo("1.2.3.4", _geo())
        assert result.checked is False
        assert result.agreed is False


class TestBuildGeoConfidence:
    def test_no_crosscheck_is_unverified_and_unchanged(self):
        out = build_geo(_geo())
        assert out["confidence"] == "unverified"
        assert out["city"] == "Hanoi"
        assert out["accuracy_km"] == 25
        assert "disagree_km" not in out

    def test_agreement_keeps_the_city(self):
        out = build_geo(_geo(), crosscheck=CrossCheck(checked=True, agreed=True,
                                                      distance_km=3.0))
        assert out["confidence"] == "high"
        assert out["city"] == "Hanoi"
        assert out["accuracy_km"] == 25

    def test_disagreement_strips_city_and_region_server_side(self):
        """The name must not be SENT, not merely not rendered."""
        out = build_geo(
            _geo(),
            crosscheck=CrossCheck(checked=True, agreed=False, distance_km=93.4),
        )
        assert out["confidence"] == "low"
        assert out["city"] == ""
        assert out["region"] == ""
        # Country survives: it is the one claim both providers still agree on.
        assert out["country_code"] == "VN"

    def test_disagreement_radius_covers_both_answers(self):
        out = build_geo(
            _geo(),
            crosscheck=CrossCheck(checked=True, agreed=False, distance_km=93.4),
        )
        assert out["disagree_km"] == 93
        assert out["accuracy_km"] == 93

    def test_radius_capped_so_it_does_not_swallow_the_country(self):
        out = build_geo(
            _geo(),
            crosscheck=CrossCheck(checked=True, agreed=False, distance_km=1150.0),
        )
        assert out["disagree_km"] == 1150       # the truth is reported
        assert out["accuracy_km"] == 300        # the drawn circle is capped

    def test_measured_accuracy_wins_when_larger_than_disagreement(self):
        """A GeoLite2-City radius is never narrowed by the cross-check."""
        out = build_geo(
            _geo(accuracy_km=200),
            crosscheck=CrossCheck(checked=True, agreed=False, distance_km=10.0),
        )
        assert out["accuracy_km"] == 200

    def test_sub_kilometre_disagreement_still_reports_at_least_1(self):
        out = build_geo(
            _geo(),
            crosscheck=CrossCheck(checked=True, agreed=False, distance_km=0.2),
        )
        assert out["disagree_km"] == 1

    def test_unchecked_crosscheck_leaves_the_claim_alone(self):
        out = build_geo(_geo(), crosscheck=CrossCheck())
        assert out["confidence"] == "unverified"
        assert out["city"] == "Hanoi"

    def test_duck_typed_crosscheck(self):
        """build_geo reads attributes, so a plain namespace must work."""
        out = build_geo(
            _geo(),
            crosscheck=SimpleNamespace(checked=True, agreed=False, distance_km=93.4),
        )
        assert out["confidence"] == "low"

    def test_null_island_still_rejected_with_a_crosscheck(self):
        assert build_geo(
            _geo(lat=0.0, lon=0.0),
            crosscheck=CrossCheck(checked=True, agreed=True),
        ) is None


class TestIpFamily:
    """The v4-vs-v6 tag. Pure, and must never raise on hostile input — it runs
    on the reveal path, which is not allowed to 500."""

    def test_v4(self):
        from apps.api.services.ip_resolution import ip_family

        assert ip_family("42.117.132.191") == "v4"

    def test_v6(self):
        from apps.api.services.ip_resolution import ip_family

        assert ip_family("2606:4700:3036::ac43:bda4") == "v6"

    def test_v6_shorthand_and_loopback(self):
        from apps.api.services.ip_resolution import ip_family

        assert ip_family("::1") == "v6"
        assert ip_family("127.0.0.1") == "v4"

    def test_whitespace_tolerated(self):
        from apps.api.services.ip_resolution import ip_family

        assert ip_family("  42.117.132.191  ") == "v4"

    def test_unparseable_is_empty_not_an_exception(self):
        from apps.api.services.ip_resolution import ip_family

        for bad in ("", "   ", "unknown", "not-an-ip", "999.999.999.999", "1.2.3"):
            assert ip_family(bad) == ""

    def test_ipv4_mapped_v6_reports_v6(self):
        """`::ffff:1.2.3.4` arrives as a v6 socket; reporting it as v4 would
        make the two buckets disagree with what the connection actually used."""
        from apps.api.services.ip_resolution import ip_family

        assert ip_family("::ffff:1.2.3.4") == "v6"
