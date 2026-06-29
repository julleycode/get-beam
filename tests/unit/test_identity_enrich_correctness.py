"""Phase 8: identity-resolution + enrichment correctness.

- a no-timestamp identity-graph record must NOT match on IP equality alone
  (office/CGNAT IPs are shared — that attached the wrong person).
- enrichment cascade must never clobber a populated field with a null/missing
  value from a partial provider response.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from apps.api.services import enricher
from apps.api.services.identity_resolver import IdentityResolver


def _visitor(last_seen: datetime) -> SimpleNamespace:
    return SimpleNamespace(visitor_id="vis_test_0001", last_seen=last_seen, ip_address="203.0.113.7")


class TestRecordMatchesVisitor:
    def setup_method(self):
        self.r = IdentityResolver(db=None)
        self.now = datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc)

    def test_no_timestamp_is_refused(self):
        matched, weak = self.r._record_matches_visitor({"ip": "203.0.113.7"}, _visitor(self.now), "leadpipe")
        assert matched is False and weak is False

    def test_timestamp_in_window_matches(self):
        rec = {"ip": "203.0.113.7", "timestamp": (self.now - timedelta(minutes=5)).isoformat()}
        matched, weak = self.r._record_matches_visitor(rec, _visitor(self.now), "leadpipe")
        assert matched is True and weak is False

    def test_timestamp_outside_window_refused(self):
        rec = {"ip": "203.0.113.7", "timestamp": (self.now - timedelta(hours=6)).isoformat()}
        matched, weak = self.r._record_matches_visitor(rec, _visitor(self.now), "leadpipe")
        assert matched is False and weak is False


class TestApplyDoesNotClobber:
    def test_proxycurl_null_preserves_existing(self):
        profile = SimpleNamespace(
            linkedin_headline="Existing Headline",
            linkedin_summary="Existing Summary",
            linkedin_follower_count=500,
        )
        enricher._apply_proxycurl(profile, {"linkedin_headline": None})  # partial response
        assert profile.linkedin_headline == "Existing Headline"
        assert profile.linkedin_summary == "Existing Summary"
        assert profile.linkedin_follower_count == 500

    def test_proxycurl_value_overwrites(self):
        profile = SimpleNamespace(linkedin_headline=None, linkedin_summary=None, linkedin_follower_count=None)
        enricher._apply_proxycurl(profile, {"linkedin_headline": "New", "linkedin_follower_count": 10})
        assert profile.linkedin_headline == "New"
        assert profile.linkedin_follower_count == 10

    def test_twitter_empty_topics_preserve_prior(self):
        profile = SimpleNamespace(twitter_bio="bio", twitter_follower_count=99, twitter_recent_topics=["ai", "saas"])
        enricher._apply_twitter(profile, {"twitter_bio": None, "twitter_recent_topics": []})
        assert profile.twitter_bio == "bio"  # null didn't wipe
        assert profile.twitter_recent_topics == ["ai", "saas"]  # empty list didn't wipe


def test_social_intelligence_has_no_mock_tweets():
    # The bug was a call to self._mock_tweets which never existed (AttributeError
    # in the exception handler). Guard that no such method was reintroduced.
    from apps.api.services.social_intelligence import SocialIntelligence
    assert not hasattr(SocialIntelligence, "_mock_tweets")
