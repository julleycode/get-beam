"""Integration tests for the PUBLIC canary — POST /api/v1/demo/canary.

The unauthed twin of /api/v1/onboarding/canary, used by the static funnel at
/beam/onboarding.html. Mirrors tests/integration/test_onboarding_canary_api.py,
plus the two guards that only matter because this route has no auth gate:

  1. Flag OFF => 404 on both routes, and no provider call.
  2. Body-supplied `ip` is IGNORED — the only IP resolved is the caller's own.
     Without this the endpoint is a free geolocation API for arbitrary IPs.
  3. The journey is scoped to Beam's own site — a fingerprint colliding with a
     visitor on ANOTHER site returns no pages. (`/demo/journey` deliberately
     keeps its historical unscoped behaviour; this route must not.)
  4. No ip / site_id / visitor_id / fingerprint anywhere in the body.
  5. A provider failure degrades to 200 + geo:null, never a 500.
  6. The per-IP rate limit trips.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.models.event import Event
from apps.api.models.identity_feedback import ANONYMOUS_USER_ID, IdentityFeedback
from apps.api.models.visitor import Visitor
from apps.api.services.geoip import GeoResult

pytestmark = pytest.mark.integration

BEAM_SITE = "site_90a488f43eac"
OTHER_SITE = "site_someone_else"
FP = "fp2_publiccanaryfingerprint"

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


@pytest.fixture
def flag_on(monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "location_reveal_enabled", True)
    monkeypatch.setattr(settings, "beam_self_site_id", BEAM_SITE)


@pytest.fixture
def geo_ok(monkeypatch):
    async def _fake(_ip):
        return _GEO

    monkeypatch.setattr("apps.api.services.geoip.resolve_geoip_full", _fake)
    # The ASN rung is dead in this repo's default env; pin it so the label is
    # deterministic regardless of whether a local mmdb happens to exist.
    monkeypatch.setattr(
        "apps.api.services.asn_lookup.lookup_asn", lambda _ip: (None, None)
    )


@pytest.mark.asyncio
async def test_flag_off_returns_404_and_calls_no_provider(test_client, monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "location_reveal_enabled", False)

    async def _boom(_ip):
        raise AssertionError("provider must not be called when the flag is off")

    monkeypatch.setattr("apps.api.services.geoip.resolve_geoip_full", _boom)

    r = await test_client.post("/api/v1/demo/canary", json={"fingerprint": FP})
    assert r.status_code == 404

    r2 = await test_client.post(
        "/api/v1/demo/identity-feedback", json={"reasons": ["wrong_city"]}
    )
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_public_no_auth_required(test_client, flag_on, geo_ok):
    """The whole point: this twin answers WITHOUT a bearer token."""
    r = await test_client.post("/api/v1/demo/canary", json={})
    assert r.status_code == 200
    assert r.json()["geo"] is not None


@pytest.mark.asyncio
async def test_returns_full_shape(test_client, flag_on, geo_ok, test_engine):
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    await _seed_visit(factory, BEAM_SITE, "v-pub-beam")

    r = await test_client.post("/api/v1/demo/canary", json={"fingerprint": FP})
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
async def test_response_never_leaks_identifiers(test_client, flag_on, geo_ok, test_engine):
    """Anti-regression: a future "while we're here, also return X" trips here."""
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    await _seed_visit(factory, BEAM_SITE, "v-pub-leak")

    r = await test_client.post("/api/v1/demo/canary", json={"fingerprint": FP})
    assert r.status_code == 200
    body = r.json()

    for forbidden in ("ip", "site_id", "visitor_id", "fingerprint"):
        assert forbidden not in body, f"{forbidden} must never be in the response"
    for page in body["pages"]:
        for forbidden in ("ip", "site_id", "visitor_id", "fingerprint"):
            assert forbidden not in page
    raw = r.text
    assert BEAM_SITE not in raw
    assert FP not in raw


@pytest.mark.asyncio
async def test_journey_is_scoped_to_beam_site(test_client, flag_on, geo_ok, test_engine):
    """A fingerprint collision on ANOTHER tenant's site must return no pages —
    the predicate /demo/journey deliberately lacks."""
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    await _seed_visit(factory, OTHER_SITE, "v-pub-other")

    r = await test_client.post("/api/v1/demo/canary", json={"fingerprint": FP})
    assert r.status_code == 200
    body = r.json()
    assert body["pages"] == []
    assert body["landed"] is False
    # Geo still works — it reads the caller's IP, not the matched visitor row.
    assert body["geo"] is not None


@pytest.mark.asyncio
async def test_body_supplied_ip_is_ignored(test_client, flag_on, monkeypatch):
    """THE key public-surface guard.

    If a caller could name the IP, this becomes a free geolocation-lookup API for
    arbitrary addresses. The resolver must only ever see the caller's own.
    """
    seen: list[str] = []

    async def _capture(ip):
        seen.append(ip)
        return _GEO

    monkeypatch.setattr("apps.api.services.geoip.resolve_geoip_full", _capture)
    monkeypatch.setattr(
        "apps.api.services.asn_lookup.lookup_asn", lambda _ip: (None, None)
    )

    r = await test_client.post(
        "/api/v1/demo/canary",
        json={"fingerprint": FP, "ip": "8.8.8.8", "client_ip": "1.1.1.1"},
        params={"ip": "9.9.9.9"},
    )
    assert r.status_code == 200
    assert seen, "the geo provider should have been called"
    for attacker_ip in ("8.8.8.8", "1.1.1.1", "9.9.9.9"):
        assert attacker_ip not in seen, f"{attacker_ip} was accepted from the caller"


@pytest.mark.asyncio
async def test_x_forwarded_for_is_not_trusted(test_client, flag_on, monkeypatch):
    """trusted_proxy_hops defaults to 0, so XFF must be ignored entirely.

    `demo._client_ip` (used by the older demo routes) takes XFF[0] verbatim; this
    route uses `resolve_client_ip` precisely so that spoof does not work.
    """
    seen: list[str] = []

    async def _capture(ip):
        seen.append(ip)
        return _GEO

    monkeypatch.setattr("apps.api.services.geoip.resolve_geoip_full", _capture)
    monkeypatch.setattr(
        "apps.api.services.asn_lookup.lookup_asn", lambda _ip: (None, None)
    )
    from apps.api.config import settings

    monkeypatch.setattr(settings, "trusted_proxy_hops", 0)
    monkeypatch.setattr(settings, "ingest_trust_cf_connecting_ip", False)

    r = await test_client.post(
        "/api/v1/demo/canary", json={}, headers={"X-Forwarded-For": "8.8.8.8"}
    )
    assert r.status_code == 200
    assert "8.8.8.8" not in seen


@pytest.mark.asyncio
async def test_provider_failure_degrades_not_500(test_client, flag_on, monkeypatch):
    async def _fail(_ip):
        raise RuntimeError("provider down")

    monkeypatch.setattr("apps.api.services.geoip.resolve_geoip_full", _fail)

    r = await test_client.post("/api/v1/demo/canary", json={"fingerprint": FP})
    assert r.status_code == 200
    body = r.json()
    assert body["geo"] is None
    assert body["network"] is None
    assert body.get("reason") == "provider_unavailable"


@pytest.mark.asyncio
async def test_does_not_consume_the_demo_budget(test_client, flag_on, geo_ok, monkeypatch):
    """This route calls no paid provider, so it must not spend the identity
    budget /identify depends on."""
    import apps.api.routers.demo as demo_mod

    async def _boom() -> None:
        raise AssertionError("the free canary must not touch the demo budget")

    monkeypatch.setattr(demo_mod, "_enforce_demo_budget", _boom)

    r = await test_client.post("/api/v1/demo/canary", json={})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_trips(test_client, flag_on, geo_ok):
    """40/minute per IP. Enough for a full 90s poll plus one reload, not enough
    for bulk use."""
    from apps.api.services.rate_limiter import limiter

    # conftest disables the limiter globally; this test is specifically about
    # limiter behaviour, so re-enable it and start from a clean bucket.
    limiter.enabled = True
    try:
        try:
            limiter.reset()
        except Exception:
            pass

        statuses = [
            (await test_client.post("/api/v1/demo/canary", json={})).status_code
            for _ in range(45)
        ]
    finally:
        limiter.enabled = False
        try:
            limiter.reset()
        except Exception:
            pass

    assert 429 in statuses, f"rate limit never tripped: {sorted(set(statuses))}"
    # …and not before the documented allowance, or a real 90s poll would 429.
    assert statuses.index(429) >= 40, (
        f"limiter tripped at call {statuses.index(429)}, before the 40/minute allowance"
    )


@pytest.mark.asyncio
async def test_feedback_persists_anonymously_and_filters_reasons(
    test_client, flag_on, test_engine
):
    r = await test_client.post(
        "/api/v1/demo/identity-feedback",
        json={
            "reasons": ["wrong_city", "bogus_reason", "vpn_or_proxy"],
            "note": "x" * 900,
            "shown": {"city": "Hanoi", "kind": "isp"},
            "fingerprint": FP,
        },
    )
    assert r.status_code == 204

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        rows = (
            await s.execute(
                select(IdentityFeedback).where(
                    IdentityFeedback.surface == "public_onboarding_canary"
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == ANONYMOUS_USER_ID
    assert row.site_id is None
    assert sorted(row.reasons) == ["vpn_or_proxy", "wrong_city"]
    assert len(row.note) == 500
