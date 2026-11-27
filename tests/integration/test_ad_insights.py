"""G4 — ad-insights-seo-aeo against real Postgres + Redis, FLAG ON.

Flag-OFF-only evidence is vacuous (E4): every ON-path test turns
``ad_insights_enabled`` ON and asserts rows were actually written. Mock provider
+ mock Gemini only (E3) — no live Meta/Google/Gemini calls.
"""

import uuid as uuidlib
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration


async def _new_site(db, prefix="ai"):
    from apps.api.models.site import Site
    from apps.api.models.user import User

    user = User(email=f"{prefix}-{uuidlib.uuid4().hex[:8]}@test.com", hashed_password="x", full_name="AI")
    db.add(user)
    await db.flush()
    site_id = f"{prefix}_{uuidlib.uuid4().hex[:8]}"
    db.add(Site(site_id=site_id, user_id=user.id, name="AI", url="https://ai.example.com"))
    await db.flush()
    return user, site_id


@pytest_asyncio.fixture
async def ins(test_db, test_engine, monkeypatch):
    from apps.api.config import settings
    from apps.api.models.ad_connection import AdConnection
    from apps.api.services import redis_client

    monkeypatch.setattr(settings, "mock_external_apis", True)
    monkeypatch.setattr(settings, "ad_insights_enabled", True)

    user, site_id = await _new_site(test_db)
    for p in ("meta", "google"):
        test_db.add(AdConnection(site_id=site_id, user_id=user.id, provider=p, auth_type="oauth", status="connected"))
    # linkedin has no reporting support -> never ingested
    test_db.add(AdConnection(site_id=site_id, user_id=user.id, provider="linkedin", auth_type="oauth", status="connected"))
    other_user, other_site = await _new_site(test_db, "aix")
    test_db.add(AdConnection(site_id=other_site, user_id=other_user.id, provider="meta", auth_type="oauth", status="error"))
    await test_db.commit()

    # Fresh Redis client per test loop; clear the refresh markers.
    redis_client._client = None
    r = redis_client.get_redis()
    await r.delete(f"ad_insights:refresh:{site_id}", f"ad_insights:refresh:{other_site}")

    import apps.api.routers.ad_insights as router_mod

    monkeypatch.setattr(
        router_mod, "async_session", async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    )
    yield {"user": user, "site_id": site_id, "other_user": other_user, "other_site": other_site}
    try:
        await r.delete(f"ad_insights:refresh:{site_id}", f"ad_insights:refresh:{other_site}")
        await r.aclose()
    finally:
        redis_client._client = None


async def _count(db, table, site_id, extra=""):
    return (await db.execute(text(f"SELECT count(*) FROM {table} WHERE site_id=:s {extra}"), {"s": site_id})).scalar_one()


async def test_flag_on_ingest_idempotent_rank_suggest_once_per_day(test_db, ins):
    from apps.api.services.ad_insights_ingest import run_ad_insights_once

    site_id = ins["site_id"]
    stats = await run_ad_insights_once(test_db)
    assert stats["sites"] == 1, "only connected meta/google connections are ingested"
    assert await _count(test_db, "ad_performance_daily", site_id) == 10  # 8 meta + 2 google
    assert await _count(test_db, "ad_performance_daily", ins["other_site"]) == 0
    assert await _count(test_db, "content_opportunities", site_id) == 3

    stats2 = await run_ad_insights_once(test_db)
    assert await _count(test_db, "ad_performance_daily", site_id) == 10, "upsert must be idempotent"
    assert await _count(test_db, "content_opportunities", site_id) == 3, "<=1 generation per site per day"
    assert stats2["suggestions"] == 0

    status_set = (await test_db.execute(
        text("SELECT DISTINCT status FROM content_opportunities WHERE site_id=:s"), {"s": site_id}
    )).scalars().all()
    assert status_set == ["new"]


