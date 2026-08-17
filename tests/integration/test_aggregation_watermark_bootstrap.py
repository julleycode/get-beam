"""F6/F9/F2 — watermark bootstrap, sweep does not stamp, future event.ts.

Docker-gated: needs PostgreSQL + Redis. Flag ON + NULL watermark must full-run
then stamp inside ``_background_aggregate``; the repair sweep must not stamp.
A client ``ts`` one year in the future must not inflate pageviews on the
second incremental run because ingest stores ``created_at = datetime.utcnow()``.
"""

import json
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.jobs import scheduler
from apps.api.models.event import Event
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.models.visitor import Visitor
from apps.api.routers import events as events_router
from apps.api.services import aggregation_debounce as dbnc

pytestmark = pytest.mark.integration

SITE_ID = "test_site_wm_bootstrap"
SITE_EMPTY = "test_site_wm_empty"
_BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"


@pytest.fixture(autouse=True)
def no_dispatched_resolution(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.visitor_aggregator._dispatch_company_resolution",
        lambda site_id: None,
    )

    async def _noop(db, site_id):
        return None

    monkeypatch.setattr(
        "apps.api.services.visitor_aggregator._resolve_companies", _noop
    )


@pytest.fixture(autouse=True)
async def clean_keys():
    from apps.api.services import redis_client

    redis_client._client = None
    redis = redis_client.get_redis()
    keys = (
        dbnc.debounce_key(SITE_ID),
        dbnc.sweep_pending_key(SITE_ID),
        dbnc.debounce_key(SITE_EMPTY),
        dbnc.sweep_pending_key(SITE_EMPTY),
    )
    for key in keys:
        await redis.delete(key)
    yield
    for key in keys:
        await redis.delete(key)
    await redis.aclose()
    redis_client._client = None


@pytest.fixture
def use_test_sessions(test_engine, monkeypatch):
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(events_router, "async_session", factory)
    monkeypatch.setattr(scheduler, "async_session", factory)
    return factory


@pytest_asyncio.fixture
async def site(test_db):
    result = await test_db.execute(
        select(User).where(User.email == "test-wm-boot@test.com")
    )
    user = result.scalar_one_or_none()
    if not user:
        user = User(email="test-wm-boot@test.com", full_name="WmBoot")
        test_db.add(user)
        await test_db.flush()

    result = await test_db.execute(select(Site).where(Site.site_id == SITE_ID))
    if not result.scalar_one_or_none():
        test_db.add(
            Site(
                site_id=SITE_ID,
                user_id=user.id,
                name="WmBoot",
                url="https://wmboot.test",
            )
        )
        await test_db.flush()
    await test_db.commit()

    yield SITE_ID

    for table in ("events", "visitors"):
        await test_db.execute(
            text(f"DELETE FROM {table} WHERE site_id = :sid"), {"sid": SITE_ID}
        )
    await test_db.execute(
        text("UPDATE sites SET last_aggregated_at = NULL WHERE site_id = :sid"),
        {"sid": SITE_ID},
    )
    await test_db.commit()


async def _add_event(db, visitor_id, ts, url="/", **kw):
    db.add(
        Event(
            site_id=SITE_ID,
            visitor_id=visitor_id,
            event_type="pageview",
            url=url,
            page_path=url,
            created_at=ts,
            **kw,
        )
    )
    await db.commit()


async def _watermark(db, site_id=SITE_ID):
    db.expire_all()
    result = await db.execute(
        select(Site.last_aggregated_at).where(Site.site_id == site_id)
    )
    return result.scalar_one()


async def _pageviews(db, visitor_id):
    db.expire_all()
    result = await db.execute(
        select(Visitor).where(
            Visitor.site_id == SITE_ID, Visitor.visitor_id == visitor_id
        )
    )
    row = result.scalar_one()
    return row.total_pageviews


