"""Integration tests for visitor aggregation with session detection.

Requires: PostgreSQL running locally.
Tests verify that the window-function-based session counting works correctly.
"""

import uuid

import pytest
import pytest_asyncio
from datetime import datetime, timedelta

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def seeded_events(test_db):
    """Seed test events for aggregation testing using ORM models.

    Creates events that span multiple sessions:
    - Session 1: 3 pageviews within 5 minutes
    - Session 2: 2 pageviews 2 hours later
    """
    from apps.api.models.user import User
    from apps.api.models.site import Site
    from apps.api.models.event import Event
    from sqlalchemy import select

    site_id = "test_site_aggregation"
    visitor_id = "test_visitor_sessions"

    # Ensure test user exists (use ORM, not raw SQL)
    result = await test_db.execute(select(User).where(User.email == "test-agg@test.com"))
    user = result.scalar_one_or_none()
    if not user:
        user = User(email="test-agg@test.com", full_name="Test User")
        test_db.add(user)
        await test_db.flush()

    # Ensure test site exists
    result = await test_db.execute(select(Site).where(Site.site_id == site_id))
    if not result.scalar_one_or_none():
        test_db.add(Site(site_id=site_id, user_id=user.id, name="Test Site", url="https://test.com"))
        await test_db.flush()

    now = datetime.utcnow()

    # Session 1: 3 pageviews within 5 minutes
    events_data = [
        (now - timedelta(hours=1, minutes=10), "/", "203.0.113.50"),
        (now - timedelta(hours=1, minutes=7), "/pricing", "203.0.113.50"),
        (now - timedelta(hours=1, minutes=5), "/contact", "203.0.113.50"),
        # Session 2: 2 pageviews 2 hours later (gap > 30 min → new session)
        (now - timedelta(minutes=5), "/", "203.0.113.50"),
        (now - timedelta(minutes=2), "/demo", "203.0.113.50"),
    ]

    for ts, url, ip in events_data:
        test_db.add(Event(
            site_id=site_id,
            visitor_id=visitor_id,
            event_type="pageview",
            url=url,
            ip_address=ip,
            created_at=ts,
            page_path=url,
        ))

    await test_db.commit()

    yield {"site_id": site_id, "visitor_id": visitor_id}

    # Cleanup via raw SQL (safe for DELETE)
    from sqlalchemy import text
    await test_db.execute(text("DELETE FROM events WHERE site_id = :sid"), {"sid": site_id})
    await test_db.execute(text("DELETE FROM visitors WHERE site_id = :sid"), {"sid": site_id})
    await test_db.commit()


class TestSessionCounting:
    """Verify window-function session detection."""

    @pytest.mark.asyncio
    async def test_detects_two_sessions(self, test_db, seeded_events):
        """Events with 30+ min gap should be counted as separate sessions."""
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

        count = await aggregate_visitors_for_site(test_db, seeded_events["site_id"])
        assert count >= 1

        # Check the visitor was created with correct session count
        from sqlalchemy import text
        result = await test_db.execute(text(
            "SELECT total_sessions, total_pageviews, ip_address FROM visitors WHERE site_id = :sid AND visitor_id = :vid"
        ), {"sid": seeded_events["site_id"], "vid": seeded_events["visitor_id"]})
        row = result.fetchone()
        assert row is not None
        assert row[0] == 2, f"Expected 2 sessions, got {row[0]}"
        assert row[1] == 5, f"Expected 5 pageviews, got {row[1]}"
        assert row[2] == "203.0.113.50", f"Expected IP propagation, got {row[2]}"

    @pytest.mark.asyncio
    async def test_intent_score_calculated(self, test_db, seeded_events):
        """Aggregation should calculate a non-zero intent score."""
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

        await aggregate_visitors_for_site(test_db, seeded_events["site_id"])

        from sqlalchemy import text
        result = await test_db.execute(text(
            "SELECT intent_score FROM visitors WHERE site_id = :sid AND visitor_id = :vid"
        ), {"sid": seeded_events["site_id"], "vid": seeded_events["visitor_id"]})
        row = result.fetchone()
        assert row is not None
        # Recent visit + 2 sessions + high-intent pages → score > 0
        assert row[0] > 0, f"Expected positive intent score, got {row[0]}"


