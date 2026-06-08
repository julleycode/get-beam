"""Tests for intent score calculation v2 in visitor_aggregator."""

import pytest
from datetime import datetime, timezone, timedelta

from apps.api.services.visitor_aggregator import (
    calculate_intent_score,
    _classify_funnel_stages,
    _score_referrer,
    _decay_multiplier,
)

NOW = datetime.now(timezone.utc)


def _score(**overrides) -> float:
    defaults = dict(
        first_seen=NOW - timedelta(days=7),
        last_seen=NOW - timedelta(hours=1),
        total_sessions=1,
        max_scroll_depth=0,
        avg_time_on_page=0,
        pages_visited=[],
        top_referrer=None,
        utm_source=None,
        utm_medium=None,
    )
    defaults.update(overrides)
    return calculate_intent_score(**defaults)


class TestSessionScoring:

    def test_three_plus_sessions_higher_than_two(self):
        three = _score(total_sessions=3, last_seen=NOW - timedelta(hours=1))
        two = _score(total_sessions=2, last_seen=NOW - timedelta(hours=1))
        assert three > two

    def test_two_sessions_higher_than_one(self):
        two = _score(total_sessions=2, last_seen=NOW - timedelta(hours=1))
        one = _score(total_sessions=1, last_seen=NOW - timedelta(hours=1))
        assert two > one

    def test_session_points_magnitude(self):
        three = _score(
            total_sessions=3,
            first_seen=NOW - timedelta(days=60),
            last_seen=NOW - timedelta(hours=1),
        )
        one = _score(
            total_sessions=1,
            first_seen=NOW - timedelta(days=60),
            last_seen=NOW - timedelta(hours=1),
        )
        assert three - one == pytest.approx(25.0, abs=1.0)


class TestScrollAndTime:

    def test_deep_scroll_adds_15(self):
        base = _score(max_scroll_depth=50)
        high = _score(max_scroll_depth=80)
        assert high - base == pytest.approx(15.0, abs=0.1)

    def test_long_time_adds_10(self):
        base = _score(avg_time_on_page=30)
        long = _score(avg_time_on_page=90)
        assert long - base == pytest.approx(10.0, abs=0.1)


class TestVelocitySignal:

    def test_accelerating_visitor_gets_15(self):
        score = _score(
            first_seen=NOW - timedelta(days=2),
            last_seen=NOW - timedelta(hours=1),
            total_sessions=3,
        )
        slow = _score(
            first_seen=NOW - timedelta(days=30),
            last_seen=NOW - timedelta(hours=1),
            total_sessions=3,
        )
        assert score > slow

    def test_steady_visitor_gets_8(self):
        score = _score(
            first_seen=NOW - timedelta(days=12),
            last_seen=NOW - timedelta(hours=1),
            total_sessions=4,
        )
        no_vel = _score(
            first_seen=NOW - timedelta(days=60),
            last_seen=NOW - timedelta(hours=1),
            total_sessions=4,
        )
        assert score > no_vel

    def test_single_session_no_velocity(self):
        a = _score(total_sessions=1)
        b = _score(total_sessions=1, first_seen=NOW - timedelta(days=1))
        assert a == b


class TestFunnelProgression:

    def test_single_stage_zero_points(self):
        score = _score(pages_visited=["/blog/post-1"])
        no_pages = _score(pages_visited=[])
        assert score == no_pages

    def test_two_stages_adds_5(self):
        base = _score(pages_visited=[])
        two = _score(pages_visited=["/", "/features"])
        assert two - base == pytest.approx(5.0, abs=0.1)

    def test_three_stages_adds_10(self):
        base = _score(pages_visited=[])
        three = _score(pages_visited=["/", "/features", "/pricing"])
        assert three - base == pytest.approx(10.0, abs=0.1)

    def test_four_stages_adds_15(self):
        base = _score(pages_visited=[])
        four = _score(pages_visited=["/", "/features", "/pricing", "/signup"])
        assert four - base == pytest.approx(15.0, abs=0.1)