class TestBackgroundAggregateStampsFullBootstrap:
    @pytest.mark.asyncio
    async def test_flag_on_null_watermark_full_run_then_stamps(
        self, test_db, site, use_test_sessions, monkeypatch
    ):
        monkeypatch.setattr(
            "apps.api.config.settings.aggregation_incremental_enabled",
            True,
            raising=False,
        )
        vid = "v_boot"
        await _add_event(test_db, vid, datetime.utcnow() - timedelta(minutes=5))
        assert await _watermark(test_db) is None

        await events_router._background_aggregate(site)

        wm = await _watermark(test_db)
        assert wm is not None
        assert await _pageviews(test_db, vid) == 1


class TestSweepDoesNotStamp:
    @pytest.mark.asyncio
    async def test_sweep_full_recompute_leaves_null_watermark(
        self, test_db, site, use_test_sessions, monkeypatch
    ):
        monkeypatch.setattr(
            "apps.api.config.settings.aggregation_incremental_enabled",
            True,
            raising=False,
        )
        await _add_event(
            test_db, "v_sweep", datetime.utcnow() - timedelta(minutes=5)
        )
        assert await _watermark(test_db) is None

        outcome, count = await scheduler._sweep_one_site(site, allow_defer=True)

        assert outcome == "ran"
        assert count >= 1
        assert await _watermark(test_db) is None


class TestFleetBootstrap:
    @pytest.mark.asyncio
    async def test_f9_stamps_sites_with_events_only(
        self, test_db, site, use_test_sessions, monkeypatch
    ):
        monkeypatch.setattr(
            "apps.api.config.settings.aggregation_incremental_enabled",
            False,
            raising=False,
        )
        result = await test_db.execute(
            select(User).where(User.email == "test-wm-boot@test.com")
        )
        user = result.scalar_one()
        empty = await test_db.execute(
            select(Site).where(Site.site_id == SITE_EMPTY)
        )
        if not empty.scalar_one_or_none():
            test_db.add(
                Site(
                    site_id=SITE_EMPTY,
                    user_id=user.id,
                    name="Empty",
                    url="https://empty.test",
                )
            )
            await test_db.commit()

        await _add_event(
            test_db, "v_f9", datetime.utcnow() - timedelta(minutes=3)
        )
        assert await _watermark(test_db, SITE_ID) is None
        assert await _watermark(test_db, SITE_EMPTY) is None

        summary = await scheduler.run_aggregation_watermark_bootstrap()

        assert summary["aggregated"] >= 1
        assert await _watermark(test_db, SITE_ID) is not None
        assert await _watermark(test_db, SITE_EMPTY) is None

        await test_db.execute(
            text("DELETE FROM sites WHERE site_id = :sid"), {"sid": SITE_EMPTY}
        )
        await test_db.commit()


class TestFutureEventTs:
    @pytest.mark.asyncio
    async def test_future_ts_does_not_inflate_pageviews_on_second_incremental(
        self, test_client, test_db, site, use_test_sessions, monkeypatch
    ):
        monkeypatch.setattr(
            "apps.api.config.settings.aggregation_incremental_enabled",
            True,
            raising=False,
        )

        real_bg = events_router._background_aggregate

        async def _skip(_sid: str) -> None:
            return None

        monkeypatch.setattr(events_router, "_background_aggregate", _skip)

        future = datetime.utcnow() + timedelta(days=365)
        payload = {
            "site_id": site,
            "visitor_id": "v_future_ts",
            "events": [
                {
                    "type": "pageview",
                    "url": "https://wmboot.test/",
                    "page_path": "/",
                    "user_agent": _BROWSER_UA,
                    "ts": future.isoformat() + "Z",
                    "event_id": "evt-future-ts-1",
                }
            ],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 204

        test_db.expire_all()
        result = await test_db.execute(
            select(Event).where(Event.event_id == "evt-future-ts-1")
        )
        row = result.scalar_one()
        now = datetime.utcnow()
        assert abs((row.created_at - now).total_seconds()) < 120
        assert row.created_at.year == now.year

        await real_bg(site)
        assert await _pageviews(test_db, "v_future_ts") == 1
        assert await _watermark(test_db) is not None

        await real_bg(site)
        assert await _pageviews(test_db, "v_future_ts") == 1
