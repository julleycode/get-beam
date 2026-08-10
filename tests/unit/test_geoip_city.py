"""Local MaxMind GeoLite2-City reader + its rung in the geoip ladder.

The guards that matter, in priority order:
  1. FAIL-OPEN. No DB configured, a corrupt file, or a missing geoip2 import must
     all degrade to ip-api — never raise into a visitor's request.
  2. The frozen ``resolve_geoip`` 2-tuple contract is unchanged (routers/events.py
     needs zero edits).
  3. The City rung, when it hits, PREEMPTS ip-api and makes zero HTTP calls.
  4. ``accuracy_radius`` maps all the way through to the reveal payload.
"""

import pytest

from apps.api.services import geoip_city
from apps.api.services.geoip_city import CityResult, lookup_city, reset_reader_cache


# ─── Fakes standing in for a geoip2.database.Reader ───


class _Loc:
    def __init__(self, lat, lon, radius):
        self.latitude = lat
        self.longitude = lon
        self.accuracy_radius = radius


class _Named:
    def __init__(self, name):
        self.name = name


class _Subdivisions:
    def __init__(self, name):
        self.most_specific = _Named(name)


class _Country:
    def __init__(self, iso):
        self.iso_code = iso


class _Record:
    def __init__(self, iso="US", region="California", city="Mountain View",
                 lat=37.386, lon=-122.084, radius=5):
        self.country = _Country(iso)
        self.subdivisions = _Subdivisions(region)
        self.city = _Named(city)
        self.location = _Loc(lat, lon, radius)


class _FakeReader:
    """`hit=False` raises the way geoip2 does for an IP absent from the DB."""

    def __init__(self, record=None, hit=True):
        self._record = record or _Record()
        self._hit = hit
        self.calls = 0

    def city(self, ip):
        self.calls += 1
        if not self._hit:
            raise LookupError(f"{ip} not in database")
        return self._record


@pytest.fixture
def _clean_reader():
    reset_reader_cache()
    yield
    reset_reader_cache()


def _install(reader):
    """Pin a fake reader without touching the filesystem."""
    geoip_city._reader = reader
    geoip_city._load_attempted = True


class TestLookupCity:
    def test_hit_maps_every_field(self, _clean_reader):
        _install(_FakeReader())
        r = lookup_city("8.8.8.8")
        assert isinstance(r, CityResult)
        assert r.country_code == "US"
        assert r.region == "California"
        assert r.city == "Mountain View"
        assert r.lat == pytest.approx(37.386)
        assert r.lon == pytest.approx(-122.084)
        assert r.accuracy_km == 5

    def test_miss_returns_none(self, _clean_reader):
        _install(_FakeReader(hit=False))
        assert lookup_city("10.0.0.1") is None

    def test_absent_db_fails_open(self, _clean_reader, monkeypatch):
        """Empty maxmind_city_db_path (the default) => None, no exception."""
        from apps.api.config import settings

        monkeypatch.setattr(settings, "maxmind_city_db_path", "")
        assert lookup_city("8.8.8.8") is None
        assert geoip_city._reader is None

    def test_missing_file_fails_open(self, _clean_reader, monkeypatch):
        from apps.api.config import settings

        monkeypatch.setattr(settings, "maxmind_city_db_path", "/nope/does-not-exist.mmdb")
        assert lookup_city("8.8.8.8") is None

    def test_corrupt_db_fails_open(self, _clean_reader, monkeypatch, tmp_path):
        """A real file that is not a valid .mmdb must not raise."""
        from apps.api.config import settings

        junk = tmp_path / "GeoLite2-City.mmdb"
        junk.write_bytes(b"this is not an mmdb" * 32)
        monkeypatch.setattr(settings, "maxmind_city_db_path", str(junk))
        assert lookup_city("8.8.8.8") is None

    def test_load_is_attempted_once(self, _clean_reader, monkeypatch):
        """A missing DB must cost one failed open per process, not one per IP."""
        from apps.api.config import settings

        calls = {"n": 0}

        def _count(*_a, **_kw):
            calls["n"] += 1
            raise OSError("boom")

        monkeypatch.setattr(settings, "maxmind_city_db_path", "/x.mmdb")
        monkeypatch.setattr("geoip2.database.Reader", _count)
        for _ in range(5):
            assert lookup_city("8.8.8.8") is None
        assert calls["n"] == 1

    def test_record_without_coordinates_is_a_miss(self, _clean_reader):
        _install(_FakeReader(_Record(lat=None, lon=None, radius=None)))
        assert lookup_city("8.8.8.8") is None

    def test_null_names_and_radius_tolerated(self, _clean_reader):
        _install(_FakeReader(_Record(iso=None, region=None, city=None, radius=None)))
        r = lookup_city("8.8.8.8")
        assert r is not None
        assert (r.country_code, r.region, r.city) == ("", "", "")
        assert r.accuracy_km is None

    def test_empty_ip_short_circuits(self, _clean_reader):
        reader = _FakeReader()
        _install(reader)
        assert lookup_city("") is None
        assert reader.calls == 0

    def test_reset_reader_cache_reopens(self, _clean_reader, monkeypatch):
        _install(_FakeReader())
        assert lookup_city("8.8.8.8") is not None
        reset_reader_cache()
        from apps.api.config import settings

        monkeypatch.setattr(settings, "maxmind_city_db_path", "")
        assert lookup_city("8.8.8.8") is None


