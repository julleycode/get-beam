"""MaxMind GeoLite2-ASN datacenter detection.

is_datacenter_ip prefers a local, free, offline ASN lookup and only falls back to
the IPinfo API when the DB is absent. Classification reuses classify_org_kind, so
the same ASN set + org tokens drive both paths. The real .mmdb needs a free MaxMind
license, so these mock the reader and assert the wiring + fail-open behavior.
"""
import httpx
import pytest

from apps.api.config import settings as app_settings
from apps.api.services import asn_lookup
from apps.api.services.company_resolver import is_datacenter_ip


@pytest.fixture
def _no_redis(monkeypatch):
    def _raise():
        raise RuntimeError("no redis in test")
    monkeypatch.setattr("apps.api.services.redis_client.get_redis", _raise)


@pytest.fixture
def _no_http(monkeypatch):
    """Make any IPinfo fallback call blow up — so tests prove MaxMind short-circuits."""
    class _Boom:
        def __init__(self, *a, **k):
            raise AssertionError("IPinfo must NOT be called when MaxMind answered")
    monkeypatch.setattr(httpx, "AsyncClient", _Boom)


class TestLookupAsn:
    def test_returns_none_without_db_path(self, monkeypatch):
        monkeypatch.setattr(app_settings, "maxmind_asn_db_path", "")
        asn_lookup.reset_reader_cache()
        assert asn_lookup.lookup_asn("8.8.8.8") == (None, None)

    def test_returns_none_for_bad_db_path(self, monkeypatch):
        monkeypatch.setattr(app_settings, "maxmind_asn_db_path", "/no/such/GeoLite2-ASN.mmdb")
        asn_lookup.reset_reader_cache()
        # Missing/corrupt DB must fail open, not raise.
        assert asn_lookup.lookup_asn("8.8.8.8") == (None, None)


class TestIsDatacenterViaMaxmind:
    @pytest.mark.asyncio
    async def test_datacenter_asn_true_no_ipinfo(self, monkeypatch, _no_redis, _no_http):
        # MaxMind answers → IPinfo (patched to blow up) is never reached, and no
        # token is needed.
        monkeypatch.setattr(app_settings, "ipinfo_token", "")
        monkeypatch.setattr("apps.api.services.asn_lookup.lookup_asn", lambda ip: (16509, "AMAZON-02"))
        assert await is_datacenter_ip("52.1.2.3") is True

    @pytest.mark.asyncio
    async def test_cdn_asn_not_dropped(self, monkeypatch, _no_redis, _no_http):
        monkeypatch.setattr(app_settings, "ipinfo_token", "")
        monkeypatch.setattr("apps.api.services.asn_lookup.lookup_asn", lambda ip: (13335, "CLOUDFLARENET"))
        assert await is_datacenter_ip("1.1.1.1") is False  # cdn — real humans behind WARP

    @pytest.mark.asyncio
    async def test_residential_isp_not_datacenter(self, monkeypatch, _no_redis, _no_http):
        monkeypatch.setattr(app_settings, "ipinfo_token", "")
        monkeypatch.setattr("apps.api.services.asn_lookup.lookup_asn", lambda ip: (7922, "COMCAST-7922"))
        assert await is_datacenter_ip("73.11.22.33") is False


class TestFallsBackToIpinfo:
    @pytest.mark.asyncio
    async def test_uses_ipinfo_when_maxmind_absent(self, monkeypatch, _no_redis):
        # MaxMind returns nothing → the IPinfo path runs and classifies.
        monkeypatch.setattr("apps.api.services.asn_lookup.lookup_asn", lambda ip: (None, None))
        monkeypatch.setattr(app_settings, "ipinfo_token", "tok")

        class _Resp:
            status_code = 200
            def json(self):
                return {"org": "AS14061 DigitalOcean, LLC"}

        class _Client:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, *a, **k): return _Resp()

        monkeypatch.setattr(httpx, "AsyncClient", _Client)
        assert await is_datacenter_ip("165.232.1.2") is True

    @pytest.mark.asyncio
    async def test_fail_open_no_db_no_token(self, monkeypatch, _no_redis):
        monkeypatch.setattr("apps.api.services.asn_lookup.lookup_asn", lambda ip: (None, None))
        monkeypatch.setattr(app_settings, "ipinfo_token", "")
        assert await is_datacenter_ip("8.8.8.8") is False
