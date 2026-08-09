"""Unit gates for the APNIC eyeball-ASN refresh + loader (WS-E).

Every test that varies the underlying file clears the loader cache first (E6a):
``load_eyeball_asns`` is ``@lru_cache(maxsize=1)``, so without ``cache_clear()`` a
fail-open / threshold test would assert against a previous test's cached data and
pass vacuously.
"""

import json

import httpx
import pytest

from apps.api.config import settings as app_settings
from apps.api.services import apnic_eyeball_refresh
from apps.api.services.apnic_eyeball_refresh import (
    load_eyeball_asns,
    parse_aspop,
    refresh_apnic_eyeball_asns,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_cache():
    load_eyeball_asns.cache_clear()
    yield
    load_eyeball_asns.cache_clear()


class TestParseAspop:
    def test_the_observed_keyed_object_shape(self):
        # G18-observed shape: top-level object with a "Data" list, records carry
        # "AS" and "Users".
        payload = {
            "copyright": "x",
            "Data": [
                {"rank": 1, "AS": 55836, "Users": 302941130, "CC": "IN"},
                {"rank": 2, "AS": 4134, "Users": 211407031, "CC": "CN"},
            ],
        }
        assert parse_aspop(payload) == {55836: 302941130, 4134: 211407031}

    def test_a_bare_list_shape(self):
        payload = [{"AS": 1, "Users": 100}, {"AS": 2, "Users": 200}]
        assert parse_aspop(payload) == {1: 100, 2: 200}

    def test_junk_records_are_skipped_not_fatal(self):
        payload = {
            "Data": [
                {"AS": 10, "Users": 5},
                "not a dict",
                {"AS": "not-an-int", "Users": 5},
                {"AS": 11},  # missing Users
                {"Users": 5},  # missing AS
                {"AS": -1, "Users": 5},  # non-positive ASN
                {"AS": 12, "Users": 7},
            ]
        }
        assert parse_aspop(payload) == {10: 5, 12: 7}

    def test_an_unknown_top_level_shape_yields_empty(self):
        assert parse_aspop("garbage") == {}
        assert parse_aspop({"no_data_key": 1}) == {}


class TestLoadEyeballAsns:
    def _write_runtime(self, monkeypatch, tmp_path, asns: dict[str, int]):
        rt = tmp_path / "eyeball_asns.json"
        rt.write_text(json.dumps({"asns": asns}), encoding="utf-8")
        monkeypatch.setattr(apnic_eyeball_refresh, "_RUNTIME_FILE", rt)
        return rt

    def test_threshold_boundary_49999_out_50001_in(self, monkeypatch, tmp_path):
        # Default threshold is 50_000.
        assert app_settings.ip_org_eyeball_min_users == 50_000
        self._write_runtime(
            monkeypatch, tmp_path, {"64512": 49_999, "64513": 50_001, "64514": 50_000}
        )
        load_eyeball_asns.cache_clear()
        result = load_eyeball_asns()
        assert 64513 in result  # 50001 >= 50000
        assert 64514 in result  # 50000 >= 50000 (boundary is inclusive)
        assert 64512 not in result  # 49999 < 50000

    def test_missing_runtime_falls_back_and_missing_both_is_empty(
        self, monkeypatch, tmp_path
    ):
        missing_rt = tmp_path / "nope_runtime.json"
        missing_vendored = tmp_path / "nope_vendored.json"
        monkeypatch.setattr(apnic_eyeball_refresh, "_RUNTIME_FILE", missing_rt)
        monkeypatch.setattr(apnic_eyeball_refresh, "_VENDORED_FILE", missing_vendored)
        load_eyeball_asns.cache_clear()
        assert load_eyeball_asns() == frozenset()  # fail-open, no crash

    def test_corrupt_file_is_fail_open(self, monkeypatch, tmp_path):
        rt = tmp_path / "eyeball_asns.json"
        rt.write_text("{ this is not json", encoding="utf-8")
        monkeypatch.setattr(apnic_eyeball_refresh, "_RUNTIME_FILE", rt)
        load_eyeball_asns.cache_clear()
        assert load_eyeball_asns() == frozenset()


class TestRefreshFailOpenAndMock:
    async def test_mock_mode_makes_no_network_call(self, monkeypatch):
        monkeypatch.setattr(app_settings, "mock_external_apis", True)

        def _boom(*a, **kw):
            raise AssertionError("network call made in mock mode")

        monkeypatch.setattr(apnic_eyeball_refresh.httpx, "AsyncClient", _boom)
        result = await refresh_apnic_eyeball_asns()
        assert result == {"asns": 0}

    async def test_a_fetch_failure_is_fail_open(self, monkeypatch):
        monkeypatch.setattr(app_settings, "mock_external_apis", False)

        class _Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def stream(self, *a, **k):
                raise httpx.ConnectError("down")

        monkeypatch.setattr(apnic_eyeball_refresh.httpx, "AsyncClient", _Client)
        result = await refresh_apnic_eyeball_asns()
        assert result == {"asns": 0}