class TestClassifyFunnelStages:

    def test_homepage_is_stage_1(self):
        assert 1 in _classify_funnel_stages(["/"])
        assert 1 in _classify_funnel_stages(["https://example.com/"])
        assert 1 in _classify_funnel_stages(["https://example.com"])

    def test_pricing_is_stage_3(self):
        assert 3 in _classify_funnel_stages(["https://example.com/pricing"])

    def test_signup_is_stage_4(self):
        assert 4 in _classify_funnel_stages(["https://example.com/signup"])

    def test_empty_list(self):
        assert _classify_funnel_stages([]) == set()

    def test_unknown_page_no_stage(self):
        assert _classify_funnel_stages(["https://example.com/random-page"]) == set()


class TestReferrerScoring:

    def test_direct_traffic_gets_10(self):
        assert _score_referrer(None, None, None) == 10.0

    def test_organic_search_gets_10(self):
        assert _score_referrer("google.com", "google", None) == 10.0

    def test_email_gets_8(self):
        assert _score_referrer("mail.com", None, "email") == 8.0

    def test_social_via_medium_gets_3(self):
        assert _score_referrer(None, None, "social") == 3.0

    def test_social_via_referrer_gets_3(self):
        assert _score_referrer("twitter.com", None, None) == 3.0

    def test_paid_gets_3(self):
        assert _score_referrer(None, "google", "cpc") == 3.0

    def test_referral_gets_5(self):
        assert _score_referrer("somesite.com", None, None) == 5.0


class TestDecayMultiplier:

    def test_recent_no_decay(self):
        assert _decay_multiplier(NOW - timedelta(hours=2)) == 1.0

    def test_week_old_decays(self):
        assert _decay_multiplier(NOW - timedelta(days=3)) == 0.9

    def test_month_old_decays(self):
        assert _decay_multiplier(NOW - timedelta(days=15)) == 0.7

    def test_quarter_old_decays(self):
        assert _decay_multiplier(NOW - timedelta(days=60)) == 0.4

    def test_ancient_heavy_decay(self):
        assert _decay_multiplier(NOW - timedelta(days=180)) == 0.2


class TestScoreCap:

    def test_score_caps_at_100(self):
        score = _score(
            first_seen=NOW - timedelta(days=2),
            last_seen=NOW - timedelta(minutes=5),
            total_sessions=5,
            max_scroll_depth=100,
            avg_time_on_page=120,
            pages_visited=["/", "/features", "/pricing", "/signup"],
            top_referrer=None,
            utm_source=None,
            utm_medium=None,
        )
        assert score <= 100.0

    def test_max_signals_is_high(self):
        score = _score(
            first_seen=NOW - timedelta(days=2),
            last_seen=NOW - timedelta(minutes=5),
            total_sessions=5,
            max_scroll_depth=100,
            avg_time_on_page=120,
            pages_visited=["/", "/features", "/pricing", "/signup"],
            top_referrer=None,
            utm_source=None,
            utm_medium=None,
        )
        assert score >= 80.0


class TestEdgeCases:

    def test_empty_pages_list(self):
        score = _score(pages_visited=[])
        assert isinstance(score, float)

    def test_naive_datetime(self):
        score = calculate_intent_score(
            first_seen=datetime.utcnow() - timedelta(days=7),
            last_seen=datetime.utcnow(),
            total_sessions=1,
            max_scroll_depth=0,
            avg_time_on_page=0,
            pages_visited=[],
        )
        assert isinstance(score, float)

    def test_zero_sessions(self):
        score = _score(total_sessions=0)
        assert isinstance(score, float)

    def test_negative_scroll(self):
        score = _score(max_scroll_depth=-10)
        assert isinstance(score, float)


class TestManualVerification:
    """Plan requirement: sessions=3, scroll=80, time=90s, pricing+features, direct, seen 2h ago -> ~80+"""

    def test_high_intent_visitor_scores_high(self):
        score = calculate_intent_score(
            first_seen=NOW - timedelta(days=3),
            last_seen=NOW - timedelta(hours=2),
            total_sessions=3,
            max_scroll_depth=80,
            avg_time_on_page=90,
            pages_visited=["/", "/features", "/pricing"],
            top_referrer=None,
            utm_source=None,
            utm_medium=None,
        )
        assert score >= 75.0, f"Expected ~80+, got {score}"
