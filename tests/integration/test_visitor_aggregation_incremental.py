"""Watermark-incremental aggregation — Phase 3 (W1) behaviour gates.

Docker-gated (needs PostgreSQL): ``aggregate_visitors_for_site`` is raw Postgres
SQL (LAG, ARRAY_AGG ... FILTER, BOOL_OR, on_conflict_do_update), so none of this
is assertable at unit tier — the same constraint documented at
``tests/integration/test_ingest_abuse_hardening.py`` and in the plan's Tier note.

Covers:
* AC2   — ``test_double_run_no_inflation``      (running twice over unchanged
          events leaves counters unchanged — the primary counter-inflation risk)
* AC4   — ``test_boundary_lookback_30min``      (30-minute LAG lookback keeps
          session boundaries correct at the window edge)
* AC-V1 — ``test_descoped_columns_untouched``   (D7: avg_time_on_page and
          intent_score are never written by an incremental run)
* AC-V3 — ``test_ai_source_follows_first_touch`` (E13: no false AI badge)
* AC-V4 — ``test_ip_address_keep_if_set``        (E14: a NULL window IP must not
          blank a stored IP)
"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from apps.api.models.event import Event
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.models.visitor import Visitor
from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

pytestmark = pytest.mark.integration

SITE_ID = "test_site_incremental"


@pytest.fixture(autouse=True)
def no_dispatched_resolution(monkeypatch):
    """Keep company resolution out of these tests — it is dispatched onto a
    background task with its own session and is covered elsewhere."""
    monkeypatch.setattr(
        "apps.api.services.visitor_aggregator._dispatch_company_resolution",
        lambda site_id: None,
    )

    async def _noop(db, site_id):
        return None

    monkeypatch.setattr(
        "apps.api.services.visitor_aggregator._resolve_companies", _noop
    )


@pytest_asyncio.fixture
async def site(test_db):
    result = await test_db.execute(select(User).where(User.email == "test-inc@test.com"))
    user = result.scalar_one_or_none()
    if not user:
        user = User(email="test-inc@test.com", full_name="Incremental")
        test_db.add(user)
        await test_db.flush()

    result = await test_db.execute(select(Site).where(Site.site_id == SITE_ID))
    if not result.scalar_one_or_none():
        test_db.add(
            Site(site_id=SITE_ID, user_id=user.id, name="Inc", url="https://inc.test")
        )
        await test_db.flush()
    await test_db.commit()

    yield SITE_ID

    for table in ("events", "visitors"):
        await test_db.execute(
            text(f"DELETE FROM {table} WHERE site_id = :sid"), {"sid": SITE_ID}
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


async def _visitor(db, visitor_id) -> Visitor:
    db.expire_all()
    result = await db.execute(
        select(Visitor).where(
            Visitor.site_id == SITE_ID, Visitor.visitor_id == visitor_id
        )
    )
    return result.scalar_one()


class TestDoubleRunNoInflation:
    """AC2 — the failure mode the full-recompute design existed to avoid."""

    @pytest.mark.asyncio
    async def test_double_run_no_inflation(self, test_db, site):
        vid = "v_double"
        base = datetime.utcnow() - timedelta(hours=3)
        for i in range(3):
            await _add_event(test_db, vid, base + timedelta(minutes=i))

        await aggregate_visitors_for_site(test_db, site)  # full recompute
        before = await _visitor(test_db, vid)
        pageviews, sessions = before.total_pageviews, before.total_sessions
        assert pageviews == 3

        watermark = datetime.utcnow()
        # No new events. Two consecutive incremental runs over an empty window.
        await aggregate_visitors_for_site(test_db, site, since=watermark)
        await aggregate_visitors_for_site(test_db, site, since=watermark)

        after = await _visitor(test_db, vid)
        assert after.total_pageviews == pageviews
        assert after.total_sessions == sessions

    @pytest.mark.asyncio
    async def test_incremental_adds_only_the_new_events(self, test_db, site):
        vid = "v_delta"
        base = datetime.utcnow() - timedelta(hours=3)
        for i in range(3):
            await _add_event(test_db, vid, base + timedelta(minutes=i))
        await aggregate_visitors_for_site(test_db, site)

        watermark = datetime.utcnow()
        # Two more pageviews, same session as each other, far after the old ones.
        await _add_event(test_db, vid, watermark + timedelta(seconds=1), url="/a")
        await _add_event(test_db, vid, watermark + timedelta(seconds=2), url="/b")

        await aggregate_visitors_for_site(test_db, site, since=watermark)

        v = await _visitor(test_db, vid)
        assert v.total_pageviews == 5
        assert set(v.pages_visited) == {"/", "/a", "/b"}


class TestBoundaryLookback:
    """AC4 — LAG must see one event before the window start."""

    @pytest.mark.asyncio
    async def test_boundary_lookback_30min(self, test_db, site):
        """An event 20 min before the watermark must NOT open a new session for
        the first in-window event (the gap is < 30 min, so it continues)."""
        vid = "v_boundary"
        watermark = datetime.utcnow() - timedelta(minutes=30)

        await _add_event(test_db, vid, watermark - timedelta(minutes=20))
        await aggregate_visitors_for_site(test_db, site)
        assert (await _visitor(test_db, vid)).total_sessions == 1

        # 5 min after the watermark → 25 min after the pre-window event (< 30),
        # so this continues the existing session and contributes a delta of 0.
        await _add_event(test_db, vid, watermark + timedelta(minutes=5), url="/x")
        await aggregate_visitors_for_site(test_db, site, since=watermark)

        v = await _visitor(test_db, vid)
        assert v.total_sessions == 1, "continuation event wrongly opened a session"
        assert v.total_pageviews == 2

    @pytest.mark.asyncio
    async def test_gap_beyond_lookback_does_open_a_new_session(self, test_db, site):
        vid = "v_boundary_gap"
        watermark = datetime.utcnow() - timedelta(hours=2)

        await _add_event(test_db, vid, watermark - timedelta(minutes=5))
        await aggregate_visitors_for_site(test_db, site)
        assert (await _visitor(test_db, vid)).total_sessions == 1

        # 90 minutes after the watermark — far outside the 30-min lookback.
        await _add_event(test_db, vid, watermark + timedelta(minutes=90), url="/y")
        await aggregate_visitors_for_site(test_db, site, since=watermark)

        assert (await _visitor(test_db, vid)).total_sessions == 2


class TestDescopedColumns:
    """AC-V1 / D7 — the incremental path never writes these two."""

    @pytest.mark.asyncio
    async def test_descoped_columns_untouched(self, test_db, site):
        vid = "v_descoped"
        base = datetime.utcnow() - timedelta(hours=4)
        for i in range(4):
            await _add_event(
                test_db, vid, base + timedelta(minutes=i), url=f"/p{i}", time_on_page=90
            )

        await aggregate_visitors_for_site(test_db, site)
        snap = await _visitor(test_db, vid)
        avg_before, intent_before = snap.avg_time_on_page, snap.intent_score
        assert avg_before > 0 and intent_before > 0

        watermark = datetime.utcnow()
        for i in range(3):
            await _add_event(
                test_db,
                vid,
                watermark + timedelta(seconds=i + 1),
                url=f"/new{i}",
                time_on_page=1,
            )

        await aggregate_visitors_for_site(test_db, site, since=watermark)
        after = await _visitor(test_db, vid)

        # DESCOPED — byte-identical to the snapshot.
        assert after.avg_time_on_page == avg_before
        assert after.intent_score == intent_before
        # MERGED — moved.
        assert after.total_pageviews == 7
        assert set(after.pages_visited) >= {"/p0", "/new0", "/new2"}

    @pytest.mark.asyncio
    async def test_the_repair_path_refreshes_them(self, test_db, site):
        """The full recompute is their sole writer — prove it actually is."""
        vid = "v_repair"
        base = datetime.utcnow() - timedelta(hours=4)
        await _add_event(test_db, vid, base, time_on_page=90)
        await aggregate_visitors_for_site(test_db, site)
        avg_before = (await _visitor(test_db, vid)).avg_time_on_page

        watermark = datetime.utcnow()
        await _add_event(
            test_db, vid, watermark + timedelta(seconds=1), url="/z", time_on_page=10
        )
        await aggregate_visitors_for_site(test_db, site, since=watermark)
        assert (await _visitor(test_db, vid)).avg_time_on_page == avg_before

        await aggregate_visitors_for_site(test_db, site, since=None)
        assert (await _visitor(test_db, vid)).avg_time_on_page == pytest.approx(50.0)


class TestFirstTouchAndAiSource:
    """AC-V3 / D6 / E13 — keep-existing-if-set, and no desync."""

    @pytest.mark.asyncio
    async def test_ai_source_follows_first_touch(self, test_db, site):
        vid = "v_ai"
        base = datetime.utcnow() - timedelta(hours=3)
        await _add_event(test_db, vid, base, referrer="https://www.google.com/")

        await aggregate_visitors_for_site(test_db, site)
        v = await _visitor(test_db, vid)
        assert v.first_touch_referrer == "https://www.google.com/"
        assert v.ai_source is None

        watermark = datetime.utcnow()
        await _add_event(
            test_db,
            vid,
            watermark + timedelta(seconds=1),
            url="/ai",
            referrer="https://chat.openai.com/",
        )
        await aggregate_visitors_for_site(test_db, site, since=watermark)

        after = await _visitor(test_db, vid)
        assert after.first_touch_referrer == "https://www.google.com/"
        assert after.ai_source is None, (
            "a naive symmetric COALESCE on ai_source stamps a false "
            "'Arrived via ChatGPT' badge onto a kept google.com first touch"
        )

    @pytest.mark.asyncio
    async def test_incremental_may_populate_a_null_first_touch(self, test_db, site):
        """Keep-existing-if-set is asymmetric: NULL may still be filled in."""
        vid = "v_ai_null"
        watermark = datetime.utcnow() - timedelta(minutes=5)
        await _add_event(test_db, vid, watermark - timedelta(minutes=1), referrer="")
        await aggregate_visitors_for_site(test_db, site)
        assert (await _visitor(test_db, vid)).first_touch_referrer is None

        await _add_event(
            test_db,
            vid,
            watermark + timedelta(seconds=1),
            url="/ai",
            referrer="https://chat.openai.com/",
        )
        await aggregate_visitors_for_site(test_db, site, since=watermark)

        after = await _visitor(test_db, vid)
        assert after.first_touch_referrer == "https://chat.openai.com/"
        assert after.ai_source is not None


class TestIpAddressKeepIfSet:
    """AC-V4 / E14 — the undocumented set_ column that must not be blanked."""

    @pytest.mark.asyncio
    async def test_ip_address_keep_if_set(self, test_db, site):
        vid = "v_ip"
        base = datetime.utcnow() - timedelta(hours=3)
        await _add_event(test_db, vid, base, ip_address="203.0.113.7")
        await aggregate_visitors_for_site(test_db, site)
        assert (await _visitor(test_db, vid)).ip_address == "203.0.113.7"

        watermark = datetime.utcnow()
        await _add_event(
            test_db, vid, watermark + timedelta(seconds=1), url="/noip", ip_address=""
        )
        await aggregate_visitors_for_site(test_db, site, since=watermark)

        assert (await _visitor(test_db, vid)).ip_address == "203.0.113.7"


class TestWatermarkAdvance:
    """Checklist item 9 — advance only after a successful commit."""

    @pytest.mark.asyncio
    async def test_incremental_run_stamps_the_watermark(self, test_db, site):
        vid = "v_wm"
        await _add_event(test_db, vid, datetime.utcnow() - timedelta(hours=1))
        await aggregate_visitors_for_site(test_db, site)

        result = await test_db.execute(
            select(Site.last_aggregated_at).where(Site.site_id == site)
        )
        assert result.scalar_one() is None, "full recompute must not stamp"

        await aggregate_visitors_for_site(
            test_db, site, since=datetime.utcnow() - timedelta(minutes=1)
        )

        test_db.expire_all()
        result = await test_db.execute(
            select(Site.last_aggregated_at).where(Site.site_id == site)
        )
        assert result.scalar_one() is not None
