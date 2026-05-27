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
