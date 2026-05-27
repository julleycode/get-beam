"""Tests for intent score calculation in visitor_aggregator."""

import pytest
from datetime import datetime, timezone, timedelta

from apps.api.services.visitor_aggregator import calculate_intent_score


class TestRecencyScoring:
    """Score should be higher for recent visitors."""

    def test_very_recent_visitor_gets_30_points(self):
        """Visitor seen within 24 hours → +30 points."""
        score = calculate_intent_score(
            last_seen=datetime.now(timezone.utc) - timedelta(hours=1),
            total_sessions=1,
            max_scroll_depth=0,
            avg_time_on_page=0,
            pages_visited=[],
        )
        assert score >= 30

    def test_three_day_old_visitor_gets_20_points(self):
        """Visitor seen 2 days ago → +20 points."""
        score = calculate_intent_score(
            last_seen=datetime.now(timezone.utc) - timedelta(days=2),
            total_sessions=1,
            max_scroll_depth=0,
            avg_time_on_page=0,
            pages_visited=[],
        )
        assert score >= 20
        assert score < 30

    def test_week_old_visitor_gets_10_points(self):
        """Visitor seen 5 days ago → +10 points."""
        score = calculate_intent_score(
            last_seen=datetime.now(timezone.utc) - timedelta(days=5),
            total_sessions=1,
            max_scroll_depth=0,
            avg_time_on_page=0,
            pages_visited=[],
        )
        assert score >= 10
        assert score < 20

    def test_old_visitor_gets_zero_recency(self):
        """Visitor seen 2 weeks ago → +0 recency."""
        score = calculate_intent_score(
            last_seen=datetime.now(timezone.utc) - timedelta(days=14),
            total_sessions=1,
            max_scroll_depth=0,
            avg_time_on_page=0,
            pages_visited=[],
        )
        assert score == 0


class TestSessionScoring:
    """Multiple sessions = higher intent."""

    def test_three_sessions_gets_25_points(self):
        score = calculate_intent_score(
            last_seen=datetime.now(timezone.utc) - timedelta(days=14),  # no recency
            total_sessions=3,
            max_scroll_depth=0,
            avg_time_on_page=0,
            pages_visited=[],
        )
        assert score == 25

    def test_two_sessions_gets_15_points(self):
        score = calculate_intent_score(
            last_seen=datetime.now(timezone.utc) - timedelta(days=14),
            total_sessions=2,
            max_scroll_depth=0,
            avg_time_on_page=0,
            pages_visited=[],
        )
        assert score == 15


class TestHighIntentPages:
    """Visiting pricing/checkout/demo pages = high intent."""

    @pytest.mark.parametrize("page", [
        "https://example.com/pricing",
        "https://example.com/checkout",
        "https://example.com/signup",
        "https://example.com/demo",
        "https://example.com/contact",
        "https://example.com/plans",
    ])
    def test_high_intent_page_adds_20_points(self, page: str):
        score = calculate_intent_score(
            last_seen=datetime.now(timezone.utc) - timedelta(days=14),
            total_sessions=1,
            max_scroll_depth=0,
            avg_time_on_page=0,
            pages_visited=[page],
        )
        assert score == 20


class TestMaxScore:
    """Score should cap at 100."""

    def test_score_caps_at_100(self):
        score = calculate_intent_score(
            last_seen=datetime.now(timezone.utc),  # +30
            total_sessions=5,  # +25
            max_scroll_depth=100,  # +15
            avg_time_on_page=120,  # +10
            pages_visited=["https://example.com/pricing"],  # +20
        )
        assert score == 100


class TestEdgeCases:
    """Edge cases that shouldn't crash."""

    def test_empty_pages_list(self):
        score = calculate_intent_score(
            last_seen=datetime.now(timezone.utc),
            total_sessions=1,
            max_scroll_depth=0,
            avg_time_on_page=0,
            pages_visited=[],
        )
        assert isinstance(score, float)

    def test_naive_datetime(self):
        """Should handle naive datetimes without crashing."""
        score = calculate_intent_score(
            last_seen=datetime.utcnow(),
            total_sessions=1,
            max_scroll_depth=0,
            avg_time_on_page=0,
            pages_visited=[],
        )
        assert isinstance(score, float)
