"""Tests for apps.api.services.company_resolver."""

import httpx
import pytest
from apps.api.config import settings as app_settings
from apps.api.services import company_resolver
from apps.api.services.company_resolver import (
    _extract_domain,
    is_datacenter_ip,
    is_privacy_relay_ip,
    is_proxy_or_vpn,
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


class TestClassifyOrgKind:
    """Unit coverage for classify_org_kind — the shared ASN/name classifier that
    drives both the ingest datacenter drop and the resolver fabrication guard."""

    @pytest.mark.parametrize("org", [
        "AS207990 HostRoyale Technologies Pvt Ltd",  # ASN + name
        "AS20473 The Constant Company, LLC",          # ASN (Vultr)
        "AS54825 Packet Host, Inc.",                  # ASN-ONLY (name not tokened)
        "AS53667 FranTech Solutions",                 # ASN-only
        "AS3356 Level 3 Parent, LLC",                 # name-token "as3356 "
        "AS32934 Facebook, Inc.",                     # crawler
        "AS8075 Microsoft Corporation",               # via NAME token (ASN deliberately excluded)
        "AS64267 Sprious LLC",                        # proxy-scraper net (ASN 64267 + name)
        "AS396319 Oxylabs",                           # proxy net (ASN 396319 + name)
        "AS64286 LogicWeb Inc.",                      # cheap hosting (ASN 64286)
        "AS398781 OCULUS NETWORKS INC",               # hosting/proxy (ASN 398781)
        "AS20001 Charter, host reassigned to Sprious",  # NAME-token catch when ASN is a residential parent
    ])
    def test_datacenter(self, org):
        assert company_resolver.classify_org_kind(org) == "datacenter"

    @pytest.mark.parametrize("org", [
        "AS54113 Fastly, Inc.",
        "AS13335 Cloudflare, Inc.",
        "AS714 Apple Inc.",
        "AS20940 Akamai International B.V.",
    ])
    def test_cdn_relay(self, org):
        # Kept at ingest (humans behind Private Relay/WARP) but blocked from fabrication.
        assert company_resolver.classify_org_kind(org) == "cdn"

    @pytest.mark.parametrize("org", [
        "AS7029 Windstream Communications LLC",
        "AS7922 Comcast Cable Communications, LLC",
        "AS22773 Cox Communications Inc.",
        "AS7018 AT&T Enterprises, LLC",
        "AS45899 VNPT",
        "AS33560 Some Random ISP",   # adjacency: must NOT match "as3356 "
        "",
        None,
    ])
    def test_eyeball(self, org):
        assert company_resolver.classify_org_kind(org) == "eyeball"


class TestIsProxyOrVpn:
    """is_proxy_or_vpn drives the ingest proxy drop — proxy/VPN/Tor/hosting drop,
    but relay (Apple Private Relay / Cloudflare WARP = real humans) must NOT."""

    @pytest.mark.parametrize("flag", ["proxy", "vpn", "tor", "hosting"])
    def test_dropped_flags(self, flag):
        assert is_proxy_or_vpn({flag: True}) is True

    def test_relay_only_not_dropped(self):
        # Apple Private Relay: relay=True, everything else False → real human, keep.
        assert is_proxy_or_vpn(
            {"vpn": False, "proxy": False, "tor": False, "relay": True, "hosting": False}
        ) is False

    def test_clean_ip_not_dropped(self):
        assert is_proxy_or_vpn(
            {"vpn": False, "proxy": False, "tor": False, "relay": False, "hosting": False}
        ) is False

    @pytest.mark.parametrize("privacy", [None, {}])
    def test_missing_privacy_not_dropped(self, privacy):
        # check_ip_privacy returns None when disabled/failed → fail-open (keep event).
        assert is_proxy_or_vpn(privacy) is False


class TestIsPrivacyRelayIp:
    """Local fail-closed gate for known iCloud Private Relay client prefixes."""

    def test_known_prefix(self):
        assert is_privacy_relay_ip("2a09:bac3:627a:3050::4d0:11") is True

    def test_unrelated_ip(self):
        assert is_privacy_relay_ip("8.8.8.8") is False


class TestIpinfoFabricationGuard:
    """The ipinfo resolver must refuse to derive a company domain from a
    datacenter OR cdn org — that path fabricated cdurham@fastly.com."""

    def _mixin(self):
        from apps.api.services.identity_providers.ipinfo import IPinfoMixin
        return IPinfoMixin()

    @pytest.mark.parametrize("org", [
        "AS54113 Fastly, Inc.",                      # CDN — the real false-positive source
        "AS207990 HostRoyale Technologies Pvt Ltd",  # hosting
        "AS8075 Microsoft Corporation",              # cloud — no guessed employee
    ])
    def test_no_domain_from_infra_org(self, org):
        assert self._mixin()._org_to_domain(org) is None

    def test_real_corporate_office_still_resolves(self):
        # A genuine (non-datacenter, non-cdn) corporate org still yields a domain.
        assert self._mixin()._org_to_domain("AS400618 Prime Security Corp.") == "primesecurity.com"


class TestExtractDomainNewlyRejected:
    """WS-D group iii / G21 (AC-D3): hosts that resolve to a domain TODAY but
    return None after the PSL change. Both NARROWS subclasses (P2-12), asserted
    at the RESOLVER layer. Each comment names the OLD return value.

    Per R12 the ICANN/amazonaws proof lives in test_public_suffix.py, NOT here —
    test_returns_none_for_cloud_hostname above already asserts None for that host
    and the two must not contradict.
    """

    # Subclass (i): domain-filter-caught ISP hosts (known ISP brands).
    def test_talktalk_two_part_tld_isp_host_now_rejected(self):
        # OLD: 'talktalk.co.uk' (early return bypassed both filters).
        # NOW: registrable talktalk.co.uk → _build_domain_filter_regex fires
        # ('talktalk' is a _DOMAIN_PATTERNS entry) → None.
        assert _extract_domain("dsl-pool.host.talktalk.co.uk") is None

    def test_virgin_two_part_tld_isp_host_now_rejected(self):
        # OLD: 'virgin.co.uk'. NOW: domain filter ('virgin') → None.
        assert _extract_domain("c-1-2-3.hsd1.virgin.co.uk") is None

    # Subclass (ii): hostname-filter-only — the lost value is a REAL corporate
    # domain, not an ISP. This is the higher-impact half (P2-12).
    def test_hostname_filter_only_on_a_real_corporate_domain_now_rejected(self):
        # OLD: 'acme.co.uk' — a REAL corporate domain, NOT an ISP. 'acme' is not
        # in _DOMAIN_PATTERNS so the domain filter passes; _build_hostname_filter
        # fires on the 'dhcp' token → None. The evidence (a DHCP-pool hostname)
        # is too weak to assert employment, so the narrowing is correct.
        assert _extract_domain("dhcp-1-2-3.acme.co.uk") is None

    # Corrected cases: hosts that returned a bare public suffix TODAY.
    def test_corrected_gov_br(self):
        # OLD: 'gov.br' (a public suffix returned as a company domain).
        assert _extract_domain("foo.bar.gov.br") == "bar.gov.br"

    def test_corrected_co_za(self):
        # OLD: 'co.za' (public suffix). NOW suffix + one label (D2 spec).
        assert _extract_domain("x.co.za") == "x.co.za"


class TestExtractDomainNewlyWidened:
    """WS-D group iv / G22 (AC-D4): the highest-volume half — 3-label hosts under
    the eight old hardcoded suffixes returned None today (bare `return None` at
    the old :110) and now return their own registrable domain. A regression-only
    gate cannot see this class. Each comment names the OLD None.
    """

    def test_google_co_uk_now_resolves(self):
        assert _extract_domain("google.co.uk") == "google.co.uk"  # OLD: None

    def test_bbc_co_uk_now_resolves(self):
        assert _extract_domain("bbc.co.uk") == "bbc.co.uk"  # OLD: None

    def test_acme_com_au_now_resolves(self):
        assert _extract_domain("acme.com.au") == "acme.com.au"  # OLD: None

    def test_x_co_uk_now_resolves(self):
        assert _extract_domain("x.co.uk") == "x.co.uk"  # OLD: None
