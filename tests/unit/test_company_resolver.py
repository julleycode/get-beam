"""Tests for apps.api.services.company_resolver."""

import pytest
from apps.api.services.company_resolver import _extract_domain, resolve_company_from_ip


class TestExtractDomain:
    """Test domain extraction from rDNS hostnames."""

    def test_simple_corporate_hostname(self):
        assert _extract_domain("mail.google.com") == "google.com"

    def test_deep_corporate_hostname(self):
        assert _extract_domain("vpn-us.corp.apple.com") == "apple.com"

    def test_country_code_tld(self):
        assert _extract_domain("mail.example.co.uk") == "example.co.uk"

    def test_returns_none_for_isp_hostname(self):
        assert _extract_domain("cpe-76-182-23-45.res.rr.com") is None  # roadrunner
        assert _extract_domain("c-73-45-12-34.hsd1.ca.comcast.net") is None

    def test_returns_none_for_vpn_hostname(self):
        assert _extract_domain("us-ny-123.nordvpn.com") is None
        assert _extract_domain("vpn-gateway.expressvpn.net") is None

    def test_returns_none_for_cloud_hostname(self):
        assert _extract_domain("ec2-52-14-123-45.us-east-2.compute.amazonaws.com") is None
        assert _extract_domain("vm-12345.googlecloud.internal") is None

    def test_returns_none_for_ip_string(self):
        assert _extract_domain("192.168.1.1") is None

    def test_returns_none_for_empty_string(self):
        assert _extract_domain("") is None

    def test_returns_none_for_single_part(self):
        assert _extract_domain("localhost") is None

    def test_real_corporate_domains(self):
        assert _extract_domain("outbound.mail.salesforce.com") == "salesforce.com"
        assert _extract_domain("proxy.microsoft.com") == "microsoft.com"

    def test_filters_residential_patterns(self):
        assert _extract_domain("dsl-pool-12.isp.residential.net") is None
        assert _extract_domain("dhcp-192-168-1-1.home.provider.net") is None

    def test_vn_isp_patterns(self):
        """Vietnamese ISPs should be filtered."""
        assert _extract_domain("static.fpt.vn") is None
        assert _extract_domain("123.vnpt.vn") is None


class TestResolveCompanyFromIp:
    """Test the full resolve function (async)."""

    @pytest.mark.asyncio
    async def test_private_ip_returns_none(self):
        assert await resolve_company_from_ip("192.168.1.1") is None
        assert await resolve_company_from_ip("10.0.0.1") is None
        assert await resolve_company_from_ip("127.0.0.1") is None

    @pytest.mark.asyncio
    async def test_empty_ip_returns_none(self):
        assert await resolve_company_from_ip("") is None
        assert await resolve_company_from_ip(None) is None

    @pytest.mark.asyncio
    async def test_invalid_ip_returns_none(self):
        """Invalid IPs should not crash, just return None."""
        result = await resolve_company_from_ip("not-an-ip")
        assert result is None
