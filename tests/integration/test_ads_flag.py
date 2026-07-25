"""AC10 — feature flag behavior, end-to-end through the ASGI app.

Flag OFF (the default): every /api/v1/ads write endpoint returns 501 and the
pre-existing CSV export path is untouched — no site's behavior changes.
Flag ON + MOCK_EXTERNAL_APIS: connect and push are deterministic, with zero
live network calls.

Requires local PostgreSQL + Redis.
"""

import uuid as uuidlib

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Ads Flag"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def flag_setup(test_client, test_db, monkeypatch):
    from apps.api.config import settings
    from apps.api.models.ad_connection import AdConnection
    from apps.api.models.segment import Segment, SegmentMember
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import IdentifiedVisitor

    monkeypatch.setattr(settings, "mock_external_apis", True)

    email = f"ads-flag-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"ads_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="Ads", url="https://ads.example.com"))

    seg_id = uuidlib.uuid4()
    test_db.add(Segment(id=seg_id, site_id=site_id, name="Flagged", visitor_count=1))
    test_db.add(SegmentMember(segment_id=seg_id, visitor_id="vf", site_id=site_id))
    test_db.add(
        IdentifiedVisitor(
            site_id=site_id, visitor_id="vf", email="flag@example.com",
            full_name="First Last", resolution_provider="form_capture",
        )
    )
    test_db.add(
        AdConnection(
            id=uuidlib.uuid4(), site_id=site_id, user_id=user.id, provider="meta",
            auth_type="oauth", status="connected",
        )
    )
    await test_db.commit()
    return {"token": token, "site_id": site_id, "segment_id": str(seg_id)}


# ── Flag OFF: baseline unchanged ─────────────────────────

async def test_ads_flag_off_connect_and_push_return_501(test_client, flag_setup, monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "ad_audiences_enabled", False)
    site_id, token = flag_setup["site_id"], flag_setup["token"]

    r = await test_client.post(
        f"/api/v1/ads/{site_id}/connections/meta/connect", headers=_auth(token)
    )
    assert r.status_code == 501, r.text

    r = await test_client.post(
        f"/api/v1/ads/{site_id}/connections/meta/push",
        json={"segment_id": flag_setup["segment_id"]},
        headers=_auth(token),
    )
    assert r.status_code == 501, r.text


async def test_ads_flag_off_csv_export_baseline_unchanged(test_db, flag_setup, monkeypatch):
    """The pre-existing CSV export path is untouched while the flag is off.

    Exercised at the service layer rather than through GET /api/v1/exports:
    that route returns a StreamingResponse, which hangs under httpx's
    ASGITransport in this suite (a pre-existing test-infra gap — there is no
    integration coverage for exports today for the same reason). The e2e leg
    covers the HTTP route.
    """
    from apps.api.config import settings
    from apps.api.services.csv_exporter import _sha256, export_meta_csv

    monkeypatch.setattr(settings, "ad_audiences_enabled", False)
    csv_text = await export_meta_csv(test_db, flag_setup["segment_id"])
    assert csv_text.splitlines()[0] == "email,phone,fn,ln,ct,st,country,zip"
    assert _sha256("flag@example.com") in csv_text
    assert "flag@example.com" not in csv_text  # hashed, as before


# ── Flag ON + mock mode: deterministic ───────────────────

async def test_ads_flag_on_mock_mode_connect_is_deterministic(test_client, flag_setup, monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "ad_audiences_enabled", True)
    r = await test_client.post(
        f"/api/v1/ads/{flag_setup['site_id']}/connections/google/connect",
        headers=_auth(flag_setup["token"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["auth_url"].startswith("https://mock.google.test/")


async def test_ads_flag_on_mock_mode_push_is_deterministic(test_client, flag_setup, monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "ad_audiences_enabled", True)
    r = await test_client.post(
        f"/api/v1/ads/{flag_setup['site_id']}/connections/meta/push",
        json={"segment_id": flag_setup["segment_id"]},
        headers=_auth(flag_setup["token"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pushed"] == 1
    assert body["platform_audience_id"].startswith("mock-meta-aud-")
    assert body["warning"]  # 1 contact is well below the minimum
    # Never echo a plaintext identifier back to the client.
    assert "flag@example.com" not in r.text


async def test_ads_flag_on_linkedin_connect_is_rejected(test_client, flag_setup, monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "ad_audiences_enabled", True)
    r = await test_client.post(
        f"/api/v1/ads/{flag_setup['site_id']}/connections/linkedin/connect",
        headers=_auth(flag_setup["token"]),
    )
    assert r.status_code == 400, r.text


async def test_ads_flag_on_foreign_site_is_404_not_403(test_client, flag_setup, monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "ad_audiences_enabled", True)
    r = await test_client.get(
        "/api/v1/ads/someone_elses_site/connections", headers=_auth(flag_setup["token"])
    )
    assert r.status_code == 404, r.text


async def test_ads_flag_on_unknown_provider_is_404(test_client, flag_setup, monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "ad_audiences_enabled", True)
    r = await test_client.post(
        f"/api/v1/ads/{flag_setup['site_id']}/connections/tiktok/connect",
        headers=_auth(flag_setup["token"]),
    )
    assert r.status_code == 404, r.text
