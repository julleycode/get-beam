"""Tests for apps.api.services.company_resolver."""

import httpx
import pytest
from apps.api.config import settings as app_settings
from apps.api.services import company_resolver
from apps.api.services.company_resolver import (
    _extract_domain,
    is_datacenter_ip,
    resolve_company_from_ip,
)


class _FakeResp:
    def __init__(self, org, status=200):
        self.status_code = status
        self._org = org

    def json(self):
        return {"org": self._org}


def _fake_client(org, status=200):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _FakeResp(org, status)

    return _Client


@pytest.fixture
def _no_redis(monkeypatch):
    """Force the no-cache path so the httpx mock is exercised deterministically."""
    def _raise():
        raise RuntimeError("no redis in test")
    monkeypatch.setattr("apps.api.services.redis_client.get_redis", _raise)


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


class TestIsDatacenterIp:
    """is_datacenter_ip blocks cloud-compute traffic, fails open on errors."""

    @pytest.mark.asyncio
    async def test_private_ip_false(self):
        assert await is_datacenter_ip("192.168.1.1") is False

    @pytest.mark.asyncio
    async def test_empty_or_none_false(self):
        assert await is_datacenter_ip("") is False
        assert await is_datacenter_ip(None) is False

    @pytest.mark.asyncio
    async def test_no_token_false(self, monkeypatch):
        monkeypatch.setattr(app_settings, "ipinfo_token", "")
        assert await is_datacenter_ip("8.8.8.8") is False

    @pytest.mark.asyncio
    async def test_azure_ip_is_datacenter(self, monkeypatch, _no_redis):
        monkeypatch.setattr(app_settings, "ipinfo_token", "tok")
        monkeypatch.setattr(httpx, "AsyncClient", _fake_client("AS8075 Microsoft Corporation"))
        assert await is_datacenter_ip("135.232.20.19") is True

    @pytest.mark.asyncio
    async def test_aws_and_gcp_are_datacenter(self, monkeypatch, _no_redis):
        monkeypatch.setattr(app_settings, "ipinfo_token", "tok")
        monkeypatch.setattr(httpx, "AsyncClient", _fake_client("AS16509 Amazon.com, Inc."))
        assert await is_datacenter_ip("52.1.2.3") is True
        monkeypatch.setattr(httpx, "AsyncClient", _fake_client("AS396982 Google LLC"))
        assert await is_datacenter_ip("34.72.1.2") is True

    @pytest.mark.asyncio
    async def test_residential_isp_not_datacenter(self, monkeypatch, _no_redis):
        monkeypatch.setattr(app_settings, "ipinfo_token", "tok")
        monkeypatch.setattr(httpx, "AsyncClient", _fake_client("AS7922 Comcast Cable Communications, LLC"))
        assert await is_datacenter_ip("73.11.22.33") is False

    @pytest.mark.asyncio
    async def test_cloudflare_cdn_excluded(self, monkeypatch, _no_redis):
        # CDN/relay must NOT be treated as datacenter — Apple Private Relay / WARP
        # route real human traffic through these.
        monkeypatch.setattr(app_settings, "ipinfo_token", "tok")
        monkeypatch.setattr(httpx, "AsyncClient", _fake_client("AS13335 Cloudflare, Inc."))
        assert await is_datacenter_ip("1.1.1.1") is False

    @pytest.mark.asyncio
    async def test_fails_open_on_error(self, monkeypatch, _no_redis):
        monkeypatch.setattr(app_settings, "ipinfo_token", "tok")
        def _boom(*a, **k):
            raise RuntimeError("ipinfo down")
        monkeypatch.setattr(httpx, "AsyncClient", _boom)
        assert await is_datacenter_ip("135.232.20.19") is False
