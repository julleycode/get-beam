"""Unit tests for the referrer reward-notification email builder (no DB)."""

from apps.api.services.referral_activation import build_reward_email


class TestBuildRewardEmail:
    def test_subject_and_body(self):
        subject, html = build_reward_email(referrer_bonus=30)
        assert "+10 identified visitors/month" in subject
        assert "+30/mo" in html
        assert "+50 max" in html
        assert "/dashboard/referrals" in html

    def test_no_email_addresses_in_body(self):
        _, html = build_reward_email(referrer_bonus=10)
        assert "@" not in html
