"""AC1 — dominant-signal precedence, 40% share, empty input, CTA resolution."""
from datetime import datetime, timedelta, timezone

import pytest

from apps.api.services.icp_fit import _STRONG_FIT_AT
from apps.api.services.signal_angle import (
    ANGLE_GUIDANCE,
    CtaType,
    SignalAngle,
    available_cta_types,
    cta_url,
    dominant_signal,
    resolve_cta,
    visitor_angle,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 27, tzinfo=timezone.utc)


def _p(**kw):
    base = {"visitor_id": kw.pop("vid", "v"), "total_sessions": 1, "pages_visited": []}
    base.update(kw)
    return base


class TestVisitorAngle:
    def test_job_change_beats_pricing(self):
        p = _p(job_changed_at=(NOW - timedelta(days=3)).isoformat(), pages_visited=["/pricing"])
        assert visitor_angle(p, now=NOW) is SignalAngle.JOB_CHANGE

    def test_stale_job_change_ignored(self):
        p = _p(job_changed_at=(NOW - timedelta(days=31)).isoformat(), pages_visited=["/plans"])
        assert visitor_angle(p, now=NOW) is SignalAngle.PRICING_INTENT

    def test_pricing_beats_ai_referral(self):
        p = _p(pages_visited=[{"url": "https://x.com/Pricing"}], ai_source="chatgpt")
        assert visitor_angle(p, now=NOW) is SignalAngle.PRICING_INTENT

    def test_ai_referral_beats_icp(self):
        p = _p(ai_source="perplexity", total_sessions=9)
        assert visitor_angle(p, 99, use_icp_fit=True, now=NOW) is SignalAngle.AI_REFERRAL

    def test_icp_rung_uses_threshold_and_flag(self):
        p = _p(total_sessions=5)
        assert visitor_angle(p, _STRONG_FIT_AT, use_icp_fit=True, now=NOW) is SignalAngle.HIGH_ICP_FIT
        assert (
            visitor_angle(p, _STRONG_FIT_AT - 1, use_icp_fit=True, now=NOW)
            is SignalAngle.REPEAT_VISIT
        )
        # icp flag OFF → rung skipped even with a high score.
        assert visitor_angle(p, 100, use_icp_fit=False, now=NOW) is SignalAngle.REPEAT_VISIT

    def test_general_fallback(self):
        assert visitor_angle(_p(), now=NOW) is SignalAngle.GENERAL


class TestDominantSignal:
    def test_empty_input_is_general(self):
        assert dominant_signal([], now=NOW) is SignalAngle.GENERAL

    def test_job_change_at_exactly_40_percent(self):
        recent = (NOW - timedelta(days=1)).isoformat()
        profiles = [_p(job_changed_at=recent)] * 2 + [_p(pages_visited=["/pricing"])] + [_p()] * 2
        assert dominant_signal(profiles, now=NOW) is SignalAngle.JOB_CHANGE  # 2/5

    def test_below_40_percent_falls_back_to_general(self):
        profiles = [_p(pages_visited=["/pricing"])] * 3 + [_p()] * 5  # 3/8 = 37.5%
        assert dominant_signal(profiles, now=NOW) is SignalAngle.GENERAL

    def test_tie_breaks_by_precedence(self):
        profiles = [_p(ai_source="chatgpt"), _p(pages_visited=["/pricing"])]
        assert dominant_signal(profiles, now=NOW) is SignalAngle.PRICING_INTENT

    def test_icp_only_when_fits_supplied(self):
        profiles = [_p(vid="a"), _p(vid="b")]
        assert dominant_signal(profiles, now=NOW) is SignalAngle.GENERAL
        assert dominant_signal(profiles, {"a": 90, "b": 80}, now=NOW) is SignalAngle.HIGH_ICP_FIT

    def test_every_angle_has_guidance(self):
        assert set(ANGLE_GUIDANCE) == set(SignalAngle)


CFG = {
    "default": "free_trial",
    "types": {
        "free_trial": {"url": "https://acme.com/trial"},
        "resource": {"url": "https://acme.com/guide"},
    },
}


class TestCta:
    def test_cta_url(self):
        assert cta_url(CFG, CtaType.FREE_TRIAL, None) == "https://acme.com/trial"
        assert cta_url(CFG, CtaType.BOOK_DEMO, "https://cal.com/x") == "https://cal.com/x"
        assert cta_url(CFG, CtaType.BOOK_DEMO, None) is None
        assert cta_url(CFG, CtaType.REPLY, "https://cal.com/x") is None
        assert cta_url(None, CtaType.PRICING_PAGE, None) is None

    def test_available_always_includes_reply(self):
        assert available_cta_types(None, None) == [CtaType.REPLY]
        assert available_cta_types(CFG, "https://cal.com/x") == [
            CtaType.BOOK_DEMO,
            CtaType.FREE_TRIAL,
            CtaType.RESOURCE,
            CtaType.REPLY,
        ]

    def test_resolve_requested_default_and_fallback(self):
        assert resolve_cta(CFG, "resource") is CtaType.RESOURCE
        assert resolve_cta(CFG, "pricing_page") is CtaType.FREE_TRIAL  # unavailable → default
        assert resolve_cta(CFG, "bogus") is CtaType.FREE_TRIAL
        assert resolve_cta({"default": "book_demo"}, None) is CtaType.REPLY
        assert resolve_cta(None, "book_demo", "https://cal.com/x") is CtaType.BOOK_DEMO
