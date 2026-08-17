"""Integration tests for POST /api/v1/onboarding/canary + /identity-feedback.

Guards, in priority order:
  1. Flag OFF => 404 on both routes, and no provider call.
  2. The response body NEVER carries ip / site_id / visitor_id / fingerprint.
  3. The journey is scoped to Beam's own site — a fingerprint colliding with a
     visitor on ANOTHER site returns no pages.
  4. A provider failure degrades to 200 + geo:null, never a 500.
"""

import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from apps.api.dependencies import get_current_user
from apps.api.main import app
from apps.api.models.event import Event
from apps.api.models.identity_feedback import IdentityFeedback
from apps.api.models.user import User
from apps.api.models.visitor import Visitor
from apps.api.services.geoip import GeoResult

pytestmark = pytest.mark.integration

BEAM_SITE = "site_90a488f43eac"
OTHER_SITE = "site_someone_else"
FP = "fp2_canarytestfingerprint"

_GEO = GeoResult(
    country_code="VN", region="Hanoi", city="Hanoi",
    lat=21.03, lon=105.85, isp="Viettel Group", org="Viettel Group",
    as_str="AS7552 Viettel Group",
)


async def _seed_visit(session_factory, site_id: str, visitor_id: str):
    now = datetime.utcnow()
    async with session_factory() as s:
        s.add(
            Visitor(
                site_id=site_id,
                visitor_id=visitor_id,
                fingerprint=FP,
                first_seen=now - timedelta(minutes=5),
                last_seen=now,
            )
        )
        s.add(
            Event(
                site_id=site_id,
                visitor_id=visitor_id,
                event_type="pageview",
                page_path="/pricing",
                page_title="Pricing",
                url="https://getbeam.fyi/pricing",
                time_on_page=42,
                created_at=now - timedelta(minutes=1),
            )
        )
        await s.commit()


@pytest_asyncio.fixture
async def user_id():
    return uuid.uuid4()


@pytest_asyncio.fixture
async def authed(test_client, user_id):
    app.dependency_overrides[get_current_user] = lambda: User(
        id=user_id, email="canary@getbeam.fyi"
    )
    yield test_client
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def flag_on(monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "location_reveal_enabled", True)
    monkeypatch.setattr(settings, "beam_self_site_id", BEAM_SITE)


@pytest.fixture
def geo_ok(monkeypatch):
    async def _fake(_ip):
        return _GEO

    monkeypatch.setattr("apps.api.routers.onboarding.resolve_geoip_full", _fake)
    # The ASN rung is dead in this repo's default env; pin it so the label is
    # deterministic regardless of whether a local mmdb happens to exist.
    monkeypatch.setattr(
        "apps.api.services.asn_lookup.lookup_asn", lambda _ip: (None, None)
    )


@pytest.mark.asyncio
async def test_flag_off_returns_404_and_calls_no_provider(authed, monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "location_reveal_enabled", False)

    async def _boom(_ip):
        raise AssertionError("provider must not be called when the flag is off")

    monkeypatch.setattr("apps.api.routers.onboarding.resolve_geoip_full", _boom)

    r = await authed.post("/api/v1/onboarding/canary", json={"fingerprint": FP})
    assert r.status_code == 404

    r2 = await authed.post("/api/v1/onboarding/identity-feedback",
                           json={"reasons": ["wrong_city"]})
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated_is_rejected(test_client, flag_on):
    r = await test_client.post("/api/v1/onboarding/canary", json={"fingerprint": FP})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_authed_returns_full_shape(authed, flag_on, geo_ok, test_engine):
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    await _seed_visit(factory, BEAM_SITE, "v-beam")

    r = await authed.post("/api/v1/onboarding/canary", json={"fingerprint": FP})
    assert r.status_code == 200
    body = r.json()

    assert body["landed"] is True
    assert body["pages"][0]["path"] == "/pricing"
    assert body["pages"][0]["seconds"] == 42
    assert body["geo"]["city"] == "Hanoi"
    assert body["geo"]["country_code"] == "VN"
    assert body["geo"]["lat"] == 21.03 and body["geo"]["lng"] == 105.85
    assert body["network"]["label"] == "Viettel Group"
    assert body["network"]["kind"] in ("isp", "company")


