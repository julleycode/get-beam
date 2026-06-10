"""Integration tests for the community feature board (logged-in upvotes).

Requires: PostgreSQL + Redis running locally (via docker-compose).
"""

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str, password: str = "testpass123") -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "full_name": "Board Tester"},
    )
    if resp.status_code != 200:  # exists from a previous run
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def board_user(test_client):
    return await _signup(test_client, "board-user@test.com")


@pytest_asyncio.fixture
async def board_user2(test_client):
    return await _signup(test_client, "board-user2@test.com")


class TestFeatureBoard:
    @pytest.mark.asyncio
    async def test_board_requires_auth(self, test_client):
        resp = await test_client.get("/api/v1/feature-requests/board")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_submit_vote_toggle_and_redaction(
        self, test_client, board_user, board_user2
    ):
        # Logged-in submit: auto-upvoted by the submitter.
        created = await test_client.post(
            "/api/v1/feature-requests/board",
            json={"title": "Board test feature", "detail": "via test", "urgency": "useful"},
            headers=_auth(board_user),
        )
        assert created.status_code == 201, created.text
        item = created.json()
        assert item["votes"] == 1 and item["my_vote"] is True
        request_id = item["id"]
        # Redacted shape: never expose submitter email / admin notes.
        assert "email" not in item and "admin_note" not in item

        # Second user sees it on the board, unvoted for them.
        board = await test_client.get(
            "/api/v1/feature-requests/board", headers=_auth(board_user2)
        )
        assert board.status_code == 200
        rows = [i for i in board.json()["items"] if i["id"] == request_id]
        assert rows and rows[0]["votes"] == 1 and rows[0]["my_vote"] is False
        assert "email" not in rows[0] and "admin_note" not in rows[0]

        # Second user upvotes → 2; toggles off → 1.
        v1 = await test_client.post(
            f"/api/v1/feature-requests/{request_id}/vote", headers=_auth(board_user2)
        )
        assert v1.status_code == 200
        assert v1.json()["votes"] == 2 and v1.json()["my_vote"] is True

        v2 = await test_client.post(
            f"/api/v1/feature-requests/{request_id}/vote", headers=_auth(board_user2)
        )
        assert v2.status_code == 200
        assert v2.json()["votes"] == 1 and v2.json()["my_vote"] is False

    @pytest.mark.asyncio
    async def test_vote_unknown_request_404(self, test_client, board_user):
        resp = await test_client.post(
            "/api/v1/feature-requests/00000000-0000-4000-8000-000000000000/vote",
            headers=_auth(board_user),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_board_sorted_by_votes(self, test_client, board_user, board_user2):
        a = await test_client.post(
            "/api/v1/feature-requests/board",
            json={"title": "Less wanted feature"},
            headers=_auth(board_user),
        )
        b = await test_client.post(
            "/api/v1/feature-requests/board",
            json={"title": "Most wanted feature"},
            headers=_auth(board_user),
        )
        assert a.status_code == 201 and b.status_code == 201
        # Second user boosts B to 2 votes.
        boost = await test_client.post(
            f"/api/v1/feature-requests/{b.json()['id']}/vote", headers=_auth(board_user2)
        )
        assert boost.status_code == 200

        board = await test_client.get(
            "/api/v1/feature-requests/board", headers=_auth(board_user)
        )
        items = board.json()["items"]
        pos = {i["id"]: idx for idx, i in enumerate(items)}
        assert pos[b.json()["id"]] < pos[a.json()["id"]]
