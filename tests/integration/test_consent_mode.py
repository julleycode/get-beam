"""Integration tests for the per-site cookie-consent mode.

Covers:
- New sites default to consent_mode = "off".
- PATCH /sites/{site_id} sets consent_mode (owner-scoped) and it persists.
- Invalid consent_mode → 422 (schema validation).
- The pixel snippet emits data-consent only when the mode is not "off"
  (existing "off" sites keep their exact snippet — zero churn).

Requires: PostgreSQL running locally (via docker-compose).
"""

import uuid as uuidlib

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Consent Tester"},
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
async def consent_setup(test_client, test_db):
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"consent-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"consent_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="Consent Site", url="https://c.example.com"))
    await test_db.commit()
    return {"token": token, "site_id": site_id}


class TestConsentModeEndpoint:
    @pytest.mark.asyncio
    async def test_defaults_off_then_sets_eu(self, test_client, consent_setup):
        sid, token = consent_setup["site_id"], consent_setup["token"]

        resp = await test_client.get(f"/api/v1/sites/{sid}", headers=_auth(token))
        assert resp.status_code == 200, resp.text
        assert resp.json()["consent_mode"] == "off"

        resp = await test_client.patch(
            f"/api/v1/sites/{sid}", headers=_auth(token), json={"consent_mode": "eu"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["consent_mode"] == "eu"

        # Persisted
        resp = await test_client.get(f"/api/v1/sites/{sid}", headers=_auth(token))
        assert resp.json()["consent_mode"] == "eu"

    @pytest.mark.asyncio
    async def test_invalid_mode_rejected(self, test_client, consent_setup):
        sid, token = consent_setup["site_id"], consent_setup["token"]
        resp = await test_client.patch(
            f"/api/v1/sites/{sid}", headers=_auth(token), json={"consent_mode": "bogus"}
        )
        assert resp.status_code == 422, resp.text

    @pytest.mark.asyncio
    async def test_other_user_cannot_set(self, test_client, consent_setup):
        other_token = await _signup(test_client, f"other-{uuidlib.uuid4().hex[:8]}@test.com")
        resp = await test_client.patch(
            f"/api/v1/sites/{consent_setup['site_id']}",
            headers=_auth(other_token),
            json={"consent_mode": "eu"},
        )
        assert resp.status_code == 404


class TestConsentSnippet:
    @pytest.mark.asyncio
    async def test_snippet_omits_consent_when_off(self, test_client, consent_setup):
        sid, token = consent_setup["site_id"], consent_setup["token"]
        resp = await test_client.get(f"/api/v1/sites/{sid}/pixel", headers=_auth(token))
        assert resp.status_code == 200, resp.text
        assert "data-consent" not in resp.json()["snippet"]

    @pytest.mark.asyncio
    async def test_snippet_emits_consent_when_eu(self, test_client, consent_setup):
        sid, token = consent_setup["site_id"], consent_setup["token"]
        await test_client.patch(
            f"/api/v1/sites/{sid}", headers=_auth(token), json={"consent_mode": "eu"}
        )
        resp = await test_client.get(f"/api/v1/sites/{sid}/pixel", headers=_auth(token))
        assert 'data-consent="eu"' in resp.json()["snippet"]
