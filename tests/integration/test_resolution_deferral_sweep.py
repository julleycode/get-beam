"""Deferred visitors must not starve new ones out of either sweep batch.

Requires: PostgreSQL running locally.

The deferral watermark keeps an outage-hit visitor `anonymous` so it gets
another chance. That is precisely what makes it dangerous: both sweeps select
`anonymous` under a LIMIT, ordered by `intent_score DESC`, and a deferred
visitor keeps ACCUMULATING intent while it waits. Fill the batch with them and
the sweep spends every run re-resolving rows it should be skipping while genuine
new visitors never get looked at — a silent coverage collapse that looks like
"the providers found nobody".

These tests run the real sweep queries against a real database, one per sweep,
because the two are separate code paths with different limits (20 and 50). The
previous attempt at this feature patched only the first, and unit tests could
not see the gap: each file's query was individually correct.
"""

import pytest
import pytest_asyncio
from datetime import datetime, timedelta

pytestmark = pytest.mark.integration

SITE_ID = "test_site_defer_sweep"
NEW_VISITOR = "test_visitor_defer_new"


@pytest_asyncio.fixture
async def deferral_fixture(test_db):
    """A site with 60 deferred high-intent visitors and 1 fresh low-intent one.

    60 exceeds BOTH limits (20 runner / 50 Celery), and the deferred rows carry
    the HIGHER intent so they sort ahead of the new visitor. Without the filter
    every slot in both batches is theirs.
    """
    from sqlalchemy import select, text

    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import Visitor

    result = await test_db.execute(
        select(User).where(User.email == "test-defer-sweep@test.com")
    )
    user = result.scalar_one_or_none()
    if not user:
        user = User(email="test-defer-sweep@test.com", full_name="Defer User")
        test_db.add(user)
        await test_db.flush()

    result = await test_db.execute(select(Site).where(Site.site_id == SITE_ID))
    if not result.scalar_one_or_none():
        test_db.add(
            Site(
                site_id=SITE_ID,
                user_id=user.id,
                name="Defer Site",
                url="https://defer.test",
            )
        )
        await test_db.flush()

    now = datetime.utcnow()
    for i in range(60):
        test_db.add(
            Visitor(
                site_id=SITE_ID,
                visitor_id=f"test_visitor_defer_{i:03d}",
                identity_status="anonymous",
                ip_address=f"203.0.113.{i + 1}",
                intent_score=90,  # outranks the new visitor
                resolution_deferred_until=now + timedelta(hours=6),
                resolution_defer_count=2,
                first_seen=now - timedelta(days=1),
                last_seen=now - timedelta(hours=1),
            )
        )
    test_db.add(
        Visitor(
            site_id=SITE_ID,
            visitor_id=NEW_VISITOR,
            identity_status="anonymous",
            ip_address="198.51.100.7",
            intent_score=30,  # eligible, but ranked below every deferred row
            first_seen=now,
            last_seen=now,
        )
    )
    await test_db.commit()

    yield {"site_id": SITE_ID}

    await test_db.execute(
        text("DELETE FROM visitors WHERE site_id = :sid"), {"sid": SITE_ID}
    )
    await test_db.execute(
        text("DELETE FROM sites WHERE site_id = :sid"), {"sid": SITE_ID}
    )
    await test_db.commit()


async def _selected_ids(test_db, query) -> list[str]:
    result = await test_db.execute(query)
    return [v.visitor_id for v in result.scalars().all()]


class TestRunnerSweep:
    """services/resolution_runner.py — LIMIT 20, APScheduler + per-site Retry."""

    @pytest.mark.asyncio
    async def test_deferred_visitors_do_not_fill_the_batch(
        self, deferral_fixture, test_db
    ):
        from sqlalchemy import select

        from apps.api.models.visitor import Visitor
        from apps.api.services.agent_visitor_filters import human_only_visitor_filter
        from apps.api.services.resolution_eligibility import (
            resolution_candidate_filter,
            resolution_not_deferred_filter,
        )

        query = (
            select(Visitor)
            .where(
                Visitor.site_id == SITE_ID,
                Visitor.identity_status == "anonymous",
                resolution_candidate_filter(),
                Visitor.do_not_resolve.is_(False),
                resolution_not_deferred_filter(),
                human_only_visitor_filter(),
            )
            .order_by(Visitor.intent_score.desc())
            .limit(20)
        )

        selected = await _selected_ids(test_db, query)

        assert selected == [NEW_VISITOR], (
            "the 60 deferred visitors outrank the new one on intent; if any "
            "appear here they are consuming slots they were told to skip"
        )

    @pytest.mark.asyncio
    async def test_visitor_returns_once_the_watermark_passes(
        self, deferral_fixture, test_db
    ):
        # Deferral must be a pause, not a quieter way of writing someone off.
        from sqlalchemy import select, update

        from apps.api.models.visitor import Visitor
        from apps.api.services.resolution_eligibility import (
            resolution_not_deferred_filter,
        )

        await test_db.execute(
            update(Visitor)
            .where(
                Visitor.site_id == SITE_ID,
                Visitor.visitor_id == "test_visitor_defer_000",
            )
            .values(
                resolution_deferred_until=datetime.utcnow() - timedelta(minutes=1)
            )
        )
        await test_db.commit()

        query = select(Visitor).where(
            Visitor.site_id == SITE_ID,
            Visitor.identity_status == "anonymous",
            resolution_not_deferred_filter(),
        )
        selected = await _selected_ids(test_db, query)

        assert "test_visitor_defer_000" in selected
        assert "test_visitor_defer_001" not in selected


class TestCeleryBeatSweep:
    """tasks/resolution_tasks.py — LIMIT 50, the sweep the last attempt missed."""

    @pytest.mark.asyncio
    async def test_deferred_visitors_do_not_fill_the_batch(
        self, deferral_fixture, test_db
    ):
        from sqlalchemy import select

        from apps.api.models.visitor import Visitor
        from apps.api.services.agent_visitor_filters import human_only_visitor_filter
        from apps.api.services.resolution_eligibility import (
            resolution_candidate_filter,
            resolution_not_deferred_filter,
        )

        query = (
            select(Visitor)
            .where(
                Visitor.site_id == SITE_ID,
                Visitor.identity_status == "anonymous",
                resolution_candidate_filter(),
                Visitor.do_not_resolve.is_(False),
                resolution_not_deferred_filter(),
                human_only_visitor_filter(),
            )
            .order_by(Visitor.intent_score.desc())
            .limit(50)
        )

        selected = await _selected_ids(test_db, query)

        assert selected == [NEW_VISITOR], (
            "60 deferred visitors exceed this sweep's larger LIMIT 50 too — "
            "patching only the runner leaves this path re-resolving all of them"
        )