@pytest.mark.asyncio
async def test_response_never_leaks_identifiers(authed, flag_on, geo_ok, test_engine):
    """Anti-regression: a future "while we're here, also return X" trips here."""
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    await _seed_visit(factory, BEAM_SITE, "v-beam")

    r = await authed.post("/api/v1/onboarding/canary", json={"fingerprint": FP})
    assert r.status_code == 200
    body = r.json()

    for forbidden in ("ip", "site_id", "visitor_id", "fingerprint"):
        assert forbidden not in body, f"{forbidden} must never be in the response"
    for page in body["pages"]:
        for forbidden in ("ip", "site_id", "visitor_id", "fingerprint"):
            assert forbidden not in page
    # And nowhere in the serialized body either.
    raw = r.text
    assert BEAM_SITE not in raw
    assert FP not in raw


@pytest.mark.asyncio
async def test_journey_is_scoped_to_beam_site(authed, flag_on, geo_ok, test_engine):
    """A fingerprint collision on ANOTHER tenant's site must return no pages —
    this is the predicate /demo/journey lacks."""
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    await _seed_visit(factory, OTHER_SITE, "v-other")

    r = await authed.post("/api/v1/onboarding/canary", json={"fingerprint": FP})
    assert r.status_code == 200
    body = r.json()
    assert body["pages"] == []
    assert body["landed"] is False
    # Geo still works — it reads the caller's IP, not the matched visitor row.
    assert body["geo"] is not None


@pytest.mark.asyncio
async def test_provider_failure_degrades_not_500(authed, flag_on, monkeypatch):
    async def _fail(_ip):
        raise RuntimeError("provider down")

    monkeypatch.setattr("apps.api.routers.onboarding.resolve_geoip_full", _fail)

    r = await authed.post("/api/v1/onboarding/canary", json={"fingerprint": FP})
    assert r.status_code == 200
    body = r.json()
    assert body["geo"] is None
    assert body["network"] is None
    assert body.get("reason") == "provider_unavailable"


