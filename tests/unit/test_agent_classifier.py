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


class TestTokenMatchingIsPreciseAndStable:
    """Classification feeds the tier, which gates the whole handoff sweep, so it
    has to be both precise about what counts as a vendor token and identical
    across processes for the same input."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "ua",
        [
            "MyScanner/1.0 (+http://example.com/gptbot-detector)",
            "SiteAudit/2.1 (+https://audit.example/docs/claudebot)",
        ],
    )
    def test_vendor_name_inside_a_comment_url_does_not_classify(self, ua):
        """Bot UAs conventionally carry a self-describing URL; a URL that merely
        mentions a vendor is not evidence that the caller IS that vendor."""
        assert classify_agent(ua) is None

    @pytest.mark.unit
    @pytest.mark.parametrize("ua", ["SomeBot gptbot-detector/2.0", "x-claudebot-proxy/1.0"])
    def test_token_fragment_does_not_classify(self, ua):
        assert classify_agent(ua) is None

    @pytest.mark.unit
    def test_real_vendor_ua_still_classifies_despite_url_stripping(self):
        """The product token sits outside the comment URL, so stripping the URL
        must not cost a genuine agent its classification."""
        result = classify_agent(
            "Mozilla/5.0 (compatible; GPTBot/1.0; +https://openai.com/gptbot)"
        )
        assert result is not None
        assert (result.vendor, result.product_or_ua_token) == ("openai", "gptbot")

    @pytest.mark.unit
    def test_multi_token_ua_resolves_to_the_most_specific_token(self):
        """A UA carrying two tokens of one vendor must resolve the same way every
        run. Set iteration order follows per-process randomized string hashes, so
        the token order is fixed deliberately, longest first."""
        result = classify_agent("GPTBot ChatGPT-User")
        assert result is not None
        assert result.product_or_ua_token == "chatgpt-user"
