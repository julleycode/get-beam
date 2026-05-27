"""Server-side bot detection via User-Agent analysis.

Filters out known bots, crawlers, scrapers, and automated tools
to prevent them from inflating visitor counts.
"""

import re

# Compiled regex for performance — matches common bot signatures
_BOT_PATTERN = re.compile(
    r"bot|crawler|spider|headless|phantom|puppeteer|selenium|"
    r"scrapy|wget|curl|python-requests|python-urllib|httpx|aiohttp|"
    r"googlebot|bingbot|slurp|duckduckbot|baiduspider|yandexbot|"
    r"facebookexternalhit|twitterbot|linkedinbot|whatsapp|telegrambot|"
    r"applebot|semrushbot|ahrefsbot|dotbot|mj12bot|rogerbot|"
    r"lighthouse|pagespeed|gtmetrix|pingdom|uptimerobot|"
    r"go-http-client|java|ruby|perl|php|node-fetch|"
    r"postman|insomnia|httpie|axios|got/|undici|"
    r"claudebot|anthropic|openai|gptbot|chatgpt|"
    r"archive\.org|ia_archiver|"
    r"feedfetcher|feedparser|rssowl|"
    r"preview|prerender|snap|embed|"
    r"DataForSeoBot|bytespider|ccbot",
    re.IGNORECASE,
)

# Very short or suspicious user agents
_MIN_UA_LENGTH = 20


def is_bot(user_agent: str) -> bool:
    """Check if a user-agent string indicates a bot/crawler.

    Returns True if the UA matches known bot patterns or looks suspicious.
    """
    if not user_agent:
        return True  # No UA is suspicious

    if len(user_agent) < _MIN_UA_LENGTH:
        return True  # Real browsers have longer UAs

    return bool(_BOT_PATTERN.search(user_agent))
