"""Integration tests for visitor aggregation with session detection.

Requires: PostgreSQL running locally.
Tests verify that the window-function-based session counting works correctly.
"""

import pytest
import pytest_asyncio
from datetime import datetime, timedelta
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def seeded_events(test_db):
    """Seed test events for aggregation testing.

    Creates events that span multiple sessions:
    - Session 1: 3 pageviews within 5 minutes
    - Session 2: 2 pageviews 2 hours later
    """
    from sqlalchemy import text

    site_id = "test_site_aggregation"
    visitor_id = "test_visitor_sessions"

    # Ensure test user exists
    await test_db.execute(text("""
        INSERT INTO users (id, email, password_hash, full_name)
        VALUES (gen_random_uuid(), 'test-aggregation@test.com', 'fakehash', 'Test User')
        ON CONFLICT (email) DO NOTHING
    """))

    # Ensure test site exists
    await test_db.execute(text("""
        INSERT INTO sites (id, site_id, user_id, name, url)
        VALUES (gen_random_uuid(), :site_id, (SELECT id FROM users LIMIT 1), 'Test Site', 'https://test.com')
        ON CONFLICT (site_id) DO NOTHING
    """), {"site_id": site_id})

    # Clean previous test data
    await test_db.execute(text(
        "DELETE FROM events WHERE site_id = :site_id AND visitor_id = :vid"
    ), {"site_id": site_id, "vid": visitor_id})
    await test_db.execute(text(
        "DELETE FROM visitors WHERE site_id = :site_id AND visitor_id = :vid"
    ), {"site_id": site_id, "vid": visitor_id})

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
        await test_db.execute(text("""
            INSERT INTO events (site_id, visitor_id, event_type, url, ip_address, created_at, page_path)
            VALUES (:site_id, :vid, 'pageview', :url, :ip, :ts, :url)
        """), {"site_id": site_id, "vid": visitor_id, "url": url, "ip": ip, "ts": ts})

    await test_db.commit()

    yield {"site_id": site_id, "visitor_id": visitor_id}

    # Cleanup
    await test_db.execute(text(
        "DELETE FROM events WHERE site_id = :site_id AND visitor_id = :vid"
    ), {"site_id": site_id, "vid": visitor_id})
    await test_db.execute(text(
        "DELETE FROM visitors WHERE site_id = :site_id AND visitor_id = :vid"
    ), {"site_id": site_id, "vid": visitor_id})
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