class TestGeoipLadder:
    """resolve_geoip_full prefers the City rung, then falls through to ip-api."""

    @pytest.fixture(autouse=True)
    def _clear(self, monkeypatch):
        import apps.api.services.geoip as geoip_mod
        from apps.api.config import settings

        monkeypatch.setattr(settings, "mock_external_apis", False)
        geoip_mod._geoip_cache.clear()
        geoip_mod._geoip_full_cache.clear()
        # Make every cache layer inert so the test exercises the provider ladder
        # itself. `get_redis` is neutralized too, not just the helpers: the L2
        # READ is an inline get_redis() call, and a stray local Redis holding a
        # blob from an earlier run otherwise answers before the ladder runs
        # (this is the documented unit-lane Redis-shadowing hazard, and it did
        # fire here on first run).
        monkeypatch.setattr(
            "apps.api.services.redis_client.get_redis",
            _explode_fn("no Redis in the unit lane"),
        )
        monkeypatch.setattr(geoip_mod, "_redis_set_full", _noop_async)
        monkeypatch.setattr(geoip_mod, "_legacy_redis_set", _noop_async)
        monkeypatch.setattr(geoip_mod, "_legacy_redis_get", _none_async)
        monkeypatch.setattr(geoip_mod, "_in_backoff", _false_async)
        yield
        geoip_mod._geoip_cache.clear()
        geoip_mod._geoip_full_cache.clear()

    @pytest.mark.asyncio
    async def test_city_hit_preempts_ip_api(self, monkeypatch):
        import apps.api.services.geoip as geoip_mod

        monkeypatch.setattr(
            "apps.api.services.geoip_city.lookup_city",
            lambda _ip: CityResult("VN", "Hanoi", "Hanoi", 21.03, 105.85, 7),
        )
        monkeypatch.setattr(
            geoip_mod.httpx, "AsyncClient", _explode("ip-api must not be called")
        )

        r = await geoip_mod.resolve_geoip_full("203.0.113.9")
        assert r is not None
        assert (r.country_code, r.region, r.city) == ("VN", "Hanoi", "Hanoi")
        assert r.accuracy_km == 7
        # The City DB carries no network fields — that is the ASN DB's job.
        assert (r.isp, r.org, r.as_str) == ("", "", "")

    @pytest.mark.asyncio
    async def test_city_miss_falls_through_to_ip_api(self, monkeypatch):
        import apps.api.services.geoip as geoip_mod

        monkeypatch.setattr(
            "apps.api.services.geoip_city.lookup_city", lambda _ip: None
        )
        monkeypatch.setattr(
            geoip_mod.httpx, "AsyncClient", _fake_ip_api()
        )

        r = await geoip_mod.resolve_geoip_full("203.0.113.10")
        assert r is not None
        assert r.city == "Sydney"
        assert r.isp == "Telstra"
        # ip-api reports no radius; the caller supplies its own honest default.
        assert r.accuracy_km is None

    @pytest.mark.asyncio
    async def test_city_import_failure_falls_through(self, monkeypatch):
        """Even a broken geoip2 import degrades to ip-api rather than raising."""
        import apps.api.services.geoip as geoip_mod

        def _boom(_ip):
            raise RuntimeError("geoip2 missing")

        monkeypatch.setattr("apps.api.services.geoip_city.lookup_city", _boom)
        monkeypatch.setattr(geoip_mod.httpx, "AsyncClient", _fake_ip_api())

        r = await geoip_mod.resolve_geoip_full("203.0.113.11")
        assert r is not None and r.city == "Sydney"

    @pytest.mark.asyncio
    async def test_frozen_two_tuple_contract_unchanged_on_city_path(self, monkeypatch):
        """routers/events.py must need zero edits: still exactly (cc, region)."""
        import apps.api.services.geoip as geoip_mod

        monkeypatch.setattr(
            "apps.api.services.geoip_city.lookup_city",
            lambda _ip: CityResult("VN", "Hanoi", "Hanoi", 21.03, 105.85, 7),
        )
        monkeypatch.setattr(
            geoip_mod.httpx, "AsyncClient", _explode("ip-api must not be called")
        )

        result = await geoip_mod.resolve_geoip("203.0.113.12")
        assert isinstance(result, tuple) and len(result) == 2
        assert result == ("VN", "Hanoi")
        assert all(isinstance(x, str) for x in result)

    @pytest.mark.asyncio
    async def test_loopback_still_short_circuits_before_city(self, monkeypatch):
        import apps.api.services.geoip as geoip_mod

        monkeypatch.setattr(
            "apps.api.services.geoip_city.lookup_city",
            _explode_fn("City DB must not be consulted for loopback"),
        )
        assert await geoip_mod.resolve_geoip("127.0.0.1") == ("", "")

    @pytest.mark.asyncio
    async def test_mock_mode_makes_zero_http_and_zero_db_reads(self, monkeypatch):
        import apps.api.services.geoip as geoip_mod
        from apps.api.config import settings

        monkeypatch.setattr(settings, "mock_external_apis", True)
        monkeypatch.setattr(
            "apps.api.services.geoip_city.lookup_city",
            _explode_fn("City DB must not be read in mock mode"),
        )
        monkeypatch.setattr(
            geoip_mod.httpx, "AsyncClient", _explode("no HTTP in mock mode")
        )

        r = await geoip_mod.resolve_geoip_full("8.8.8.8")
        assert r is not None and r.city == "Mountain View"

    @pytest.mark.asyncio
    async def test_accuracy_km_survives_the_redis_json_round_trip(self):
        from apps.api.services.geoip import GeoResult

        original = GeoResult(country_code="VN", lat=1.0, lon=2.0, accuracy_km=7)
        assert GeoResult.from_dict(original.to_dict()).accuracy_km == 7

    @pytest.mark.asyncio
    async def test_legacy_cached_json_without_accuracy_still_parses(self):
        """A blob written by a pod that predates the City rung must not crash."""
        from apps.api.services.geoip import GeoResult

        legacy = {"country_code": "US", "region": "CA", "city": "SF",
                  "lat": 1.0, "lon": 2.0, "isp": "x", "org": "y", "as_str": "z"}
        assert GeoResult.from_dict(legacy).accuracy_km is None


