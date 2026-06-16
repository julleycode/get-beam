"""Phase 01 (GDPR/CCPA) integration: GPC/DNT opt-out flows end to end.

Covers, against the test DB (requires local PostgreSQL via docker-compose):
- The aggregator BOOL_ORs events.optout into visitors.do_not_resolve.
- The flag is sticky: a later non-opt-out event does NOT clear it.
- run_resolution_for_site never loads opted-out visitors (the real WHERE
  filter), so they are never resolved.
"""

import uuid as uuidlib
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


def _pageview(site_id: str, visitor_id: str, when: datetime, optout: bool):
    from apps.api.models.event import Event

    return Event(
        event_id=uuidlib.uuid4().hex,
        site_id=site_id,
        visitor_id=visitor_id,
        event_type="pageview",
        url="https://example.com/pricing",
        created_at=when,
        optout=optout,
    )


class TestAggregatorSetsOptout:
    @pytest.mark.asyncio
    async def test_optout_event_marks_visitor(self, test_db):
        from apps.api.models.visitor import Visitor
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

        site_id = f"opt_{uuidlib.uuid4().hex[:8]}"
        vid = f"v_{uuidlib.uuid4().hex[:8]}"
        now = datetime.utcnow()
        test_db.add(_pageview(site_id, vid, now - timedelta(minutes=2), optout=False))
        test_db.add(_pageview(site_id, vid, now, optout=True))
        await test_db.commit()

        await aggregate_visitors_for_site(test_db, site_id)

        visitor = (
            await test_db.execute(
                select(Visitor).where(Visitor.site_id == site_id, Visitor.visitor_id == vid)
            )
        ).scalar_one()
        assert visitor.do_not_resolve is True

    @pytest.mark.asyncio
    async def test_no_optout_event_leaves_flag_false(self, test_db):
        from apps.api.models.visitor import Visitor
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

        site_id = f"opt_{uuidlib.uuid4().hex[:8]}"
        vid = f"v_{uuidlib.uuid4().hex[:8]}"
        now = datetime.utcnow()
        test_db.add(_pageview(site_id, vid, now, optout=False))
        await test_db.commit()

        await aggregate_visitors_for_site(test_db, site_id)

        visitor = (
            await test_db.execute(
                select(Visitor).where(Visitor.site_id == site_id, Visitor.visitor_id == vid)
            )
        ).scalar_one()
        assert visitor.do_not_resolve is False

    @pytest.mark.asyncio
    async def test_flag_is_sticky_across_reaggregation(self, test_db):
        from apps.api.models.visitor import Visitor
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

        site_id = f"opt_{uuidlib.uuid4().hex[:8]}"
        vid = f"v_{uuidlib.uuid4().hex[:8]}"
        now = datetime.utcnow()
        test_db.add(_pageview(site_id, vid, now, optout=True))
        await test_db.commit()
        await aggregate_visitors_for_site(test_db, site_id)

        # A later, non-opt-out visit must NOT clear the opt-out.
        test_db.add(_pageview(site_id, vid, now + timedelta(hours=1), optout=False))
        await test_db.commit()
        await aggregate_visitors_for_site(test_db, site_id)

        visitor = (
            await test_db.execute(
                select(Visitor).where(Visitor.site_id == site_id, Visitor.visitor_id == vid)
            )
        ).scalar_one()
        assert visitor.do_not_resolve is True


class TestSweepSkipsOptout:
    @pytest.mark.asyncio
    async def test_opted_out_visitor_never_resolved(self, test_db, monkeypatch):
        from apps.api.models.site import Site
        from apps.api.models.user import User
        from apps.api.models.visitor import Visitor
        from apps.api.services import resolution_runner
        from apps.api.services.identity_resolver import IdentityResolver

        user = User(email=f"sweep-{uuidlib.uuid4().hex[:8]}@test.com", full_name="Sweep")
        test_db.add(user)
        await test_db.flush()

        site_id = f"site_{uuidlib.uuid4().hex[:8]}"
        site = Site(site_id=site_id, user_id=user.id, name="S", url="https://s.example.com")
        test_db.add(site)

        now = datetime.utcnow()
        normal_vid = f"v_ok_{uuidlib.uuid4().hex[:8]}"
        optout_vid = f"v_no_{uuidlib.uuid4().hex[:8]}"
        for vid, flag in ((normal_vid, False), (optout_vid, True)):
            test_db.add(Visitor(
                site_id=site_id, visitor_id=vid,
                first_seen=now, last_seen=now,
                intent_score=80.0, identity_status="anonymous",
                ip_address="203.0.113.10", do_not_resolve=flag,
            ))
        await test_db.commit()

        resolved_with: list[str] = []

        async def fake_resolve(self, visitor):
            resolved_with.append(visitor.visitor_id)
            return None  # no identification → no enrich/increment

        monkeypatch.setattr(IdentityResolver, "resolve", fake_resolve)

        await resolution_runner.run_resolution_for_site(test_db, site, max_resolve=20)

        assert normal_vid in resolved_with
        assert optout_vid not in resolved_with
