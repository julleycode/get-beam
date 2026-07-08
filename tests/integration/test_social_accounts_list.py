"""Integration test for GET /api/v1/social/accounts/.

Pins the `has_refresh_token` flag the UI uses to decide connection health:
accounts with a refresh token auto-renew at send time (e.g. Twitter's 2h
tokens) and must NOT be flagged as expiring.

Requires: PostgreSQL running locally (via docker-compose).
"""

import uuid as uuidlib

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Accounts Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def test_list_accounts_reports_has_refresh_token(test_client, test_db):
    from apps.api.models.social_account import Platform, SocialAccount
    from apps.api.models.user import User

    email = f"accounts-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    refreshable = SocialAccount(
        id=uuidlib.uuid4(),
        user_id=user.id,
        platform=Platform.twitter,
        platform_user_id="pu-refreshable",
        username="acct_refreshable",
        access_token="enc-access",
        refresh_token="enc-refresh",
    )
    bare = SocialAccount(
        id=uuidlib.uuid4(),
        user_id=user.id,
        platform=Platform.linkedin,
        platform_user_id="pu-bare",
        username="acct_bare",
        access_token="enc-access",
        refresh_token=None,
    )
    test_db.add_all([refreshable, bare])
    await test_db.commit()

    resp = await test_client.get(
        "/api/v1/social/accounts/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    by_username = {a["username"]: a for a in resp.json()}

    assert by_username["acct_refreshable"]["has_refresh_token"] is True
    assert by_username["acct_bare"]["has_refresh_token"] is False
