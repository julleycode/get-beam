"""Integration test for per-user dashboard widget-layout sync.

GET/PUT /api/v1/auth/widget-layout persist an ordered widget-id list per
surface on the user (JSONB). Requires PostgreSQL (via docker-compose).
"""

import uuid as uuidlib

import pytest

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "WL Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestWidgetLayout:
    @pytest.mark.asyncio
    async def test_default_is_null_then_round_trips(self, test_client, test_db):
        token = await _signup(test_client, f"wl-{uuidlib.uuid4().hex[:8]}@test.com")

        # No layout saved yet → null (client uses its default).
        r = await test_client.get(
            "/api/v1/auth/widget-layout", headers=_auth(token)
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"surface": "visitors", "layout": None}

        # Save a custom order, read it back.
        r = await test_client.put(
            "/api/v1/auth/widget-layout",
            headers=_auth(token),
            json={"surface": "visitors", "layout": ["funnel", "browser"]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["layout"] == ["funnel", "browser"]

        r = await test_client.get(
            "/api/v1/auth/widget-layout", headers=_auth(token)
        )
        assert r.json()["layout"] == ["funnel", "browser"]

    @pytest.mark.asyncio
    async def test_surfaces_are_isolated(self, test_client, test_db):
        token = await _signup(test_client, f"wl-{uuidlib.uuid4().hex[:8]}@test.com")
        await test_client.put(
            "/api/v1/auth/widget-layout",
            headers=_auth(token),
            json={"surface": "visitors", "layout": ["funnel"]},
        )
        # Writing a different surface must not clobber 'visitors'.
        await test_client.put(
            "/api/v1/auth/widget-layout",
            headers=_auth(token),
            json={"surface": "overview", "layout": ["a", "b"]},
        )
        r = await test_client.get(
            "/api/v1/auth/widget-layout?surface=visitors", headers=_auth(token)
        )
        assert r.json()["layout"] == ["funnel"]

    @pytest.mark.asyncio
    async def test_requires_auth(self, test_client):
        r = await test_client.get("/api/v1/auth/widget-layout")
        assert r.status_code in (401, 403)
