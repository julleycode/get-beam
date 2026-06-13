"""Blog CMS endpoint tests (`/api/v1/blog`).

Integration: requires local PostgreSQL (docker-compose) via conftest fixtures.
Admin auth is bypassed by overriding `require_admin` — the endpoints don't tie
records to the admin user, so a transient User is sufficient.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient

from apps.api.dependencies import require_admin
from apps.api.main import app
from apps.api.models.user import User


@pytest_asyncio.fixture
async def admin_client(test_client: AsyncClient) -> AsyncClient:
    """test_client plus an admin identity for require_admin-gated routes."""
    app.dependency_overrides[require_admin] = lambda: User(
        id=uuid.uuid4(), email="admin@getbeam.fyi", is_admin=True
    )
    yield test_client
    app.dependency_overrides.pop(require_admin, None)


async def _create(client: AsyncClient, **overrides) -> dict:
    payload = {"title": "Hello World", "body_markdown": "word " * 400}
    payload.update(overrides)
    resp = await client.post("/api/v1/blog/posts", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_create_draft_then_publish_flow(admin_client: AsyncClient) -> None:
    created = await _create(admin_client, title="Draft Then Publish")
    assert created["status"] == "draft"
    assert created["slug"] == "draft-then-publish"
    assert created["reading_time_minutes"] >= 1
    # meta fallbacks resolved on write
    assert created["meta_title"] == "Draft Then Publish"
    post_id = created["id"]

    # Draft is hidden from the public list + slug lookup.
    public = (await admin_client.get("/api/v1/blog/posts")).json()
    assert all(p["slug"] != "draft-then-publish" for p in public["posts"])
    assert (await admin_client.get("/api/v1/blog/posts/draft-then-publish")).status_code == 404

    # Publish.
    pub = await admin_client.post(f"/api/v1/blog/posts/{post_id}/publish")
    assert pub.status_code == 200
    first_published_at = pub.json()["published_at"]
    assert first_published_at is not None

    # Now visible publicly.
    public = (await admin_client.get("/api/v1/blog/posts")).json()
    assert any(p["slug"] == "draft-then-publish" for p in public["posts"])
    assert (await admin_client.get("/api/v1/blog/posts/draft-then-publish")).status_code == 200

    # Re-publish must NOT move published_at.
    await admin_client.post(f"/api/v1/blog/posts/{post_id}/unpublish")
    again = await admin_client.post(f"/api/v1/blog/posts/{post_id}/publish")
    assert again.json()["published_at"] == first_published_at


@pytest.mark.asyncio
async def test_slug_uniqueness(admin_client: AsyncClient) -> None:
    a = await _create(admin_client, title="Same Title")
    b = await _create(admin_client, title="Same Title")
    assert a["slug"] == "same-title"
    assert b["slug"] == "same-title-2"


@pytest.mark.asyncio
async def test_update_recomputes_reading_time_and_meta(admin_client: AsyncClient) -> None:
    created = await _create(admin_client, title="Editable", body_markdown="short")
    post_id = created["id"]
    resp = await admin_client.put(
        f"/api/v1/blog/posts/{post_id}",
        json={"body_markdown": "word " * 1000, "meta_description": "Custom desc"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["reading_time_minutes"] >= 4
    assert body["meta_description"] == "Custom desc"


@pytest.mark.asyncio
async def test_unpublish_removes_from_public(admin_client: AsyncClient) -> None:
    created = await _create(admin_client, title="Toggle Me")
    post_id = created["id"]
    await admin_client.post(f"/api/v1/blog/posts/{post_id}/publish")
    await admin_client.post(f"/api/v1/blog/posts/{post_id}/unpublish")
    assert (await admin_client.get("/api/v1/blog/posts/toggle-me")).status_code == 404


@pytest.mark.asyncio
async def test_delete_post(admin_client: AsyncClient) -> None:
    created = await _create(admin_client, title="Delete Me")
    post_id = created["id"]
    resp = await admin_client.delete(f"/api/v1/blog/posts/{post_id}")
    assert resp.status_code == 204
    # Publishing a deleted post now 404s.
    assert (await admin_client.post(f"/api/v1/blog/posts/{post_id}/publish")).status_code == 404


@pytest.mark.asyncio
async def test_admin_write_requires_auth(test_client: AsyncClient) -> None:
    """No override here → require_admin runs → no token → 401."""
    resp = await test_client.post(
        "/api/v1/blog/posts", json={"title": "Nope", "body_markdown": "x"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_unknown_slug_404(test_client: AsyncClient) -> None:
    assert (await test_client.get("/api/v1/blog/posts/nonexistent")).status_code == 404