async def test_endpoints_tenant_scoping_and_status_patch(test_db, test_client, ins):
    from apps.api.dependencies import get_current_user
    from apps.api.main import app
    from apps.api.services.ad_insights_ingest import run_ad_insights_once

    site_id = ins["site_id"]
    await run_ad_insights_once(test_db)
    base = f"/api/v1/ad-insights/{site_id}"

    app.dependency_overrides[get_current_user] = lambda: ins["other_user"]
    try:
        assert (await test_client.get(f"{base}/top-ads")).status_code == 404
        assert (await test_client.get(f"{base}/opportunities")).status_code == 404
        assert (await test_client.post(f"{base}/refresh")).status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    app.dependency_overrides[get_current_user] = lambda: ins["user"]
    try:
        r = await test_client.get(f"{base}/top-ads")
        assert r.status_code == 200
        body = r.json()
        assert body["enough_data"] is True and len(body["ads"]) == 5
        assert "m-104" not in {a["platform_ad_id"] for a in body["ads"]}, "below floor"
        assert [a["rank"] for a in body["ads"]] == [1, 2, 3, 4, 5]

        r = await test_client.get(f"{base}/opportunities")
        assert r.status_code == 200
        opps = r.json()
        assert len(opps) == 3 and {o["kind"] for o in opps} == {"page_title", "faq", "llms_txt"}
        oid = opps[0]["id"]

        r = await test_client.patch(f"{base}/opportunities/{oid}", json={"status": "copied"})
        assert r.status_code == 200 and r.json()["status"] == "copied"
        r = await test_client.patch(f"{base}/opportunities/{oid}", json={"status": "published"})
        assert r.status_code == 422
        r = await test_client.patch(f"{base}/opportunities/{oid}", json={"title": "x", "status": "dismissed"})
        assert r.status_code == 200 and r.json()["title"] != "x"
        assert len((await test_client.get(f"{base}/opportunities")).json()) == 2  # dismissed hidden
        assert (await test_client.patch(f"{base}/opportunities/{uuidlib.uuid4()}", json={"status": "new"})).status_code == 404
        # opportunity id from another site through this site's path -> 404
        other_path = f"/api/v1/ad-insights/{ins['other_site']}/opportunities/{oid}"
        assert (await test_client.patch(other_path, json={"status": "new"})).status_code == 404

        # generated today already -> refresh is 429
        assert (await test_client.post(f"{base}/refresh")).status_code == 429
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_refresh_once_per_day_even_after_failed_generation(test_db, test_client, ins, monkeypatch):
    from apps.api.dependencies import get_current_user
    from apps.api.main import app
    from apps.api.services import content_opportunities as co

    site_id = ins["site_id"]
    monkeypatch.setattr(co, "_mock_response", lambda ads: {"opportunities": [{"kind": "bad"}]})
    app.dependency_overrides[get_current_user] = lambda: ins["user"]
    try:
        r = await test_client.post(f"/api/v1/ad-insights/{site_id}/refresh")
        assert r.status_code == 202
        # background ingest ran (flag ON path non-vacuous), generation failed -> 0 rows
        assert await _count(test_db, "ad_performance_daily", site_id) == 10
        assert await _count(test_db, "content_opportunities", site_id) == 0
        r = await test_client.post(f"/api/v1/ad-insights/{site_id}/refresh")
        assert r.status_code == 429, "a failed generation still consumes the day's attempt"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_refresh_redis_error_fails_closed(test_db, test_client, ins, monkeypatch):
    from apps.api.dependencies import get_current_user
    from apps.api.main import app
    from apps.api.services import redis_client

    class _Broken:
        async def set(self, *a, **k):
            raise ConnectionError("redis down")

    monkeypatch.setattr(redis_client, "get_redis", lambda: _Broken())
    app.dependency_overrides[get_current_user] = lambda: ins["user"]
    try:
        assert (await test_client.post(f"/api/v1/ad-insights/{ins['site_id']}/refresh")).status_code == 429
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_flag_off_routes_404_and_job_noop(test_db, test_client, ins, monkeypatch):
    from apps.api.config import settings
    from apps.api.dependencies import get_current_user
    from apps.api.jobs.scheduler import _ad_insights_job
    from apps.api.main import app
    from apps.api.services.ad_insights_ingest import run_ad_insights_once

    monkeypatch.setattr(settings, "ad_insights_enabled", False)
    site_id = ins["site_id"]
    stats = await run_ad_insights_once(test_db)
    await _ad_insights_job()
    assert stats["sites"] == 0
    assert await _count(test_db, "ad_performance_daily", site_id) == 0
    app.dependency_overrides[get_current_user] = lambda: ins["user"]
    try:
        for method, path in (
            ("get", "top-ads"), ("get", "opportunities"), ("post", "refresh"),
        ):
            r = await getattr(test_client, method)(f"/api/v1/ad-insights/{site_id}/{path}")
            assert r.status_code == 404
        r = await test_client.patch(f"/api/v1/ad-insights/{site_id}/opportunities/{uuidlib.uuid4()}", json={"status": "new"})
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_site_delete_removes_both_tables(test_db, test_client, ins):
    from apps.api.dependencies import get_current_user
    from apps.api.main import app
    from apps.api.services.ad_insights_ingest import run_ad_insights_once

    site_id = ins["site_id"]
    await run_ad_insights_once(test_db)
    assert await _count(test_db, "ad_performance_daily", site_id) == 10  # non-vacuous
    assert await _count(test_db, "content_opportunities", site_id) == 3
    app.dependency_overrides[get_current_user] = lambda: ins["user"]
    try:
        r = await test_client.delete(f"/api/v1/sites/{site_id}")
        assert r.status_code == 204
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert await _count(test_db, "ad_performance_daily", site_id) == 0
    assert await _count(test_db, "content_opportunities", site_id) == 0


async def test_failed_connection_is_isolated_and_status_rechecked(test_db, ins, monkeypatch):
    """N-2: a refresh failure flips status to error -> that connection is skipped."""
    from apps.api.models.ad_connection import AdConnection
    from apps.api.services import ads_push
    from apps.api.services.ad_insights_ingest import ingest_site

    async def _fail_refresh(db, conn):
        if conn.provider == "google":
            conn.status = "error"
        return ""

    monkeypatch.setattr(ads_push, "fresh_access_token", _fail_refresh)
    site_id = ins["site_id"]
    n = await ingest_site(test_db, site_id)
    assert n == 8, "meta ingested, google skipped after status re-check"
    rows = (await test_db.execute(
        select(AdConnection.provider).where(AdConnection.site_id == site_id)
    )).scalars().all()
    assert "google" in rows