@pytest.mark.asyncio
async def test_no_fingerprint_still_returns_geo(authed, flag_on, geo_ok):
    r = await authed.post("/api/v1/onboarding/canary", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["landed"] is False
    assert body["geo"] is not None


@pytest.mark.asyncio
async def test_identity_feedback_persists_and_filters_reasons(
    authed, flag_on, test_engine, user_id
):
    r = await authed.post(
        "/api/v1/onboarding/identity-feedback",
        json={
            "reasons": ["wrong_city", "bogus_reason", "vpn_or_proxy"],
            "note": "x" * 900,
            "shown": {"city": "Hanoi", "kind": "isp"},
        },
    )
    assert r.status_code == 204

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        rows = (await s.execute(select(IdentityFeedback))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == user_id
    assert sorted(row.reasons) == ["vpn_or_proxy", "wrong_city"]
    assert len(row.note) == 500
    assert row.surface == "onboarding_canary"
    assert row.shown["city"] == "Hanoi"


@pytest.mark.asyncio
async def test_geo_cache_reuse_makes_one_provider_call(
    authed, flag_on, monkeypatch, test_engine
):
    """Two calls must hit the provider once — the claim that ingest warms the
    cache seconds before the reveal rests on this."""
    import apps.api.services.geoip as geoip_mod

    # This test is specifically about the LIVE provider + cache path, so mock
    # mode has to be off. `resolve_geoip_full` short-circuits to a deterministic
    # fake before anything else when `mock_external_apis` is on (deliberately —
    # it is what lets the reveal be demoed on loopback in local dev), which
    # would make the provider-call count trivially zero and the assertion
    # vacuous rather than failing loudly.
    monkeypatch.setattr(geoip_mod.settings, "mock_external_apis", False)

    geoip_mod._geoip_cache.clear()
    geoip_mod._geoip_full_cache.clear()

    # …and the L2 (Redis) cache, which the in-process dicts above do not cover.
    # Without this the test SELF-POISONS: the first run writes
    # geoip2:203.0.113.9, and every run after it sees zero provider calls and
    # fails — or, worse, would pass vacuously if the assertion were `<= 1`.
    from apps.api.services.redis_client import get_redis

    for key in ("geoip2:203.0.113.9", "geoip:203.0.113.9", "geoip:backoff"):
        try:
            await get_redis().delete(key)
        except Exception:  # noqa: BLE001 — Redis is a cache; the test works without it
            pass

    calls = {"n": 0}

    class _Resp:
        status_code = 200
        headers: dict = {}

        @staticmethod
        def json():
            return {
                "status": "success", "countryCode": "VN", "regionName": "Hanoi",
                "city": "Hanoi", "lat": 21.03, "lon": 105.85,
                "isp": "Viettel Group", "org": "Viettel Group",
                "as": "AS7552 Viettel Group",
            }

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, *a, **kw):
            calls["n"] += 1
            return _Resp()

    monkeypatch.setattr(geoip_mod.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(
        "apps.api.services.asn_lookup.lookup_asn", lambda _ip: (None, None)
    )
    # Force a routable IP so the localhost short-circuit doesn't fire.
    monkeypatch.setattr(
        "apps.api.routers.onboarding.resolve_client_ip", lambda _r: "203.0.113.9"
    )

    r1 = await authed.post("/api/v1/onboarding/canary", json={})
    r2 = await authed.post("/api/v1/onboarding/canary", json={})
    assert r1.status_code == 200 and r2.status_code == 200
    assert calls["n"] == 1, f"expected 1 provider call, got {calls['n']}"


@pytest_asyncio.fixture
async def admin(test_client, user_id):
    """Same override style as `authed`, but with the admin bit set."""
    app.dependency_overrides[get_current_user] = lambda: User(
        id=user_id, email="ops@getbeam.fyi", is_admin=True
    )
    yield test_client
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_feedback_stats_requires_admin(authed, test_engine):
    """A plain authed (non-admin) user is refused — require_admin, not just auth."""
    r = await authed.get("/api/v1/onboarding/identity-feedback/stats")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_feedback_stats_unauthenticated_is_rejected(test_client):
    r = await test_client.get("/api/v1/onboarding/identity-feedback/stats")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_feedback_stats_empty_table_zero_fills(admin, test_engine):
    """No rows must read as explicit zeros for every known reason, not {}."""
    r = await admin.get("/api/v1/onboarding/identity-feedback/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["with_note"] == 0
    assert body["by_surface"] == []
    assert {x["reason"] for x in body["by_reason"]} == {
        "not_me", "vpn_or_proxy", "wrong_city", "wrong_network",
    }
    assert all(x["count"] == 0 for x in body["by_reason"])
    # Present even with the flag off, so an operator can read history.
    assert body["enabled"] is False


@pytest.mark.asyncio
async def test_feedback_stats_aggregates_and_leaks_no_pii(
    admin, flag_on, test_engine, user_id
):
    """Counts per reason across rows; the `shown` blob and note text never appear."""
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        s.add_all(
            [
                IdentityFeedback(
                    user_id=user_id, surface="onboarding_canary",
                    shown={"city": "Hanoi", "lat": 21.0, "lng": 105.8},
                    reasons=["wrong_city", "vpn_or_proxy"],
                    note="my secret note",
                ),
                IdentityFeedback(
                    user_id=user_id, surface="onboarding_canary",
                    shown={"city": "Da Nang"}, reasons=["wrong_city"], note=None,
                ),
                IdentityFeedback(
                    user_id=uuid.uuid4(), surface="onboarding_canary",
                    shown={}, reasons=[], note=None,
                ),
            ]
        )
        await s.commit()

    r = await admin.get("/api/v1/onboarding/identity-feedback/stats?days=30")
    assert r.status_code == 200
    body = r.json()

    counts = {x["reason"]: x["count"] for x in body["by_reason"]}
    assert counts["wrong_city"] == 2
    assert counts["vpn_or_proxy"] == 1
    assert counts["wrong_network"] == 0
    assert counts["not_me"] == 0
    assert body["total"] == 3
    assert body["with_note"] == 1
    assert body["by_surface"] == [{"surface": "onboarding_canary", "count": 3}]
    assert body["enabled"] is True

    # No PII of any kind: no place names, no coordinates, no note text, no ids.
    blob = r.text
    for leaked in ("Hanoi", "Da Nang", "my secret note", str(user_id), "shown", "lat"):
        assert leaked not in blob, f"{leaked!r} leaked into the stats body"


@pytest.mark.asyncio
async def test_feedback_stats_window_excludes_old_rows(admin, test_engine, user_id):
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        s.add(
            IdentityFeedback(
                user_id=user_id, surface="onboarding_canary", shown={},
                reasons=["not_me"],
                created_at=datetime.utcnow() - timedelta(days=10),
            )
        )
        await s.commit()

    recent = (await admin.get("/api/v1/onboarding/identity-feedback/stats?days=30")).json()
    old = (await admin.get("/api/v1/onboarding/identity-feedback/stats?days=1")).json()
    assert recent["total"] == 1
    assert old["total"] == 0


@pytest.mark.asyncio
async def test_city_db_rung_is_dormant_by_default(authed, flag_on, monkeypatch):
    """Unconfigured MaxMind path => the City reader is never even opened."""
    from apps.api.config import settings
    from apps.api.services import geoip_city

    assert settings.maxmind_city_db_path == ""
    geoip_city.reset_reader_cache()
    monkeypatch.setattr(
        "geoip2.database.Reader",
        lambda *a, **kw: pytest.fail("City DB opened while unconfigured"),
    )
    monkeypatch.setattr(
        "apps.api.routers.onboarding.resolve_geoip_full", lambda _ip: _async_geo()
    )
    r = await authed.post("/api/v1/onboarding/canary", json={})
    assert r.status_code == 200


async def _async_geo():
    return _GEO


@pytest.mark.asyncio
async def test_city_accuracy_radius_reaches_the_response(
    authed, flag_on, monkeypatch, test_engine
):
    """A measured radius from the City DB replaces the fixed 25km estimate."""
    import apps.api.services.geoip as geoip_mod
    from apps.api.services.geoip_city import CityResult

    monkeypatch.setattr(geoip_mod.settings, "mock_external_apis", False)
    geoip_mod._geoip_cache.clear()
    geoip_mod._geoip_full_cache.clear()
    from apps.api.services.redis_client import get_redis

    for key in ("geoip2:203.0.113.77", "geoip:203.0.113.77", "geoip:backoff"):
        try:
            await get_redis().delete(key)
        except Exception:  # noqa: BLE001 — Redis is a cache; the test works without it
            pass

    monkeypatch.setattr(
        "apps.api.services.geoip_city.lookup_city",
        lambda _ip: CityResult("VN", "Hanoi", "Hanoi", 21.03, 105.85, 3),
    )
    monkeypatch.setattr(
        "apps.api.routers.onboarding.resolve_client_ip", lambda _r: "203.0.113.77"
    )
    monkeypatch.setattr(
        "apps.api.services.asn_lookup.lookup_asn", lambda _ip: (None, None)
    )

    r = await authed.post("/api/v1/onboarding/canary", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["geo"]["accuracy_km"] == 3
    assert body["geo"]["city"] == "Hanoi"
    # City DB carries no org/isp and the ASN rung is dead here, so the network
    # line is OMITTED rather than filled with a guess (config KNOWN LIMITATIONS).
    assert body["network"] is None


# ─── Two-provider cross-check ───────────────────────────────────────────────
#
# The reveal used to print whatever single provider it had. On residential
# non-US ranges that provider geolocates by ASN registration: one real FPT
# address resolved to Hanoi via ip-api, Haiphong via ipinfo, while the human was
# in Ho Chi Minh City. These tests pin the wire contract of the fix — the city
# must not merely be hidden by the client, it must not be SENT.
#
# `_lookup_second` is always stubbed. The suite pins GEO_CROSSCHECK_ENABLED off
# in conftest precisely so no test reaches the network; enabling it here without
# a stub would reintroduce that.

@pytest.fixture
def crosscheck_on(monkeypatch):
    from apps.api.services import geoip_crosscheck as xc

    monkeypatch.setattr(xc.settings, "geo_crosscheck_enabled", True)
    monkeypatch.setattr(xc.settings, "geo_crosscheck_disagree_km", 50)
    monkeypatch.setattr(xc.settings, "geo_crosscheck_max_radius_km", 300)
    monkeypatch.setattr(xc.settings, "mock_external_apis", False)
    # L1 is module-global and survives between tests in one process.
    xc._L1.clear()


def _second_provider(monkeypatch, point):
    async def _fake(_ip):
        return point

    monkeypatch.setattr("apps.api.services.geoip_crosscheck._lookup_second", _fake)


@pytest.mark.asyncio
async def test_agreeing_providers_keep_the_city(
    authed, flag_on, geo_ok, crosscheck_on, monkeypatch, test_engine
):
    _second_provider(monkeypatch, (21.05, 105.90, "Hanoi"))

    r = await authed.post("/api/v1/onboarding/canary", json={})
    assert r.status_code == 200
    geo = r.json()["geo"]
    assert geo["confidence"] == "high"
    assert geo["city"] == "Hanoi"
    assert geo["accuracy_km"] == 25


@pytest.mark.asyncio
async def test_disagreeing_providers_never_send_the_city(
    authed, flag_on, geo_ok, crosscheck_on, monkeypatch, test_engine
):
    """The real incident: ip-api Hanoi vs ipinfo Haiphong, ~90km apart."""
    _second_provider(monkeypatch, (20.8648, 106.6834, "Haiphong"))

    r = await authed.post("/api/v1/onboarding/canary", json={})
    assert r.status_code == 200
    geo = r.json()["geo"]
    assert geo["confidence"] == "low"
    # Not "hidden by the UI" — absent from the payload. A future surface that
    # reads this response cannot reprint a city it never received.
    assert geo["city"] == ""
    assert geo["region"] == ""
    assert geo["country_code"] == "VN"
    # The circle now genuinely contains both candidate answers.
    assert 80 <= geo["disagree_km"] <= 100
    assert geo["accuracy_km"] == geo["disagree_km"]
    # Neither rejected city name leaks through any other field.
    assert "Haiphong" not in r.text and "Hanoi" not in r.text


@pytest.mark.asyncio
async def test_dead_second_provider_is_unverified_not_degraded(
    authed, flag_on, geo_ok, crosscheck_on, monkeypatch, test_engine
):
    """A provider outage must not manufacture a disagreement — that would blank
    the city for every user the moment ipinfo rate-limits us."""
    _second_provider(monkeypatch, None)

    r = await authed.post("/api/v1/onboarding/canary", json={})
    assert r.status_code == 200
    geo = r.json()["geo"]
    assert geo["confidence"] == "unverified"
    assert geo["city"] == "Hanoi"
    assert "disagree_km" not in geo


@pytest.mark.asyncio
async def test_crosscheck_disabled_leaves_the_payload_alone(
    authed, flag_on, geo_ok, monkeypatch, test_engine
):
    """The conftest default. Confidence is still reported so the client never
    has to distinguish "old payload" from "flag off"."""
    r = await authed.post("/api/v1/onboarding/canary", json={})
    assert r.status_code == 200
    assert r.json()["geo"]["confidence"] == "unverified"


# ─── Ground truth: "wrong city" → which city, then? ─────────────────────────


@pytest.mark.asyncio
async def test_actual_city_is_stored_with_a_wrong_city_report(
    authed, flag_on, test_engine, user_id
):
    r = await authed.post(
        "/api/v1/onboarding/identity-feedback",
        json={
            "reasons": ["wrong_city"],
            "actual_city": "  Ho Chi Minh City  ",
            "shown": {"city": "Hanoi", "confidence": "unverified"},
        },
    )
    assert r.status_code == 204

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        row = (await s.execute(select(IdentityFeedback))).scalars().one()
    assert row.actual_city == "Ho Chi Minh City"


@pytest.mark.asyncio
async def test_actual_city_is_dropped_without_a_wrong_city_report(
    authed, flag_on, test_engine, user_id
):
    """Keeps the column a clean ground-truth pair with `shown["city"]` rather
    than a second free-text field anything could write into."""
    r = await authed.post(
        "/api/v1/onboarding/identity-feedback",
        json={"reasons": ["vpn_or_proxy"], "actual_city": "Ho Chi Minh City"},
    )
    assert r.status_code == 204

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        row = (await s.execute(select(IdentityFeedback))).scalars().one()
    assert row.actual_city is None


@pytest.mark.asyncio
async def test_actual_city_is_truncated_not_rejected(
    authed, flag_on, test_engine, user_id
):
    r = await authed.post(
        "/api/v1/onboarding/identity-feedback",
        json={"reasons": ["wrong_city"], "actual_city": "x" * 400},
    )
    assert r.status_code == 204

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        row = (await s.execute(select(IdentityFeedback))).scalars().one()
    assert len(row.actual_city) == 120


@pytest.mark.asyncio
async def test_stats_reports_the_city_correction_pairs(admin, flag_on, test_engine):
    """The metric the table exists for: not "we were wrong N times" but "we said
    Hanoi and they were in Ho Chi Minh City".

    Posts as `admin` rather than pulling in `authed` too: both fixtures write
    `app.dependency_overrides[get_current_user]`, so requesting both would leave
    whichever set up last in charge and silently 403 the stats read.
    """
    for _ in range(2):
        await admin.post(
            "/api/v1/onboarding/identity-feedback",
            json={
                "reasons": ["wrong_city"],
                "actual_city": "Ho Chi Minh City",
                "shown": {"city": "Hanoi"},
            },
        )

    r = await admin.get("/api/v1/onboarding/identity-feedback/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["with_actual_city"] == 2
    # Asserts the pair and the count, not the whole row: the address-family
    # breakdown is this endpoint's own test (test_stats_breaks_corrections_down_
    # by_family), and pinning the full dict here just makes both tests fail
    # whenever one field is added.
    assert len(body["city_corrections"]) == 1
    row = body["city_corrections"][0]
    assert row["shown"] == "Hanoi"
    assert row["actual"] == "Ho Chi Minh City"
    assert row["count"] == 2
    # The rounded coordinates stay unreturned — only the city pair was widened.
    assert "lat" not in r.text and "lng" not in r.text


# ─── v4 vs v6 tagging ───────────────────────────────────────────────────────
#
# The reason this exists: the SAME machine geolocated correctly over IPv6 and
# incorrectly over IPv4 on one measured FPT connection. One anecdote is not a
# reason to build a v6-only measurement endpoint, so tag every report with the
# family it came from and let the rate decide.


@pytest.mark.asyncio
async def test_feedback_records_the_address_family_server_side(
    authed, flag_on, test_engine, monkeypatch
):
    monkeypatch.setattr(
        "apps.api.routers.onboarding.resolve_client_ip",
        lambda _r: "2606:4700:3036::ac43:bda4",
    )
    r = await authed.post(
        "/api/v1/onboarding/identity-feedback",
        json={"reasons": ["wrong_city"], "shown": {"city": "Hanoi"}},
    )
    assert r.status_code == 204

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        row = (await s.execute(select(IdentityFeedback))).scalars().one()
    assert row.shown["ip_family"] == "v6"
    assert row.shown["city"] == "Hanoi"


@pytest.mark.asyncio
async def test_client_cannot_forge_the_address_family(
    authed, flag_on, test_engine, monkeypatch
):
    """`shown` is client-supplied; the family is the one key in it that has to
    be trustworthy, or the v4-vs-v6 comparison measures nothing."""
    monkeypatch.setattr(
        "apps.api.routers.onboarding.resolve_client_ip", lambda _r: "42.117.132.191"
    )
    r = await authed.post(
        "/api/v1/onboarding/identity-feedback",
        json={"reasons": ["wrong_city"], "shown": {"ip_family": "v6"}},
    )
    assert r.status_code == 204

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        row = (await s.execute(select(IdentityFeedback))).scalars().one()
    assert row.shown["ip_family"] == "v4"


@pytest.mark.asyncio
async def test_stats_breaks_corrections_down_by_family(admin, flag_on, test_engine, monkeypatch):
    monkeypatch.setattr(
        "apps.api.routers.onboarding.resolve_client_ip", lambda _r: "42.117.132.191"
    )
    await admin.post(
        "/api/v1/onboarding/identity-feedback",
        json={
            "reasons": ["wrong_city"],
            "actual_city": "Ho Chi Minh City",
            "shown": {"city": "Hanoi"},
        },
    )

    r = await admin.get("/api/v1/onboarding/identity-feedback/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["by_ip_family"] == [{"ip_family": "v4", "count": 1}]
    assert body["city_corrections"] == [
        {
            "shown": "Hanoi",
            "actual": "Ho Chi Minh City",
            "ip_family": "v4",
            "count": 1,
        }
    ]


# ── Display policy v2 — per-mode payload shape on BOTH surfaces ──────────────
#
# The unit lane proves the pure decider. These prove the ROUTERS call it and
# that what goes on the wire is actually stripped — a client cannot leak a name
# it was never sent, but only if the server really never sends it.

_ROUTES = ["/api/v1/onboarding/canary", "/api/v1/demo/canary"]


def _patch_geo(monkeypatch, geo, *, cross=None):
    """Patch both routers identically — D7 means there is no divergence to test."""
    async def _fake(_ip):
        return geo

    for mod in ("onboarding", "demo"):
        monkeypatch.setattr(f"apps.api.routers.{mod}.resolve_geoip_full", _fake)
    monkeypatch.setattr("apps.api.services.asn_lookup.lookup_asn", lambda _ip: (None, None))
    if cross is not None:
        async def _cross(_ip, _primary):
            return cross

        monkeypatch.setattr("apps.api.services.geoip_crosscheck.crosscheck_geo", _cross)
        monkeypatch.setattr("apps.api.routers.onboarding.crosscheck_geo", _cross)


def _cc(**kw):
    from apps.api.services.geoip_crosscheck import CrossCheck

    base = dict(checked=True, agreed=True, distance_km=1.0, second_city="Hanoi",
                second_country="VN", country_agreed=True)
    base.update(kw)
    return CrossCheck(**base)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", _ROUTES)
async def test_map_mode_carries_the_full_payload(authed, flag_on, monkeypatch, route):
    _patch_geo(monkeypatch, _GEO, cross=_cc())
    r = await authed.post(route, json={"fingerprint": FP})
    assert r.status_code == 200
    body = r.json()
    assert body["display_mode"] == "map"
    assert body["geo"]["lat"] == pytest.approx(21.03)
    assert body["geo"]["city"] == "Hanoi"


@pytest.mark.asyncio
@pytest.mark.parametrize("route", _ROUTES)
async def test_country_mode_omits_coordinates_on_the_wire(
    authed, flag_on, monkeypatch, route
):
    """AC-6: the client cannot leak a name it was never sent."""
    # A relay network routes to `country` regardless of confidence.
    relay_geo = GeoResult(
        country_code="VN", region="Hanoi", city="Hanoi", lat=21.03, lon=105.85,
        isp="Cloudflare WARP", org="Cloudflare, Inc.", as_str="AS13335 Cloudflare",
    )
    _patch_geo(monkeypatch, relay_geo, cross=_cc())
    monkeypatch.setattr(
        "apps.api.services.onboarding_canary.classify_org_kind", lambda *_a, **_k: "cdn"
    )
    r = await authed.post(route, json={"fingerprint": FP})
    assert r.status_code == 200
    body = r.json()
    assert body["display_mode"] == "country"
    assert "lat" not in body["geo"]
    assert "lng" not in body["geo"]
    assert "accuracy_km" not in body["geo"]
    assert body["geo"]["city"] == ""
    assert body["geo"]["region"] == ""
    assert body["geo"]["country_code"] == "VN"


@pytest.mark.asyncio
@pytest.mark.parametrize("route", _ROUTES)
async def test_low_confidence_is_country_not_a_wide_map(
    authed, flag_on, monkeypatch, route
):
    _patch_geo(monkeypatch, _GEO, cross=_cc(agreed=False, distance_km=93.0))
    body = (await authed.post(route, json={"fingerprint": FP})).json()
    assert body["display_mode"] == "country"
    assert "lat" not in body["geo"]


@pytest.mark.asyncio
@pytest.mark.parametrize("route", _ROUTES)
async def test_country_disagreement_is_none_with_its_own_reason(
    authed, flag_on, monkeypatch, route
):
    """Row 7. The ONLY place it is distinguishable from row 8."""
    _patch_geo(monkeypatch, _GEO, cross=_cc(second_country="CN", country_agreed=False))
    body = (await authed.post(route, json={"fingerprint": FP})).json()
    assert body["display_mode"] == "none"
    assert body["geo"] is None
    assert body["reason"] == "country_disagreement"


@pytest.mark.asyncio
@pytest.mark.parametrize("route", _ROUTES)
async def test_provider_failure_is_none_with_the_other_reason(
    authed, flag_on, monkeypatch, route
):
    """Row 8 — the companion of the case above."""
    _patch_geo(monkeypatch, None)
    body = (await authed.post(route, json={"fingerprint": FP})).json()
    assert body["display_mode"] == "none"
    assert body["geo"] is None
    assert body["reason"] == "provider_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("route", _ROUTES)
async def test_no_mode_ever_leaks_an_identifier(authed, flag_on, monkeypatch, route):
    _patch_geo(monkeypatch, _GEO, cross=_cc())
    raw = (await authed.post(route, json={"fingerprint": FP})).text
    for banned in ("site_id", "visitor_id", "fingerprint", '"ip"'):
        assert banned not in raw


@pytest.mark.asyncio
async def test_client_cannot_forge_the_display_mode(
    authed, flag_on, test_engine, monkeypatch
):
    """`shown["display_mode"]` is server-owned — same posture as ip_family."""
    _patch_geo(monkeypatch, _GEO, cross=_cc())
    monkeypatch.setattr(
        "apps.api.routers.onboarding.resolve_client_ip", lambda _r: "42.117.132.191"
    )
    r = await authed.post(
        "/api/v1/onboarding/identity-feedback",
        json={"reasons": ["wrong_city"], "shown": {"display_mode": "totally-fake"}},
    )
    assert r.status_code == 204

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        row = (await s.execute(select(IdentityFeedback))).scalars().one()
    assert row.shown["display_mode"] in {"map", "country", "none"}
    assert row.shown["display_mode"] != "totally-fake"
    # AC-14: the pre-existing stamp is preserved alongside the new one.
    assert row.shown["ip_family"] == "v4"
