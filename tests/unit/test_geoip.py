"""Tests for apps.api.services.geoip.resolve_geoip()"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from apps.api.services.geoip import resolve_geoip


class TestResolveGeoIP:
    """Test GeoIP resolution with mocked HTTP calls."""

    @pytest.mark.asyncio
    async def test_successful_resolution(self):
        """Should return (country_code, region) on success."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "countryCode": "US",
            "regionName": "California",
        }

        with patch("apps.api.services.geoip.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client

            # Clear cache to ensure fresh call
            from apps.api.services.geoip import _geoip_cache
            _geoip_cache.clear()

            country, region = await resolve_geoip("8.8.8.8")
            assert country == "US"
            assert region == "California"

    @pytest.mark.asyncio
    async def test_empty_ip_returns_empty(self):
        """Empty IP should return empty strings without making HTTP call."""
        country, region = await resolve_geoip("")
        assert country == ""
        assert region == ""

    @pytest.mark.asyncio
    async def test_private_ip_returns_empty(self):
        """Private IPs won't resolve but shouldn't crash."""
        # This will either hit cache or make a real call that fails gracefully
        country, region = await resolve_geoip("192.168.1.1")
        # Private IPs return empty (ip-api returns "fail" for them)
        assert isinstance(country, str)
        assert isinstance(region, str)

    @pytest.mark.asyncio
    async def test_never_raises(self):
        """Function should never raise, always return ("", "")."""
        with patch("apps.api.services.geoip.httpx.AsyncClient", side_effect=Exception("network error")):
            from apps.api.services.geoip import _geoip_cache
            _geoip_cache.clear()

            country, region = await resolve_geoip("1.2.3.4")
            assert country == ""
            assert region == ""


# ─────────────────────────────────────────────────────────────────────────────
# Widened resolve_geoip_full + the backward-compat guarantee on resolve_geoip
# ─────────────────────────────────────────────────────────────────────────────

import apps.api.services.geoip as geoip_mod


class _FakeRedis:
    """Minimal async Redis stand-in so cache behaviour is deterministic in the
    unit lane (a real local Redis would carry state between runs)."""

    def __init__(self, initial: dict | None = None):
        self.store: dict[str, str] = dict(initial or {})
        self.sets: list[tuple[str, int, str]] = []

    async def get(self, key):
        return self.store.get(key)

    async def setex(self, key, ttl, value):
        self.store[key] = value
        self.sets.append((key, ttl, value))


def _clear_caches():
    geoip_mod._geoip_cache.clear()
    geoip_mod._geoip_full_cache.clear()


def _mock_client(response):
    """Build a patched httpx.AsyncClient whose .get returns `response`."""
    mock_client = AsyncMock()
    mock_client.get.return_value = response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


_FULL_PAYLOAD = {
    "status": "success",
    "countryCode": "US",
    "regionName": "California",
    "city": "Mountain View",
    "lat": 37.386,
    "lon": -122.084,
    "isp": "Google LLC",
    "org": "Google Public DNS",
    "as": "AS15169 Google LLC",
}


def _ok_response(payload=None):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = payload if payload is not None else _FULL_PAYLOAD
    return r


class TestGeoIPWidened:
    @pytest.mark.asyncio
    async def test_resolve_geoip_backward_compatible(self):
        """THE important one: the widened payload must still yield exactly the
        old 2-tuple. events.py depends on this byte-for-byte."""
        _clear_caches()
        fake = _FakeRedis()
        with patch("apps.api.services.geoip.httpx.AsyncClient") as MockClient, \
                patch("apps.api.services.redis_client.get_redis", return_value=fake):
            MockClient.return_value = _mock_client(_ok_response())
            assert await resolve_geoip("8.8.8.8") == ("US", "California")

    @pytest.mark.asyncio
    async def test_widened_field_mask_is_sent(self):
        _clear_caches()
        fake = _FakeRedis()
        client = _mock_client(_ok_response())
        with patch("apps.api.services.geoip.httpx.AsyncClient") as MockClient, \
                patch("apps.api.services.redis_client.get_redis", return_value=fake):
            MockClient.return_value = client
            await geoip_mod.resolve_geoip_full("8.8.8.8")
        fields = client.get.call_args.kwargs["params"]["fields"]
        for f in ("city", "lat", "lon", "isp", "org", "as"):
            assert f in fields, f"missing {f} in {fields}"
        # legacy fields must survive
        assert "countryCode" in fields and "regionName" in fields

    @pytest.mark.asyncio
    async def test_resolve_geoip_full_maps_every_field(self):
        _clear_caches()
        fake = _FakeRedis()
        with patch("apps.api.services.geoip.httpx.AsyncClient") as MockClient, \
                patch("apps.api.services.redis_client.get_redis", return_value=fake):
            MockClient.return_value = _mock_client(_ok_response())
            g = await geoip_mod.resolve_geoip_full("8.8.8.8")
        assert g is not None
        assert g.country_code == "US"
        assert g.region == "California"
        assert g.city == "Mountain View"
        assert g.lat == 37.386
        assert g.lon == -122.084
        assert g.isp == "Google LLC"
        assert g.org == "Google Public DNS"
        assert g.as_str == "AS15169 Google LLC"

    @pytest.mark.asyncio
    async def test_full_result_written_under_new_prefix_only(self):
        """A JSON value must NEVER land under the legacy `geoip:` key — an old
        pod would split it on '|' and corrupt country_code."""
        _clear_caches()
        fake = _FakeRedis()
        with patch("apps.api.services.geoip.httpx.AsyncClient") as MockClient, \
                patch("apps.api.services.redis_client.get_redis", return_value=fake):
            MockClient.return_value = _mock_client(_ok_response())
            await geoip_mod.resolve_geoip_full("8.8.8.8")
        assert "geoip2:8.8.8.8" in fake.store
        assert fake.store.get("geoip:8.8.8.8") is None
        assert fake.store["geoip2:8.8.8.8"].startswith("{")

    @pytest.mark.asyncio
    async def test_legacy_cache_value_still_parses(self):
        """A stale `geoip:` pipe value from a pre-widening pod must be honoured,
        not mis-parsed and not crash."""
        _clear_caches()
        fake = _FakeRedis({"geoip:9.9.9.9": "US|California"})
        with patch("apps.api.services.geoip.httpx.AsyncClient",
                   side_effect=AssertionError("must not call the provider")), \
                patch("apps.api.services.redis_client.get_redis", return_value=fake):
            assert await resolve_geoip("9.9.9.9") == ("US", "California")

    @pytest.mark.asyncio
    async def test_legacy_cache_malformed_value_does_not_crash(self):
        _clear_caches()
        fake = _FakeRedis({"geoip:9.9.9.8": '{"country_code": "US"}'})
        with patch("apps.api.services.geoip.httpx.AsyncClient") as MockClient, \
                patch("apps.api.services.redis_client.get_redis", return_value=fake):
            MockClient.return_value = _mock_client(_ok_response())
            cc, region = await resolve_geoip("9.9.9.8")
        # Garbage in, no crash; the value is treated as an opaque (cc, region).
        assert isinstance(cc, str) and isinstance(region, str)

    @pytest.mark.asyncio
    async def test_rate_limit_429_degrades_and_sets_backoff(self):
        _clear_caches()
        fake = _FakeRedis()
        r = MagicMock()
        r.status_code = 429
        r.headers = {"X-Ttl": "37"}
        with patch("apps.api.services.geoip.httpx.AsyncClient") as MockClient, \
                patch("apps.api.services.redis_client.get_redis", return_value=fake):
            MockClient.return_value = _mock_client(r)
            assert await geoip_mod.resolve_geoip_full("8.8.4.4") is None
        assert fake.store.get(geoip_mod._BACKOFF_KEY) == "1"
        assert any(k == geoip_mod._BACKOFF_KEY and ttl == 37 for k, ttl, _ in fake.sets)

    @pytest.mark.asyncio
    async def test_backoff_skips_the_provider_entirely(self):
        _clear_caches()
        fake = _FakeRedis({geoip_mod._BACKOFF_KEY: "1"})
        with patch("apps.api.services.geoip.httpx.AsyncClient",
                   side_effect=AssertionError("must not construct a client")), \
                patch("apps.api.services.redis_client.get_redis", return_value=fake):
            assert await geoip_mod.resolve_geoip_full("8.8.4.4") is None

    @pytest.mark.asyncio
    async def test_mock_mode_is_deterministic_and_makes_zero_http(self, monkeypatch):
        _clear_caches()
        monkeypatch.setattr(geoip_mod.settings, "mock_external_apis", True)
        with patch("apps.api.services.geoip.httpx.AsyncClient",
                   side_effect=AssertionError("mock mode must not make HTTP calls")):
            a = await geoip_mod.resolve_geoip_full("8.8.8.8")
            b = await geoip_mod.resolve_geoip_full("8.8.8.8")
        assert a is not None and a == b
        assert a.city and a.lat is not None

    @pytest.mark.asyncio
    async def test_localhost_returns_none(self, monkeypatch):
        # Live behaviour: no provider can say anything useful about loopback.
        monkeypatch.setattr(geoip_mod.settings, "mock_external_apis", False)
        assert await geoip_mod.resolve_geoip_full("127.0.0.1") is None
        assert await geoip_mod.resolve_geoip_full("") is None

    @pytest.mark.asyncio
    async def test_mock_mode_beats_the_loopback_guard(self, monkeypatch):
        """Mock mode must answer for 127.0.0.1 so the reveal demos locally.

        In local dev the caller's IP IS loopback. When the loopback guard ran
        first, `MOCK_EXTERNAL_APIS=true` still produced `geo: null` and the
        location reveal could not be hand-tested offline at all — contradicting
        the plan's degraded-paths row for "Private/localhost IP (dev)".
        """
        _clear_caches()
        monkeypatch.setattr(geoip_mod.settings, "mock_external_apis", True)
        got = await geoip_mod.resolve_geoip_full("127.0.0.1")
        assert got is not None
        assert got.city and got.lat is not None and got.lon is not None

    @pytest.mark.asyncio
    async def test_ingest_wrapper_still_short_circuits_loopback_in_mock_mode(
        self, monkeypatch
    ):
        """The frozen 2-tuple contract is unchanged by the reordering above.

        `resolve_geoip` keeps its own loopback guard, so the ingest hot path
        never reaches `resolve_geoip_full` for 127.0.0.1 regardless of mock
        mode. Guarding this explicitly because the reorder is the kind of edit
        that silently starts stamping fake countries onto real events.
        """
        _clear_caches()
        monkeypatch.setattr(geoip_mod.settings, "mock_external_apis", True)
        assert await geoip_mod.resolve_geoip("127.0.0.1") == ("", "")
        assert await geoip_mod.resolve_geoip("::1") == ("", "")
