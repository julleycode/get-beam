"""Integration tests for Phase 05 — the auto-identify toggle.

Covers:
- PATCH /sites/{site_id} flips auto_identify_enabled (owner-scoped; 404 for others).
- New sites default to auto_identify_enabled = False.
- run_resolution_sweep only processes sites with the toggle ON (the real WHERE
  filter, exercised against the test DB).

Requires: PostgreSQL running locally (via docker-compose).
"""

import uuid as uuidlib
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Toggle Tester"},
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
async def toggle_setup(test_client, test_db):
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"toggle-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"toggle_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="Toggle Site", url="https://t.example.com"))
    await test_db.commit()
    return {"token": token, "site_id": site_id}


class TestAutoIdentifyToggleEndpoint:
    @pytest.mark.asyncio
    async def test_defaults_off_then_toggles(self, test_client, toggle_setup):
        sid, token = toggle_setup["site_id"], toggle_setup["token"]

        # Default off
        resp = await test_client.get(f"/api/v1/sites/{sid}", headers=_auth(token))
        assert resp.status_code == 200, resp.text
        assert resp.json()["auto_identify_enabled"] is False

        # Turn on
        resp = await test_client.patch(
            f"/api/v1/sites/{sid}",
            headers=_auth(token),
            json={"auto_identify_enabled": True},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["auto_identify_enabled"] is True

        # Persisted
        resp = await test_client.get(f"/api/v1/sites/{sid}", headers=_auth(token))
        assert resp.json()["auto_identify_enabled"] is True

        # Turn back off
        resp = await test_client.patch(
            f"/api/v1/sites/{sid}",
            headers=_auth(token),
            json={"auto_identify_enabled": False},
        )
        assert resp.json()["auto_identify_enabled"] is False

    @pytest.mark.asyncio
    async def test_other_user_cannot_toggle(self, test_client, toggle_setup):
        other_token = await _signup(test_client, f"other-{uuidlib.uuid4().hex[:8]}@test.com")
        resp = await test_client.patch(
            f"/api/v1/sites/{toggle_setup['site_id']}",
            headers=_auth(other_token),
            json={"auto_identify_enabled": True},
        )
        assert resp.status_code == 404


class TestSweepRespectsToggle:
    @pytest.mark.asyncio
    async def test_sweep_only_runs_enabled_sites(self, test_client, test_db, monkeypatch):
        from apps.api.models.site import Site
        from apps.api.models.user import User
        from apps.api.services import resolution_runner

        user = User(email=f"sweep-{uuidlib.uuid4().hex[:8]}@test.com", full_name="Sweep")
        test_db.add(user)
        await test_db.flush()

        on_id = f"on_{uuidlib.uuid4().hex[:8]}"
        off_id = f"off_{uuidlib.uuid4().hex[:8]}"
        test_db.add(Site(site_id=on_id, user_id=user.id, name="On", url="https://on.example.com", auto_identify_enabled=True))
        test_db.add(Site(site_id=off_id, user_id=user.id, name="Off", url="https://off.example.com", auto_identify_enabled=False))
        await test_db.commit()

        called: list[str] = []

        async def fake_run(db, site, max_resolve=20):
            called.append(site.site_id)
            return {"processed": 0, "resolved": 0, "enriched": 0, "skipped_plan_limit": 0}

        monkeypatch.setattr(resolution_runner, "run_resolution_for_site", fake_run)

        await resolution_runner.run_resolution_sweep()

        assert on_id in called
        assert off_id not in called
