"""Shared state + exceptions for the Twitter browser-automation mixins."""

import asyncio

# Module-level lock: only one browser session at a time.
# Shared by the posting and scraping mixins — imported, not re-created, so all
# browser operations serialize through the same lock.
_browser_lock = asyncio.Lock()


class TwitterBrowserError(Exception):
    """Raised when browser-based reply posting fails."""
    pass


class TwitterSessionExpiredError(TwitterBrowserError):
    """Raised when saved cookies are expired / user is logged out."""
    pass
