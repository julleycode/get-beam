"""Integration tests for the unresolvable-visitor revive pass.

Requires: PostgreSQL running locally.

An `identity_status='unresolvable'` visitor used to be dead forever (the sweep
only picks `anonymous` rows). The aggregation rollup now re-queues such a visitor
when their stored IP changes — the exact case created by the Cloudflare-edge-IP
backlog, where the IP we tried was junk and the real one only arrives on the
visitor's next visit.
"""

import pytest
import pytest_asyncio
from datetime import datetime, timedelta

pytestmark = pytest.mark.integration

SITE_ID = "test_site_revive"
VISITOR_ID = "test_visitor_revive"
CF_EDGE_IP = "172.68.10.20"  # Cloudflare edge — the junk we used to store


@pytest_asyncio.fixture
async def revive_fixture(test_db):
    """Seed a site + an unresolvable visitor with a CF-edge IP and 2 resolution logs."""
    from sqlalchemy import select, text

    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import ResolutionLog, Visitor

    result = await test_db.execute(select(User).where(User.email == "test-revive@test.com"))
    user = result.scalar_one_or_none()
    if not user:
        user = User(email="test-revive@test.com", full_name="Revive User")
        test_db.add(user)
        await test_db.flush()

    result = await test_db.execute(select(Site).where(Site.site_id == SITE_ID))
    if not result.scalar_one_or_none():
        test_db.add(Site(site_id=SITE_ID, user_id=user.id, name="Revive Site", url="https://revive.test"))
        await test_db.flush()

    now = datetime.utcnow()
    test_db.add(Visitor(
        site_id=SITE_ID,
        visitor_id=VISITOR_ID,
        identity_status="unresolvable",
        ip_address=CF_EDGE_IP,
        first_seen=now - timedelta(days=10),
        last_seen=now - timedelta(days=10),
    ))
    test_db.add(ResolutionLog(site_id=SITE_ID, visitor_id=VISITOR_ID, provider="rb2b", success=False, cost_usd=0.0))
    test_db.add(ResolutionLog(site_id=SITE_ID, visitor_id=VISITOR_ID, provider="pdl", success=True, cost_usd=0.05))
    await test_db.commit()

    yield {"site_id": SITE_ID, "visitor_id": VISITOR_ID, "now": now}

    for table in ("events", "resolution_logs", "visitors"):
        await test_db.execute(text(f"DELETE FROM {table} WHERE site_id = :sid"), {"sid": SITE_ID})
    await test_db.commit()


async def _seed_event_and_aggregate(test_db, ip: str, now: datetime) -> None:
    from apps.api.models.event import Event
    from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

    test_db.add(Event(
        site_id=SITE_ID,
        visitor_id=VISITOR_ID,
        event_type="pageview",
        url="/",
        page_path="/",
        ip_address=ip,
        created_at=now - timedelta(minutes=1),
    ))
    await test_db.commit()
    await aggregate_visitors_for_site(test_db, SITE_ID)


async def _read_state(test_db):
    from sqlalchemy import select

    from apps.api.models.visitor import ResolutionLog, Visitor

    result = await test_db.execute(
        select(Visitor).where(Visitor.site_id == SITE_ID, Visitor.visitor_id == VISITOR_ID)
    )
    visitor = result.scalar_one()
    result = await test_db.execute(
        select(ResolutionLog.success).where(ResolutionLog.site_id == SITE_ID)
    )
    logs = sorted(row[0] for row in result.all())
    return visitor, logs


class TestUnresolvableRevive:
    @pytest.mark.asyncio
    async def test_new_ip_revives_and_purges_failed_logs(self, revive_fixture, test_db):
        """A DIFFERENT IP flips status back to anonymous and drops only failed logs."""
        await _seed_event_and_aggregate(test_db, "203.0.113.77", revive_fixture["now"])
        test_db.expire_all()

        visitor, logs = await _read_state(test_db)
        assert visitor.ip_address == "203.0.113.77"
        assert visitor.identity_status == "anonymous"
        # Only the success=True row survives.
        assert logs == [True]

    @pytest.mark.asyncio
    async def test_same_ip_leaves_visitor_unresolvable(self, revive_fixture, test_db):
        """The SAME IP is not a new provider query — nothing changes."""
        await _seed_event_and_aggregate(test_db, CF_EDGE_IP, revive_fixture["now"])
        test_db.expire_all()

        visitor, logs = await _read_state(test_db)
        assert visitor.ip_address == CF_EDGE_IP
        assert visitor.identity_status == "unresolvable"
        assert logs == [False, True]
