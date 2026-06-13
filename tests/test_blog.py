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


@pytest.mark.asyncio
async def test_admin_list_returns_all_statuses(admin_client: AsyncClient) -> None:
    await _create(admin_client, title="Admin List Draft")
    published = await _create(admin_client, title="Admin List Published")
    await admin_client.post(f"/api/v1/blog/posts/{published['id']}/publish")

    resp = await admin_client.get("/api/v1/blog/admin/posts")
    assert resp.status_code == 200
    body = resp.json()
    by_slug = {p["slug"]: p["status"] for p in body["posts"]}
    assert by_slug.get("admin-list-draft") == "draft"
    assert by_slug.get("admin-list-published") == "published"
    assert body["total"] >= 2


@pytest.mark.asyncio
async def test_admin_list_requires_auth(test_client: AsyncClient) -> None:
    """No override → require_admin runs → no token → 401."""
    assert (await test_client.get("/api/v1/blog/admin/posts")).status_code == 401


@pytest.mark.asyncio
async def test_public_list_filters_by_tag(admin_client: AsyncClient) -> None:
    a = (
        await admin_client.post(
            "/api/v1/blog/posts", json={"title": "Tagged Alpha", "tags": ["seo", "alpha"]}
        )
    ).json()
    b = (
        await admin_client.post(
            "/api/v1/blog/posts", json={"title": "Tagged Beta", "tags": ["seo", "beta"]}
        )
    ).json()
    await admin_client.post(f"/api/v1/blog/posts/{a['id']}/publish")
    await admin_client.post(f"/api/v1/blog/posts/{b['id']}/publish")

    seo = (await admin_client.get("/api/v1/blog/posts?tag=seo")).json()
    seo_slugs = {p["slug"] for p in seo["posts"]}
    assert {"tagged-alpha", "tagged-beta"} <= seo_slugs

    alpha = (await admin_client.get("/api/v1/blog/posts?tag=alpha")).json()
    alpha_slugs = {p["slug"] for p in alpha["posts"]}
    assert "tagged-alpha" in alpha_slugs
    assert "tagged-beta" not in alpha_slugs


@pytest.mark.asyncio
async def test_schedule_publishes_when_due(admin_client: AsyncClient, test_db) -> None:
    from datetime import datetime, timedelta, timezone

    from apps.api.services import blog_service

    created = await _create(admin_client, title="Scheduled Soon")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    resp = await admin_client.post(
        f"/api/v1/blog/posts/{created['id']}/schedule", json={"scheduled_for": past}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "scheduled"
    # Not public while scheduled.
    assert (await admin_client.get("/api/v1/blog/posts/scheduled-soon")).status_code == 404

    published = await blog_service.publish_due_posts(test_db)
    assert published >= 1
    # Now live.
    assert (await admin_client.get("/api/v1/blog/posts/scheduled-soon")).status_code == 200


@pytest.mark.asyncio
async def test_schedule_future_stays_scheduled(admin_client: AsyncClient, test_db) -> None:
    from datetime import datetime, timedelta, timezone

    from apps.api.services import blog_service

    created = await _create(admin_client, title="Scheduled Future")
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    await admin_client.post(
        f"/api/v1/blog/posts/{created['id']}/schedule", json={"scheduled_for": future}
    )
    await blog_service.publish_due_posts(test_db)
    # Future schedule → not published, not public.
    assert (await admin_client.get("/api/v1/blog/posts/scheduled-future")).status_code == 404


@pytest.mark.asyncio
async def test_schedule_requires_auth(test_client: AsyncClient) -> None:
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = await test_client.post(
        f"/api/v1/blog/posts/{fake_id}/schedule",
        json={"scheduled_for": "2030-01-01T00:00:00Z"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_upload_image_mock(admin_client: AsyncClient) -> None:
    """No service-role key in test env → mock mode returns a public URL."""
    resp = await admin_client.post(
        "/api/v1/blog/upload",
        files={"file": ("photo.png", b"\x89PNG\r\n fake", "image/png")},
    )
    assert resp.status_code == 200, resp.text
    url = resp.json()["url"]
    assert "blog-images" in url and url.endswith(".png")


@pytest.mark.asyncio
async def test_upload_rejects_non_image(admin_client: AsyncClient) -> None:
    resp = await admin_client.post(
        "/api/v1/blog/upload",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_requires_auth(test_client: AsyncClient) -> None:
    resp = await test_client.post(
        "/api/v1/blog/upload",
        files={"file": ("photo.png", b"data", "image/png")},
    )
    assert resp.status_code == 401
