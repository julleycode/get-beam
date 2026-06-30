"""Integration test — CRM push end-to-end against a real Postgres.

Proves the things the mock unit tests can't:
- the push goes through the router → shared service → connector with real rows,
- the compliance guards (do_not_email + do_not_sell suppression) actually drop
  contacts from an outbound push,
- site ownership scoping returns 404 for a non-owner,
- unknown providers 404.

Runs the connectors in mock mode (no real HTTP). Requires local PostgreSQL.
"""

import uuid as uuidlib

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "CRM Tester"},
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
async def push_setup(test_client, test_db, monkeypatch):
    from apps.api.config import settings
    from apps.api.models.segment import Segment, SegmentMember
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import IdentifiedVisitor
    from apps.api.services.suppression import add_suppression

    monkeypatch.setattr(settings, "mock_external_apis", True)

    email = f"crm-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"crm_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="CRM Site", url="https://crm.example.com"))

    seg_id = uuidlib.uuid4()
    test_db.add(Segment(id=seg_id, site_id=site_id, name="Push me", visitor_count=3))

    # 3 members: A pushable, B do_not_email, C suppressed (do_not_sell).
    rows = [
        ("vA", "a@example.com", False),
        ("vB", "b@example.com", True),
        ("vC", "c@example.com", False),
    ]
    for visitor_id, vemail, dne in rows:
        test_db.add(SegmentMember(segment_id=seg_id, visitor_id=visitor_id, site_id=site_id))
        test_db.add(
            IdentifiedVisitor(
                site_id=site_id,
                visitor_id=visitor_id,
                email=vemail,
                full_name="First Last",
                # Must be a person-level provider or the emailable guard drops it
                # (a company-level guess is never exported/pushed).
                resolution_provider="form_capture",
                do_not_email=dne,
            )
        )
    await test_db.commit()

    # Suppress C under the "do_not_sell" scope the exporter checks.
    await add_suppression(test_db, "c@example.com", "do_not_sell")

    return {"token": token, "site_id": site_id, "segment_id": str(seg_id)}


async def _save_webhook(test_client, site_id, token):
    # Public IP literal → passes the SSRF guard deterministically (no DNS). In
    # mock mode no real request is sent.
    return await test_client.put(
        f"/api/v1/crm/{site_id}/connections/generic_webhook",
        headers=_auth(token),
        json={"webhook_url": "https://8.8.8.8/beam", "secret": "secret123"},
    )


async def test_push_skips_suppressed_and_do_not_email(push_setup, test_client):
    s = push_setup
    saved = await _save_webhook(test_client, s["site_id"], s["token"])
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "connected"

    listed = await test_client.get(
        f"/api/v1/crm/{s['site_id']}/connections", headers=_auth(s["token"])
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    # secret never leaks
    assert "secret" not in listed.json()[0] or listed.json()[0].get("secret_hint")

    pushed = await test_client.post(
        f"/api/v1/crm/{s['site_id']}/connections/generic_webhook/push",
        headers=_auth(s["token"]),
        json={"segment_id": s["segment_id"]},
    )
    assert pushed.status_code == 200, pushed.text
    body = pushed.json()
    # Only vA is emailable: vB is do_not_email, vC is do_not_sell-suppressed.
    assert body["pushed"] == 1, body
    assert body["skipped"] == 2, body
    assert body["failed"] == 0, body


async def test_push_requires_site_ownership(push_setup, test_client):
    s = push_setup
    await _save_webhook(test_client, s["site_id"], s["token"])

    other = await _signup(test_client, f"intruder-{uuidlib.uuid4().hex[:8]}@test.com")
    resp = await test_client.post(
        f"/api/v1/crm/{s['site_id']}/connections/generic_webhook/push",
        headers=_auth(other),
        json={"segment_id": s["segment_id"]},
    )
    assert resp.status_code == 404, resp.text

    listed = await test_client.get(
        f"/api/v1/crm/{s['site_id']}/connections", headers=_auth(other)
    )
    assert listed.status_code == 404


async def test_webhook_ssrf_guard_rejects_private(push_setup, test_client):
    s = push_setup
    resp = await test_client.put(
        f"/api/v1/crm/{s['site_id']}/connections/generic_webhook",
        headers=_auth(s["token"]),
        json={"webhook_url": "http://169.254.169.254/latest/meta-data/", "secret": "secret123"},
    )
    assert resp.status_code == 400, resp.text


async def test_unknown_provider_404(push_setup, test_client):
    s = push_setup
    resp = await test_client.post(
        f"/api/v1/crm/{s['site_id']}/connections/mailchimp/test",
        headers=_auth(s["token"]),
        json={},
    )
    assert resp.status_code == 404


async def test_rate_limit_returns_429(push_setup, test_client, monkeypatch):
    """Router returns 429 when the per-site push limiter denies a slot.

    (The limiter's own Redis behavior is unit-tested; here we stub it to False
    because the shared async Redis client is bound to a stale loop in the test
    harness and would fail open.)
    """
    import apps.api.routers.crm as crm_router

    s = push_setup
    await _save_webhook(test_client, s["site_id"], s["token"])

    async def _deny(_site_id: str) -> bool:
        return False

    monkeypatch.setattr(crm_router, "check_and_reserve_push", _deny)
    resp = await test_client.post(
        f"/api/v1/crm/{s['site_id']}/connections/generic_webhook/push",
        headers=_auth(s["token"]),
        json={"segment_id": s["segment_id"]},
    )
    assert resp.status_code == 429, resp.text


async def test_hubspot_oauth_roundtrip(push_setup, test_client, monkeypatch):
    """connect → callback (mock exchange) → connection stored + tokens encrypted."""
    from urllib.parse import parse_qs, urlparse

    from apps.api.config import settings

    s = push_setup
    monkeypatch.setattr(settings, "hubspot_client_id", "cid")
    monkeypatch.setattr(settings, "hubspot_client_secret", "csecret")

    connect = await test_client.post(
        f"/api/v1/crm/{s['site_id']}/connections/hubspot/connect", headers=_auth(s["token"])
    )
    assert connect.status_code == 200, connect.text
    auth_url = connect.json()["auth_url"]
    state = parse_qs(urlparse(auth_url).query)["state"][0]

    callback = await test_client.get(
        f"/api/v1/crm/callback/hubspot?code=abc&state={state}"
    )
    assert callback.status_code in (302, 307), callback.text
    assert "crm=connected" in callback.headers["location"]

    listed = await test_client.get(
        f"/api/v1/crm/{s['site_id']}/connections", headers=_auth(s["token"])
    )
    providers = {c["provider"]: c for c in listed.json()}
    assert providers["hubspot"]["status"] == "connected"
    # The out-schema must never expose tokens — only safe fields.
    assert "access_token" not in providers["hubspot"]
    assert "refresh_token" not in providers["hubspot"]
