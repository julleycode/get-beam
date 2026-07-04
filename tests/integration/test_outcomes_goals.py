"""Integration tests for conversion-goal CRUD (/api/v1/outcomes/{site}/goals).

Requires: PostgreSQL running locally (via docker-compose).
"""

import uuid as uuidlib

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Goal Tester"},
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
async def goal_setup(test_client, test_db):
    from sqlalchemy import select
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"goals-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"goal_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="Goal Site", url="https://g.example.com"))
    await test_db.commit()
    return {"token": token, "site_id": site_id}


class TestGoalCrud:
    @pytest.mark.asyncio
    async def test_create_defaults_and_list(self, test_client, goal_setup):
        sid, token = goal_setup["site_id"], goal_setup["token"]

        resp = await test_client.post(
            f"/api/v1/outcomes/{sid}/goals",
            headers=_auth(token),
            json={"name": "Signup", "match_type": "prefix", "pattern": "/Welcome/"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["enabled"] is True
        assert body["repeatable"] is False
        assert body["goal_type"] == "url_match"
        # Pattern normalized: lowercased, trailing slash stripped.
        assert body["pattern"] == "/welcome"

        resp = await test_client.get(f"/api/v1/outcomes/{sid}/goals", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_duplicate_name_409(self, test_client, goal_setup):
        sid, token = goal_setup["site_id"], goal_setup["token"]
        payload = {"name": "Purchase", "match_type": "contains", "pattern": "order-complete"}
        assert (
            await test_client.post(f"/api/v1/outcomes/{sid}/goals", headers=_auth(token), json=payload)
        ).status_code == 200
        # Same name, different case — still a duplicate.
        payload["name"] = "purchase"
        resp = await test_client.post(f"/api/v1/outcomes/{sid}/goals", headers=_auth(token), json=payload)
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_invalid_inputs_422(self, test_client, goal_setup):
        sid, token = goal_setup["site_id"], goal_setup["token"]

        # Unknown match_type
        resp = await test_client.post(
            f"/api/v1/outcomes/{sid}/goals",
            headers=_auth(token),
            json={"name": "Bad", "match_type": "regex", "pattern": "/x"},
        )
        assert resp.status_code == 422

        # exact must start with /
        resp = await test_client.post(
            f"/api/v1/outcomes/{sid}/goals",
            headers=_auth(token),
            json={"name": "Bad2", "match_type": "exact", "pattern": "thanks"},
        )
        assert resp.status_code == 422

        # contains too short
        resp = await test_client.post(
            f"/api/v1/outcomes/{sid}/goals",
            headers=_auth(token),
            json={"name": "Bad3", "match_type": "contains", "pattern": "ab"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_goal_limit_400(self, test_client, goal_setup):
        from apps.api.services.conversion_tracker import MAX_GOALS_PER_SITE

        sid, token = goal_setup["site_id"], goal_setup["token"]
        for i in range(MAX_GOALS_PER_SITE):
            resp = await test_client.post(
                f"/api/v1/outcomes/{sid}/goals",
                headers=_auth(token),
                json={"name": f"Goal {i}", "match_type": "exact", "pattern": f"/g{i}"},
            )
            assert resp.status_code == 200, resp.text
        resp = await test_client.post(
            f"/api/v1/outcomes/{sid}/goals",
            headers=_auth(token),
            json={"name": "One too many", "match_type": "exact", "pattern": "/over"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_patch_and_revalidation(self, test_client, goal_setup):
        sid, token = goal_setup["site_id"], goal_setup["token"]
        created = (
            await test_client.post(
                f"/api/v1/outcomes/{sid}/goals",
                headers=_auth(token),
                json={"name": "Demo", "match_type": "contains", "pattern": "thanks"},
            )
        ).json()
        gid = created["id"]

        resp = await test_client.patch(
            f"/api/v1/outcomes/{sid}/goals/{gid}",
            headers=_auth(token),
            json={"enabled": False, "value_cents": 4900},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["enabled"] is False
        assert resp.json()["value_cents"] == 4900

        # Switching to exact while the stored pattern lacks a leading slash → 422.
        resp = await test_client.patch(
            f"/api/v1/outcomes/{sid}/goals/{gid}",
            headers=_auth(token),
            json={"match_type": "exact"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_delete(self, test_client, goal_setup):
        sid, token = goal_setup["site_id"], goal_setup["token"]
        created = (
            await test_client.post(
                f"/api/v1/outcomes/{sid}/goals",
                headers=_auth(token),
                json={"name": "Gone", "match_type": "exact", "pattern": "/bye"},
            )
        ).json()
        resp = await test_client.delete(
            f"/api/v1/outcomes/{sid}/goals/{created['id']}", headers=_auth(token)
        )
        assert resp.status_code == 204
        resp = await test_client.get(f"/api/v1/outcomes/{sid}/goals", headers=_auth(token))
        assert resp.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_foreign_user_404(self, test_client, goal_setup):
        sid = goal_setup["site_id"]
        other_token = await _signup(test_client, f"other-{uuidlib.uuid4().hex[:8]}@test.com")
        resp = await test_client.get(f"/api/v1/outcomes/{sid}/goals", headers=_auth(other_token))
        assert resp.status_code == 404
        resp = await test_client.post(
            f"/api/v1/outcomes/{sid}/goals",
            headers=_auth(other_token),
            json={"name": "Nope", "match_type": "exact", "pattern": "/x"},
        )
        assert resp.status_code == 404