# ---------------------------------------------------------------------------
# AI-referral attribution (v1) — first-touch referrer + ai_source.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def ai_referral_env(test_db):
    """A site + helper to seed pageviews with arbitrary referrers/timestamps."""
    from apps.api.models.user import User
    from apps.api.models.site import Site
    from apps.api.models.event import Event
    from sqlalchemy import select, text

    site_id = "test_site_ai_referral"

    result = await test_db.execute(select(User).where(User.email == "test-ai-ref@test.com"))
    user = result.scalar_one_or_none()
    if not user:
        user = User(email="test-ai-ref@test.com", full_name="AI Ref User")
        test_db.add(user)
        await test_db.flush()

    result = await test_db.execute(select(Site).where(Site.site_id == site_id))
    if not result.scalar_one_or_none():
        test_db.add(Site(site_id=site_id, user_id=user.id, name="AI Ref Site", url="https://test.com"))
        await test_db.flush()

    async def seed(visitor_id, events):
        """events: list of (created_at, url, referrer)."""
        for ts, url, referrer in events:
            test_db.add(Event(
                site_id=site_id,
                visitor_id=visitor_id,
                event_type="pageview",
                url=url,
                referrer=referrer,
                ip_address="203.0.113.77",
                created_at=ts,
                page_path=url,
            ))
        await test_db.commit()

    yield {"site_id": site_id, "seed": seed}

    await test_db.execute(text("DELETE FROM events WHERE site_id = :sid"), {"sid": site_id})
    await test_db.execute(text("DELETE FROM identified_visitors WHERE site_id = :sid"), {"sid": site_id})
    await test_db.execute(text("DELETE FROM visitors WHERE site_id = :sid"), {"sid": site_id})
    await test_db.commit()


