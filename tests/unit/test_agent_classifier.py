"""Tests for apps.api.services.agent_classifier.classify_agent."""

import pytest
from apps.api.services.agent_classifier import classify_agent


class TestRecognizedVendors:
    @pytest.mark.parametrize("ua,expected_vendor", [
        ("Mozilla/5.0 (compatible; GPTBot/1.0; +https://openai.com/gptbot)", "openai"),
        ("ChatGPT-User/1.0", "openai"),
        ("OAI-SearchBot/1.0", "openai"),
        ("ClaudeBot/1.0", "anthropic"),
        ("anthropic-ai", "anthropic"),
        ("Claude-User/1.0", "anthropic"),
        ("Claude-SearchBot/1.0", "anthropic"),
        ("PerplexityBot/1.0", "perplexity"),
        ("Perplexity-User/1.0", "perplexity"),
        ("Bytespider", "bytespider"),
    ])
    @pytest.mark.unit
    def test_classifies_known_vendor_tokens(self, ua, expected_vendor):
        result = classify_agent(ua)
        assert result is not None
        assert result.vendor == expected_vendor
        assert result.verification_method == "ua-only"


class TestDropOnlyTokensReturnNone:
    @pytest.mark.parametrize("ua", [
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "curl/7.88.1",
        "python-requests/2.31.0",
        "Mozilla/5.0 AppleWebKit/537.36 HeadlessChrome/120.0.0.0 Safari/537.36",
        "Scrapy/2.11.0",
        "ccbot",
        "bedrock-agentcore",
        "agentcore",
        "shap-user",
    ])
    @pytest.mark.unit
    def test_drop_only_tokens_return_none(self, ua):
        assert classify_agent(ua) is None


class TestAC13ExclusionRobotsTxtOnlyTokens:
    @pytest.mark.parametrize("ua", ["google-extended", "applebot-extended"])
    @pytest.mark.unit
    def test_robots_txt_only_tokens_never_classified(self, ua):
        assert classify_agent(ua) is None


class TestEmptyOrMissingUA:
    @pytest.mark.parametrize("ua", [None, "", "   "])
    @pytest.mark.unit
    def test_empty_or_none_returns_none(self, ua):
        assert classify_agent(ua) is None
