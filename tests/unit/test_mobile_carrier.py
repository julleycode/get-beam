"""Unit tests for mobile-carrier detection (plan D5).

A mobile connection is the one case the two-provider cross-check cannot catch:
both providers agree on the carrier's registration city and both are wrong. So
these tests guard two boundaries at once — the seed carriers must be detected,
and the deliberately-liberal regex must NOT be so broad that it downgrades
fixed-line ISPs.
"""

import ast
import inspect
from types import SimpleNamespace

import pytest

from apps.api.services import mobile_carrier
from apps.api.services.mobile_carrier import _MOBILE_ASNS, is_mobile_carrier

pytestmark = pytest.mark.unit

IP = "1.2.3.4"


def _geo(as_str="", org="", isp=""):
    return SimpleNamespace(as_str=as_str, org=org, isp=isp)


class TestAsnDetection:
    def test_all_seven_seed_carriers_detected_by_asn(self):
        assert len(_MOBILE_ASNS) == 7
        for asn in _MOBILE_ASNS:
            assert is_mobile_carrier(IP, _geo(as_str=f"AS{asn} Some Carrier")) is True

    def test_unlisted_asn_is_not_mobile(self):
        assert is_mobile_carrier(IP, _geo(as_str="AS15169 Google LLC")) is False

    def test_fixed_line_fpt_asn_is_not_mobile(self):
        """AS18403 is FPT's residential fixed-line block — the incident address."""
        assert 18403 not in _MOBILE_ASNS
        assert is_mobile_carrier(IP, _geo(as_str="AS18403 FPT Telecom")) is False


class TestRegexFallback:
    @pytest.mark.parametrize(
        "org",
        [
            "Viettel Group",
            "MobiFone Corporation",
            "Vinaphone",
            "T-Mobile USA, Inc.",
            "Verizon Wireless",
            "AT&T Mobility LLC",
            "Some Cellular Network",
            "Acme Wireless",
            "Generic GSM Provider",
            "Foo LTE Services",
            "Bar 4G Networks",
            "Baz 5G Access",
        ],
    )
    def test_brand_and_generic_tokens_hit(self, org):
        assert is_mobile_carrier(IP, _geo(org=org)) is True

    def test_isp_field_is_checked_too(self):
        assert is_mobile_carrier(IP, _geo(isp="T-Mobile")) is True

    def test_fpt_telecom_fixed_line_is_not_mobile(self):
        """'telecom' is NOT a generic token — it would sweep in every fixed-line ISP."""
        assert is_mobile_carrier(IP, _geo(org="FPT Telecom", isp="FPT Telecom")) is False

    def test_mobilezone_datacenter_boundary(self):
        """Word-boundary anchored: 'Mobilezone' must NOT match 'mobile'."""
        assert is_mobile_carrier(IP, _geo(org="Mobilezone Datacenter GmbH")) is False

    def test_ordinary_isp_is_not_mobile(self):
        assert is_mobile_carrier(IP, _geo(org="Comcast Cable", isp="Comcast")) is False


class TestNeverRaises:
    @pytest.mark.parametrize(
        "geo",
        [None, object(), SimpleNamespace(), SimpleNamespace(as_str=None, org=None, isp=None)],
    )
    def test_malformed_geo_returns_false(self, geo):
        assert is_mobile_carrier(IP, geo) is False

    def test_empty_everything_is_false(self):
        assert is_mobile_carrier("", _geo()) is False


class TestPurity:
    def test_no_company_resolver_import(self):
        """D5: classify_org_kind's taxonomy is frozen; this module must not touch it."""
        source = inspect.getsource(mobile_carrier)
        # AST-level, not substring: the module docstring legitimately NAMES
        # company_resolver when explaining why it deliberately does not use it.
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all("company_resolver" not in a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert "company_resolver" not in (node.module or "")
                assert all("company_resolver" not in a.name for a in node.names)
