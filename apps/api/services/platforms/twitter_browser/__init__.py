"""Twitter browser automation via Playwright.

Bypasses Twitter Free-tier API limitations:
- Replies blocked (403) → post via browser
- Timeline read blocked (402) → scrape via browser

`TwitterBrowserPoster` composes three mixins (session, posting, scraping).
Behavior is identical to the former single-file module — this is a structural
split only. Public symbols (`TwitterBrowserPoster`, `TwitterBrowserError`,
`TwitterSessionExpiredError`) are re-exported here so existing imports
(`from apps.api.services.platforms.twitter_browser import ...`) keep working.
"""

from apps.api.services.platforms.twitter_browser._core import (
    TwitterBrowserError,
    TwitterSessionExpiredError,
)
from apps.api.services.platforms.twitter_browser.posting import PostingMixin
from apps.api.services.platforms.twitter_browser.scraping import ScrapingMixin
from apps.api.services.platforms.twitter_browser.session import SessionMixin


class TwitterBrowserPoster(SessionMixin, PostingMixin, ScrapingMixin):
    """Posts Twitter replies via Playwright browser automation."""


__all__ = [
    "TwitterBrowserPoster",
    "TwitterBrowserError",
    "TwitterSessionExpiredError",
]
