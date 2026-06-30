"""Changelog endpoint tests (`/api/v1/changelog`).

Integration: requires local PostgreSQL (docker-compose) via conftest fixtures.
Admin auth is bypassed by overriding `require_admin`.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient

from apps.api.dependencies import require_admin
from apps.api.main import app
from apps.api.models.user import User

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def admin_client(test_client: AsyncClient) -> AsyncClient:
    """test_client plus an admin identity for require_admin-gated routes."""
    app.dependency_overrides[require_admin] = lambda: User(
        id=uuid.uuid4(), email="admin@getbeam.fyi", is_admin=True
    )
    yield test_client
    app.dependency_overrides.pop(require_admin, None)


async def _create(client: AsyncClient, **overrides) -> dict:
    payload = {"title": "Shipped a thing", "body": "A short note.", "category": "new"}
    payload.update(overrides)
    resp = await client.post("/api/v1/changelog/entries", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_create_draft_hidden_then_publish(admin_client: AsyncClient) -> None:
    created = await _create(admin_client, title="Draft Then Publish")
    assert created["status"] == "draft"
    assert created["published_at"] is None
    entry_id = created["id"]

    # Draft is hidden from the public list.
    public = (await admin_client.get("/api/v1/changelog/entries")).json()
    assert all(e["id"] != entry_id for e in public["entries"])

    # Publish stamps published_at and reveals it publicly.
    pub = await admin_client.post(f"/api/v1/changelog/entries/{entry_id}/publish")
    assert pub.status_code == 200
    first_published_at = pub.json()["published_at"]
    assert first_published_at is not None

    public = (await admin_client.get("/api/v1/changelog/entries")).json()
    assert any(e["id"] == entry_id for e in public["entries"])

    # Re-publish must NOT move published_at.
    await admin_client.post(f"/api/v1/changelog/entries/{entry_id}/unpublish")
    again = await admin_client.post(f"/api/v1/changelog/entries/{entry_id}/publish")
    assert again.json()["published_at"] == first_published_at


@pytest.mark.asyncio
async def test_unpublish_removes_from_public(admin_client: AsyncClient) -> None:
    created = await _create(admin_client, title="Toggle Me")
    entry_id = created["id"]
    await admin_client.post(f"/api/v1/changelog/entries/{entry_id}/publish")
    await admin_client.post(f"/api/v1/changelog/entries/{entry_id}/unpublish")
    public = (await admin_client.get("/api/v1/changelog/entries")).json()
    assert all(e["id"] != entry_id for e in public["entries"])


@pytest.mark.asyncio
async def test_public_list_newest_first(admin_client: AsyncClient) -> None:
    a = await _create(admin_client, title="Older")
    b = await _create(admin_client, title="Newer")
    await admin_client.post(f"/api/v1/changelog/entries/{a['id']}/publish")
    await admin_client.post(f"/api/v1/changelog/entries/{b['id']}/publish")
    entries = (await admin_client.get("/api/v1/changelog/entries")).json()["entries"]
    ids = [e["id"] for e in entries]
    # b was published after a → appears first.
    assert ids.index(b["id"]) < ids.index(a["id"])


@pytest.mark.asyncio
async def test_update_fields(admin_client: AsyncClient) -> None:
    created = await _create(admin_client, title="Editable", category="new")
    entry_id = created["id"]
    resp = await admin_client.put(
        f"/api/v1/changelog/entries/{entry_id}",
        json={"title": "Edited", "category": "fixed"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Edited"
    assert body["category"] == "fixed"


@pytest.mark.asyncio
async def test_delete_entry(admin_client: AsyncClient) -> None:
    created = await _create(admin_client, title="Delete Me")
    entry_id = created["id"]
    resp = await admin_client.delete(f"/api/v1/changelog/entries/{entry_id}")
    assert resp.status_code == 204
    assert (
        await admin_client.post(f"/api/v1/changelog/entries/{entry_id}/publish")
    ).status_code == 404


@pytest.mark.asyncio
async def test_invalid_category_rejected(admin_client: AsyncClient) -> None:
    resp = await admin_client.post(
        "/api/v1/changelog/entries", json={"title": "Bad", "category": "wizardry"}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_admin_list_returns_all_statuses(admin_client: AsyncClient) -> None:
    await _create(admin_client, title="Admin List Draft")
    published = await _create(admin_client, title="Admin List Published")
    await admin_client.post(f"/api/v1/changelog/entries/{published['id']}/publish")

    body = (await admin_client.get("/api/v1/changelog/admin/entries")).json()
    by_id = {e["id"]: e["status"] for e in body["entries"]}
    assert by_id.get(published["id"]) == "published"
    assert body["total"] >= 2


@pytest.mark.asyncio
async def test_admin_write_requires_auth(test_client: AsyncClient) -> None:
    """No override → require_admin runs → no token → 401."""
    resp = await test_client.post(
        "/api/v1/changelog/entries", json={"title": "Nope"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_list_requires_auth(test_client: AsyncClient) -> None:
    assert (
        await test_client.get("/api/v1/changelog/admin/entries")
    ).status_code == 401
