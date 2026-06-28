"""Server-side bot detection via User-Agent analysis.

Filters out known bots, crawlers, scrapers, and automated tools
to prevent them from inflating visitor counts.
"""

import re

# Compiled regex for performance — matches common bot signatures.
# Broad tokens are word-bounded so they don't swallow real browser UAs:
#   \bjava\b   — catches "Java/17.0.1" HTTP clients but NOT "javascript"
#   \bpreview\b / \bembed — catch link-preview/embed fetchers, not mid-word hits
#   \bsnap     — catches Snapchat's link-preview crawler; genuine Snapchat
#                in-app browsers are rescued by the allowlist below first
_BOT_PATTERN = re.compile(
    r"bot|crawler|spider|headless|phantom|puppeteer|selenium|"
    r"scrapy|wget|curl|python-requests|python-urllib|httpx|aiohttp|"
    r"googlebot|bingbot|slurp|duckduckbot|baiduspider|yandexbot|"
    r"facebookexternalhit|twitterbot|linkedinbot|whatsapp|telegrambot|"
    r"applebot|semrushbot|ahrefsbot|dotbot|mj12bot|rogerbot|"
    r"lighthouse|pagespeed|gtmetrix|pingdom|uptimerobot|"
    r"go-http-client|\bjava\b|ruby|perl|php|node-fetch|"
    r"postman|insomnia|httpie|axios|got/|undici|"
    r"claudebot|anthropic|openai|gptbot|chatgpt|"
    r"bedrock-agentcore|agentcore|shap-user|perplexitybot|"
    r"playwright|webdriver|cypress|okhttp|apache-httpclient|"
    r"archive\.org|ia_archiver|"
    r"feedfetcher|feedparser|rssowl|"
    r"\bpreview\b|prerender|\bsnap|\bembed|"
    r"DataForSeoBot|bytespider|ccbot",
    re.IGNORECASE,
)

# Very short or suspicious user agents
_MIN_UA_LENGTH = 20

# In-app browser markers (case-sensitive — real apps emit these exact tokens).
# Social in-app WebViews are REAL humans clicking through from social posts;
# the bot patterns above (e.g. \bsnap) must never silently drop them.
_IN_APP_BROWSER_MARKERS = (
    "Snapchat/",
    "Instagram",
    "FBAV",
    "FBAN",
    "TikTok",
    "musical_ly",
    "Line/",
    "MicroMessenger",
)

# A genuine in-app browser UA always carries a mobile device marker.
# Link-preview crawlers (e.g. Snapchat's URL preview fetcher) lack these and
# still fall through to the bot patterns.
_MOBILE_MARKERS = ("Mobile", "Android", "iPhone")


def _is_in_app_browser(user_agent: str) -> bool:
    """Return True for genuine mobile in-app browsers (Snapchat, Instagram, ...)."""
    return any(marker in user_agent for marker in _IN_APP_BROWSER_MARKERS) and any(
        marker in user_agent for marker in _MOBILE_MARKERS
    )


def is_bot(user_agent: str) -> bool:
    """Check if a user-agent string indicates a bot/crawler.

    Returns True if the UA matches known bot patterns or looks suspicious.
    Empty/missing UA is always treated as a bot (documented behavior the
    ingest endpoint and tests rely on).
    """
    if not user_agent:
        return True  # No UA is suspicious

    if len(user_agent) < _MIN_UA_LENGTH:
        return True  # Real browsers have longer UAs

    # In-app browsers short-circuit BEFORE bot patterns: real social traffic.
    if _is_in_app_browser(user_agent):
        return False

    return bool(_BOT_PATTERN.search(user_agent))