class TestAccuracyReachesThePayload:
    def test_measured_radius_is_used(self):
        from apps.api.services.geoip import GeoResult
        from apps.api.services.onboarding_canary import build_geo

        out = build_geo(GeoResult(lat=21.0, lon=105.0, accuracy_km=7))
        assert out["accuracy_km"] == 7

    def test_missing_radius_falls_back_to_the_honest_default(self):
        from apps.api.services.geoip import GeoResult
        from apps.api.services.onboarding_canary import build_geo

        out = build_geo(GeoResult(lat=21.0, lon=105.0))
        assert out["accuracy_km"] == 25

    def test_zero_radius_is_clamped(self):
        """A 0km circle would render as an invisible dot claiming pinpoint truth."""
        from apps.api.services.geoip import GeoResult
        from apps.api.services.onboarding_canary import build_geo

        assert build_geo(GeoResult(lat=21.0, lon=105.0, accuracy_km=0))["accuracy_km"] == 1

    def test_garbage_radius_falls_back(self):
        from apps.api.services.geoip import GeoResult
        from apps.api.services.onboarding_canary import build_geo

        out = build_geo(GeoResult(lat=21.0, lon=105.0, accuracy_km="wat"))
        assert out["accuracy_km"] == 25


# ─── helpers ───


async def _noop_async(*_a, **_kw):
    return None


async def _none_async(*_a, **_kw):
    return None


async def _false_async(*_a, **_kw):
    return False


def _explode_fn(msg):
    def _f(*_a, **_kw):
        raise AssertionError(msg)

    return _f


def _explode(msg):
    class _Boom:
        def __init__(self, *a, **kw):
            raise AssertionError(msg)

    return _Boom


def _fake_ip_api():
    """Minimal async httpx.AsyncClient stand-in returning one ip-api success."""

    class _Resp:
        status_code = 200
        headers: dict = {}

        @staticmethod
        def json():
            return {
                "status": "success",
                "countryCode": "AU",
                "regionName": "New South Wales",
                "city": "Sydney",
                "lat": -33.87,
                "lon": 151.21,
                "isp": "Telstra",
                "org": "Telstra",
                "as": "AS1221 Telstra",
            }

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            return _Resp()

    return _Client
