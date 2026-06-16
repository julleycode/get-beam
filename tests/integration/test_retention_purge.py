"""Phase 04 (GDPR/CCPA) integration: retention purge of raw events.

Against the test DB (requires local PostgreSQL via docker-compose):
- Events older than the window are deleted; recent events are kept.
- dry_run counts without deleting.
- A second run is a no-op (idempotent).

purge_events_older_than opens its own sessions via the app's async_session,
which targets the same test database as the test_db fixture, so committed rows
are visible across both.
"""

import uuid as uuidlib
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def patched_retention(test_engine):
    """Point retention.async_session at the test engine (current event loop).

    The service opens its own sessions via the app's module-level async_session,
    which is bound to a different engine/loop in tests. Mirror conftest's
    approach and swap in a factory on test_engine so purge runs on this loop.
    """
    from apps.api.services import retention

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    original = retention.async_session
    retention.async_session = factory
    yield retention
    retention.async_session = original


def _event(site_id: str, vid: str, when: datetime):
    from apps.api.models.event import Event

    return Event(
        event_id=uuidlib.uuid4().hex,
        site_id=site_id,
        visitor_id=vid,
        event_type="pageview",
        url="https://example.com/",
        created_at=when,
    )


async def _count(db, site_id: str) -> int:
    from apps.api.models.event import Event

    return (
        await db.execute(
            select(func.count()).select_from(Event).where(Event.site_id == site_id)
        )
    ).scalar() or 0


class TestRetentionPurge:
    @pytest.mark.asyncio
    async def test_purges_old_keeps_recent(self, test_db, patched_retention):
        site_id = f"ret_{uuidlib.uuid4().hex[:8]}"
        vid = f"v_{uuidlib.uuid4().hex[:8]}"
        now = datetime.utcnow()
        test_db.add(_event(site_id, vid, now - timedelta(days=100)))  # old
        test_db.add(_event(site_id, vid, now - timedelta(days=100)))  # old
        test_db.add(_event(site_id, vid, now - timedelta(days=10)))   # recent
        await test_db.commit()

        result = await patched_retention.purge_events_older_than(days=90)
        assert result["status"] == "ok"
        assert result["deleted"] >= 2

        await test_db.commit()  # start a fresh read txn
        assert await _count(test_db, site_id) == 1  # only the recent event remains

    @pytest.mark.asyncio
    async def test_dry_run_deletes_nothing(self, test_db, patched_retention):
        site_id = f"ret_{uuidlib.uuid4().hex[:8]}"
        vid = f"v_{uuidlib.uuid4().hex[:8]}"
        now = datetime.utcnow()
        test_db.add(_event(site_id, vid, now - timedelta(days=200)))
        await test_db.commit()

        result = await patched_retention.purge_events_older_than(days=90, dry_run=True)
        assert result["status"] == "dry_run"
        assert result["would_delete"] >= 1

        await test_db.commit()
        assert await _count(test_db, site_id) == 1  # nothing deleted

    @pytest.mark.asyncio
    async def test_second_run_is_noop(self, test_db, patched_retention):
        site_id = f"ret_{uuidlib.uuid4().hex[:8]}"
        vid = f"v_{uuidlib.uuid4().hex[:8]}"
        now = datetime.utcnow()
        test_db.add(_event(site_id, vid, now - timedelta(days=120)))
        await test_db.commit()

        first = await patched_retention.purge_events_older_than(days=90)
        assert first["deleted"] >= 1
        await patched_retention.purge_events_older_than(days=90)
        await test_db.commit()
        assert await _count(test_db, site_id) == 0
