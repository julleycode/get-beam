"""Session/auth mixin: cookie hydration, login flow, error screenshots."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import structlog

from apps.api.config import settings
from apps.api.services.platforms.twitter_browser._core import TwitterBrowserError

logger = structlog.get_logger()


class SessionMixin:
    """Cookie/session lifecycle + shared error-screenshot helper."""

    def __init__(self) -> None:
        self._cookie_path = Path(
            os.path.expanduser(settings.twitter_browser_cookie_path)
        )
        self._headless = settings.twitter_browser_headless
        # Hydrate cookies from env var (for Railway/Docker)
        self._hydrate_cookies_from_env()

    def _hydrate_cookies_from_env(self) -> None:
        """Write cookies from TWITTER_BROWSER_COOKIES_B64 env var to disk."""
        if self._cookie_path.exists():
            return
        b64_data = settings.twitter_browser_cookies_b64
        if not b64_data:
            return
        import base64
        try:
            raw = base64.b64decode(b64_data)
            self._cookie_path.parent.mkdir(parents=True, exist_ok=True)
            self._cookie_path.write_bytes(raw)
            logger.info("twitter_browser_cookies_hydrated_from_env", path=str(self._cookie_path))
        except Exception:
            logger.exception("twitter_browser_cookies_hydration_failed")

    async def setup_login(self) -> None:
        """Launch a headed browser for the user to log into Twitter manually.

        After login is complete, browser cookies/storage state are saved
        to disk for future headless sessions.
        """
        from playwright.async_api import async_playwright

        # Ensure parent directory exists
        self._cookie_path.parent.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/136.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            logger.info("twitter_browser_login_starting", cookie_path=str(self._cookie_path))
            await page.goto("https://x.com/login", wait_until="domcontentloaded")

            # Wait for the user to log in — detect /home URL
            try:
                await page.wait_for_url(
                    re.compile(r"https://(x\.com|twitter\.com)/home"),
                    timeout=600_000,  # 10 minutes to complete login
                )
            except Exception:
                logger.error("twitter_browser_login_timeout")
                await browser.close()
                raise TwitterBrowserError(
                    "Login timed out after 10 minutes. Please try again."
                )

            # Small delay for cookies to settle
            await page.wait_for_timeout(2000)

            # Save storage state (cookies + localStorage)
            await context.storage_state(path=str(self._cookie_path))
            logger.info("twitter_browser_login_saved", cookie_path=str(self._cookie_path))

            await browser.close()

    async def _save_error_screenshot(self, page, context: str) -> None:  # noqa: ANN001
        """Save a screenshot for debugging on failure."""
        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = f"/tmp/twitter_browser_error_{context}_{timestamp}.png"
            await page.screenshot(path=path, full_page=False)
            logger.info("twitter_browser_error_screenshot_saved", path=path)
        except Exception as exc:
            logger.warning("twitter_browser_screenshot_failed", error=str(exc))
