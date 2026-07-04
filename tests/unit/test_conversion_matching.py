"""Unit tests for conversion_tracker pure functions (no DB, no network)."""

import uuid
from datetime import datetime

from apps.api.services.conversion_tracker import (
    build_dedupe_key,
    matches_goal,
    normalize_path,
)


class TestNormalizePath:
    def test_full_url_reduced_to_path(self):
        assert normalize_path("https://site.com/thanks") == "/thanks"

    def test_query_fragment_case_trailing_slash_stripped(self):
        assert normalize_path("https://Site.com/Thanks/?q=1#frag") == "/thanks"

    def test_bare_path_with_query(self):
        assert normalize_path("/Checkout/Complete?order=9") == "/checkout/complete"

    def test_root_preserved(self):
        assert normalize_path("https://site.com/") == "/"
        assert normalize_path("/") == "/"

    def test_empty_and_none(self):
        assert normalize_path(None) == ""
        assert normalize_path("") == ""
        assert normalize_path("   ") == ""

    def test_missing_leading_slash_added(self):
        assert normalize_path("thanks") == "/thanks"

    def test_url_with_empty_path(self):
        assert normalize_path("https://site.com") == "/"


class TestMatchesGoal:
    def test_exact(self):
        assert matches_goal("/thanks", "exact", "/thanks") is True
        assert matches_goal("/thanks", "exact", "/thanks/you") is False

    def test_prefix(self):
        assert matches_goal("/checkout", "prefix", "/checkout/complete") is True
        assert matches_goal("/checkout", "prefix", "/cart/checkout") is False

    def test_contains(self):
        assert matches_goal("thank", "contains", "/say-thanks") is True
        assert matches_goal("thank", "contains", "/pricing") is False

    def test_empty_path_or_pattern_never_matches(self):
        assert matches_goal("/thanks", "exact", "") is False
        assert matches_goal("", "contains", "/thanks") is False

    def test_unknown_match_type(self):
        assert matches_goal("/thanks", "regex", "/thanks") is False


class TestBuildDedupeKey:
    def setup_method(self):
        self.goal_id = uuid.uuid4()
        self.vid = "visitor-abc"

    def test_non_repeatable_stable_across_days(self):
        k1 = build_dedupe_key(self.goal_id, False, self.vid, datetime(2026, 7, 1))
        k2 = build_dedupe_key(self.goal_id, False, self.vid, datetime(2026, 7, 2))
        assert k1 == k2 == f"{self.goal_id}:{self.vid}"

    def test_repeatable_url_match_day_bucketed(self):
        k1 = build_dedupe_key(self.goal_id, True, self.vid, datetime(2026, 7, 1, 9))
        k2 = build_dedupe_key(self.goal_id, True, self.vid, datetime(2026, 7, 1, 23))
        k3 = build_dedupe_key(self.goal_id, True, self.vid, datetime(2026, 7, 2, 0))
        assert k1 == k2
        assert k1 != k3
        assert k1.endswith(":20260701")

    def test_repeatable_event_id_exact_for_js_and_webhook(self):
        at = datetime(2026, 7, 1)
        k_js = build_dedupe_key(self.goal_id, True, self.vid, at, "evt-1", "js_event")
        k_wh = build_dedupe_key(self.goal_id, True, self.vid, at, "order-77", "webhook")
        assert k_js == f"{self.goal_id}:{self.vid}:evt-1"
        assert k_wh == f"{self.goal_id}:{self.vid}:order-77"

    def test_repeatable_url_match_ignores_event_id(self):
        # url_match replays share an event_id only per pageview; the daily
        # bucket is the policy regardless of the pixel's event ids.
        at = datetime(2026, 7, 1)
        k = build_dedupe_key(self.goal_id, True, self.vid, at, "evt-1", "url_match")
        assert k.endswith(":20260701")

    def test_max_key_length_fits_column(self):
        long_vid = "v" * 100
        long_event = "e" * 64
        key = build_dedupe_key(self.goal_id, True, long_vid, datetime(2026, 7, 1), long_event, "webhook")
        assert len(key) <= 250
