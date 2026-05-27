"""Tests for apps.api.services.bot_filter.is_bot()"""

import pytest
from apps.api.services.bot_filter import is_bot


class TestKnownBots:
    """Known bot user-agents should be detected."""

    @pytest.mark.parametrize("ua", [
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
        "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
        "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatype.php)",
        "Twitterbot/1.0",
        "LinkedInBot/1.0",
        "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)",
        "Mozilla/5.0 AppleWebKit/537.36 HeadlessChrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (compatible; GPTBot/1.0; +https://openai.com/gptbot)",
        "ClaudeBot",
        "Scrapy/2.11.0",
        "python-requests/2.31.0",
        "curl/7.88.1",
        "Go-http-client/2.0",
        "Lighthouse",
        "PageSpeed Insights",
    ])
    def test_detects_known_bots(self, ua: str):
        assert is_bot(ua) is True


class TestRealBrowsers:
    """Real browser user-agents should NOT be flagged as bots."""

    @pytest.mark.parametrize("ua", [
        # Chrome on macOS
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        # Firefox on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        # Safari on iOS
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
        # Edge on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        # Chrome on Android
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        # Samsung Internet
        "Mozilla/5.0 (Linux; Android 13; SM-S908B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/23.0 Chrome/115.0.0.0 Mobile Safari/537.36",
    ])
    def test_allows_real_browsers(self, ua: str):
        assert is_bot(ua) is False


class TestEdgeCases:
    """Edge cases: empty, short, None-like values."""

    def test_empty_string_is_bot(self):
        assert is_bot("") is True

    def test_very_short_ua_is_bot(self):
        assert is_bot("Mozilla/5.0") is True  # too short to be real

    def test_whitespace_only_is_bot(self):
        assert is_bot("   ") is True

    def test_case_insensitive_detection(self):
        assert is_bot("googlebot") is True
        assert is_bot("GOOGLEBOT") is True
        assert is_bot("GoOgLeBoT") is True


class TestAutomationTools:
    """Headless browsers and automation tools should be detected."""

    @pytest.mark.parametrize("ua", [
        "Mozilla/5.0 PhantomJS/2.1.1",
        "Selenium",
        "Puppeteer",
    ])
    def test_detects_automation_tools(self, ua: str):
        assert is_bot(ua) is True
