"""Unit tests for classify_ai_source (AI-referral attribution, v1).

Docker-free — the classifier is pure and DB-free. Covers AC-U1..AC-U4.
"""

import pytest

from apps.api.services.ai_referral import classify_ai_source

pytestmark = pytest.mark.unit


class TestKnownHosts:
    """AC-U1: every known AI answer-engine host maps to its label, including
    full URLs with scheme/path/query."""

    @pytest.mark.parametrize(
        "referrer, expected",
        [
            ("https://chatgpt.com/", "chatgpt"),
            ("https://chatgpt.com/c/abc-123?utm=x", "chatgpt"),
            ("https://chat.openai.com/", "chatgpt"),
            ("https://www.perplexity.ai/search?q=beam", "perplexity"),
            ("https://gemini.google.com/app", "gemini"),
            ("https://bard.google.com/", "gemini"),
            ("https://copilot.microsoft.com/", "copilot"),
            ("https://copilot.cloud.microsoft/chat", "copilot"),
            ("https://claude.ai/chat/xyz", "claude"),
            ("https://you.com/search", "you"),
            ("https://grok.com/", "grok"),
            ("https://x.ai/", "grok"),
            ("https://chat.deepseek.com/", "deepseek"),
            ("https://chat.mistral.ai/chat", "mistral"),
        ],
    )
    def test_known_host_maps_to_label(self, referrer, expected):
        assert classify_ai_source(referrer) == expected


class TestNonAiReferrers:
    """AC-U2: direct / social / own-domain / unknown referrers → None."""

    @pytest.mark.parametrize(
        "referrer",
        [
            None,
            "",
            "   ",
            "direct",
            "https://twitter.com/someone",
            "https://x.com/someone",  # social X, not x.ai
            "https://www.linkedin.com/feed/",
            "https://news.ycombinator.com/",
            "https://getbeam.fyi/pricing",  # own domain
            "https://example.com/",
        ],
    )
    def test_non_ai_referrer_returns_none(self, referrer):
        assert classify_ai_source(referrer) is None


class TestHostRobustness:
    """AC-U3: www. prefix, subdomains, path, case, and no-scheme all normalize."""

    @pytest.mark.parametrize(
        "referrer, expected",
        [
            ("https://www.chatgpt.com/", "chatgpt"),
            ("chatgpt.com/c/abc", "chatgpt"),  # no scheme
            ("HTTPS://ChatGPT.com/", "chatgpt"),  # mixed case
            ("https://sub.chatgpt.com/x", "chatgpt"),  # deeper subdomain
            ("https://chatgpt.com:443/path", "chatgpt"),  # explicit port
            ("//perplexity.ai/search", "perplexity"),  # protocol-relative
        ],
    )
    def test_host_normalization(self, referrer, expected):
        assert classify_ai_source(referrer) == expected


class TestFalsePositiveGuard:
    """AC-U4: bare google.com / bing.com / openai.com search URLs → None
    (in-SERP AI answers are indistinguishable from organic search)."""

    @pytest.mark.parametrize(
        "referrer",
        [
            "https://www.google.com/search?q=beam",
            "https://google.com/",
            "https://www.bing.com/search?q=beam",
            "https://bing.com/",
            "https://openai.com/",  # marketing site, not the chat product
        ],
    )
    def test_search_engine_not_attributed(self, referrer):
        assert classify_ai_source(referrer) is None