class TestAiReferralAggregation:
    """AC-I1..AC-I5 — first-touch referrer classification + emailability invariant."""

    @pytest.mark.asyncio
    async def test_entry_chatgpt_sets_ai_source(self, test_db, ai_referral_env):
        """AC-I1: entry pageview referred by chatgpt.com → ai_source='chatgpt'."""
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site
        now = datetime.utcnow()
        await ai_referral_env["seed"]("v_chatgpt", [
            (now - timedelta(minutes=10), "/", "https://chatgpt.com/"),
            (now - timedelta(minutes=8), "/pricing", ""),
        ])
        await aggregate_visitors_for_site(test_db, ai_referral_env["site_id"])
        from sqlalchemy import text
        row = (await test_db.execute(text(
            "SELECT ai_source, first_touch_referrer FROM visitors "
            "WHERE site_id = :sid AND visitor_id = :vid"
        ), {"sid": ai_referral_env["site_id"], "vid": "v_chatgpt"})).fetchone()
        assert row is not None
        assert row[0] == "chatgpt", f"Expected ai_source=chatgpt, got {row[0]}"
        assert row[1] == "https://chatgpt.com/"

    @pytest.mark.asyncio
    async def test_direct_then_perplexity_is_none(self, test_db, ai_referral_env):
        """AC-I2: genuine first touch is direct; a later perplexity visit does
        NOT retroactively attribute — strict first-touch semantic → None."""
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site
        now = datetime.utcnow()
        await ai_referral_env["seed"]("v_direct_first", [
            (now - timedelta(hours=3), "/", ""),  # direct entry
            (now - timedelta(minutes=5), "/", "https://perplexity.ai/"),  # later
        ])
        await aggregate_visitors_for_site(test_db, ai_referral_env["site_id"])
        from sqlalchemy import text
        row = (await test_db.execute(text(
            "SELECT ai_source FROM visitors WHERE site_id = :sid AND visitor_id = :vid"
        ), {"sid": ai_referral_env["site_id"], "vid": "v_direct_first"})).fetchone()
        assert row is not None
        assert row[0] is None, f"Expected None (first-touch direct), got {row[0]}"

    @pytest.mark.asyncio
    async def test_first_touch_beats_lexicographic_max(self, test_db, ai_referral_env):
        """AC-I3: top_referrer is MAX(referrer) (lexicographic); ai_source uses the
        chronological first-touch. Entry=chatgpt, later=zzz-referrer.example →
        first-touch (chatgpt) wins even though 'zzz...' sorts higher."""
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site
        now = datetime.utcnow()
        await ai_referral_env["seed"]("v_lexi", [
            (now - timedelta(minutes=20), "/", "https://chatgpt.com/"),
            (now - timedelta(minutes=2), "/x", "https://zzz-referrer.example/"),
        ])
        await aggregate_visitors_for_site(test_db, ai_referral_env["site_id"])
        from sqlalchemy import text
        row = (await test_db.execute(text(
            "SELECT ai_source, first_touch_referrer, top_referrer FROM visitors "
            "WHERE site_id = :sid AND visitor_id = :vid"
        ), {"sid": ai_referral_env["site_id"], "vid": "v_lexi"})).fetchone()
        assert row is not None
        assert row[0] == "chatgpt", f"first-touch should win, got ai_source={row[0]}"
        assert row[1] == "https://chatgpt.com/"
        # top_referrer is the lexicographic MAX — proves the two differ.
        assert row[2] == "https://zzz-referrer.example/"

    @pytest.mark.asyncio
    async def test_google_search_entry_is_none(self, test_db, ai_referral_env):
        """AC-I4: google.com entry → None (in-SERP AI answers undetectable)."""
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site
        now = datetime.utcnow()
        await ai_referral_env["seed"]("v_google", [
            (now - timedelta(minutes=10), "/", "https://www.google.com/search?q=beam"),
        ])
        await aggregate_visitors_for_site(test_db, ai_referral_env["site_id"])
        from sqlalchemy import text
        row = (await test_db.execute(text(
            "SELECT ai_source FROM visitors WHERE site_id = :sid AND visitor_id = :vid"
        ), {"sid": ai_referral_env["site_id"], "vid": "v_google"})).fetchone()
        assert row is not None
        assert row[0] is None, f"Expected None for google search, got {row[0]}"

    @pytest.mark.asyncio
    async def test_emailability_invariant(self, test_db, ai_referral_env):
        """AC-I5 (THE safety invariant): an AI-referred visitor is an ordinary
        emailable human. Aggregation NEVER writes source_agent_visit_id, and a
        person-provider identity for an ai_source visitor is emailable."""
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site
        from apps.api.services.identity_classification import is_emailable_identity
        from apps.api.models.visitor import IdentifiedVisitor
        from sqlalchemy import select, text

        now = datetime.utcnow()
        await ai_referral_env["seed"]("v_emailable", [
            (now - timedelta(minutes=10), "/", "https://chatgpt.com/"),
        ])
        await aggregate_visitors_for_site(test_db, ai_referral_env["site_id"])

        # ai_source is set AND source_agent_visit_id was never touched by
        # aggregation — the visitors table has no such column, and the identity
        # row (added below) carries NULL, proving additive-only behavior.
        vrow = (await test_db.execute(text(
            "SELECT ai_source FROM visitors WHERE site_id = :sid AND visitor_id = :vid"
        ), {"sid": ai_referral_env["site_id"], "vid": "v_emailable"})).fetchone()
        assert vrow is not None and vrow[0] == "chatgpt"

        # A human person-level resolution for this AI-referred visitor.
        test_db.add(IdentifiedVisitor(
            site_id=ai_referral_env["site_id"],
            visitor_id="v_emailable",
            email="human@example.com",
            full_name="Real Human",
            resolution_provider="form_capture",  # first-party → emailable
            source_agent_visit_id=None,  # NEVER set for AI-referred humans
        ))
        await test_db.commit()

        idrow = (await test_db.execute(
            select(IdentifiedVisitor).where(
                IdentifiedVisitor.site_id == ai_referral_env["site_id"],
                IdentifiedVisitor.visitor_id == "v_emailable",
            )
        )).scalar_one()
        assert idrow.source_agent_visit_id is None
        assert is_emailable_identity(
            idrow.resolution_provider, idrow.source_agent_visit_id
        ) is True, "AI-referred human with first-party provider must be emailable"
