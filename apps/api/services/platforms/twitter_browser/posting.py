"""Reply-posting mixin: navigate to a tweet, type, submit, capture reply ID."""

import asyncio
import random
from typing import Optional

import structlog

from apps.api.services.platforms.twitter_browser._core import (
    TwitterBrowserError,
    TwitterSessionExpiredError,
    _browser_lock,
)

logger = structlog.get_logger()


class PostingMixin:
    """Browser automation for posting a reply to a tweet."""

    async def post_reply(self, tweet_url: str, text: str) -> str:
        """Post a reply to a tweet via browser automation.

        Args:
            tweet_url: Full URL to the tweet (e.g. https://x.com/user/status/123)
            text: The reply text to post.

        Returns:
            The reply tweet ID (string).

        Raises:
            TwitterSessionExpiredError: If cookies are expired.
            TwitterBrowserError: If reply posting fails for any reason.
        """
        if not self._cookie_path.exists():
            raise TwitterBrowserError(
                f"No saved Twitter session found at {self._cookie_path}. "
                "Run the login setup first: python apps/api/scripts/twitter_login.py"
            )

        async with _browser_lock:
            return await self._do_post_reply(tweet_url, text)

    async def _do_post_reply(self, tweet_url: str, text: str) -> str:
        """Actual browser automation for posting a reply."""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self._headless)
            context = await browser.new_context(
                storage_state=str(self._cookie_path),
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/136.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            try:
                reply_id = await self._navigate_and_reply(page, tweet_url, text)

                # Update stored cookies after successful interaction
                await context.storage_state(path=str(self._cookie_path))

                return reply_id
            except TwitterSessionExpiredError:
                raise
            except TwitterBrowserError:
                raise
            except Exception as exc:
                # Save debug screenshot
                await self._save_error_screenshot(page, "post_reply")
                raise TwitterBrowserError(f"Browser reply failed: {exc}") from exc
            finally:
                await browser.close()

    async def _navigate_and_reply(
        self, page, tweet_url: str, text: str  # noqa: ANN001
    ) -> str:
        """Navigate to tweet and post a reply. Returns reply tweet ID."""
        logger.info("twitter_browser_navigating", url=tweet_url)

        # Navigate to the tweet
        await page.goto(tweet_url, wait_until="domcontentloaded", timeout=30_000)

        # Human-like delay after page load
        await page.wait_for_timeout(random.randint(1500, 3000))

        # Check if we landed on login page (session expired)
        if "/login" in page.url or "/i/flow/login" in page.url:
            logger.warning("twitter_browser_session_expired")
            raise TwitterSessionExpiredError(
                "Twitter session expired. Re-run the login setup: "
                "python apps/api/scripts/twitter_login.py"
            )

        # Wait for tweet content to load
        try:
            await page.wait_for_selector(
                '[data-testid="tweetText"]', timeout=15_000
            )
        except Exception:
            await self._save_error_screenshot(page, "tweet_not_loaded")
            raise TwitterBrowserError(
                f"Tweet content did not load at {tweet_url}. "
                "The tweet may be deleted or the account may be suspended."
            )

        # Find the reply input area — on a tweet detail page, the reply box
        # is typically the inline compose area below the tweet.
        reply_box = await self._find_reply_box(page)

        # Click to focus the reply box
        await reply_box.click()
        await page.wait_for_timeout(random.randint(500, 1000))

        # Type the reply with human-like delays
        await self._human_type(page, text)

        # Small pause before submitting (human-like)
        await page.wait_for_timeout(random.randint(1000, 2000))

        # Set up a listener for the tweet creation network request
        reply_id = await self._click_reply_and_get_id(page)

        logger.info(
            "twitter_browser_reply_posted",
            tweet_url=tweet_url,
            reply_id=reply_id,
        )
        return reply_id

    async def _find_reply_box(self, page) -> object:  # noqa: ANN001
        """Find the reply text area on the tweet detail page."""
        # Twitter's reply box on the tweet detail page
        selectors = [
            '[data-testid="tweetTextarea_0"]',
            'div[role="textbox"][data-testid="tweetTextarea_0"]',
            'div[role="textbox"][aria-label*="Post your reply"]',
            'div[role="textbox"][aria-label*="reply"]',
            'div[role="textbox"]',
        ]

        for selector in selectors:
            try:
                element = await page.wait_for_selector(selector, timeout=5_000)
                if element:
                    logger.debug("twitter_browser_reply_box_found", selector=selector)
                    return element
            except Exception:
                continue

        # If none found, save screenshot for debugging
        await self._save_error_screenshot(page, "no_reply_box")
        raise TwitterBrowserError(
            "Could not find the reply text area. "
            "The tweet may not allow replies, or the UI has changed."
        )

    async def _human_type(self, page, text: str) -> None:  # noqa: ANN001
        """Type text with randomized delays to mimic human typing."""
        for char in text:
            await page.keyboard.type(char, delay=random.randint(30, 120))
            # Occasional longer pause (like thinking)
            if random.random() < 0.05:
                await page.wait_for_timeout(random.randint(200, 500))

    async def _click_reply_and_get_id(self, page) -> str:  # noqa: ANN001
        """Click the Reply button and extract the new tweet ID."""

        # Set up response listener to capture the tweet creation API call
        reply_tweet_id: Optional[str] = None
        captured_event = asyncio.Event()

        async def handle_response(response) -> None:  # noqa: ANN001
            nonlocal reply_tweet_id
            try:
                if (
                    "CreateTweet" in response.url
                    or "/TweetResultByRestId" in response.url
                    or (
                        "/2/tweets" in response.url
                        and response.request.method == "POST"
                    )
                ):
                    if response.status == 200:
                        body = await response.json()
                        # Try to extract tweet ID from GraphQL response
                        tweet_result = (
                            body.get("data", {})
                            .get("create_tweet", {})
                            .get("tweet_results", {})
                            .get("result", {})
                        )
                        rest_id = tweet_result.get("rest_id")
                        if rest_id:
                            reply_tweet_id = rest_id
                            captured_event.set()
            except Exception:
                pass  # Response parsing failed, we'll fall back

        page.on("response", handle_response)

        # Find and click the Reply/Post button
        reply_button_selectors = [
            '[data-testid="tweetButtonInline"]',
            '[data-testid="tweetButton"]',
            'button[data-testid="tweetButtonInline"]',
        ]

        clicked = False
        for selector in reply_button_selectors:
            try:
                button = await page.wait_for_selector(selector, timeout=5_000)
                if button and await button.is_enabled():
                    await button.click()
                    clicked = True
                    logger.debug("twitter_browser_reply_button_clicked", selector=selector)
                    break
            except Exception:
                continue

        if not clicked:
            await self._save_error_screenshot(page, "no_reply_button")
            raise TwitterBrowserError(
                "Could not find or click the Reply button."
            )

        # Wait for the API response with the tweet ID
        try:
            await asyncio.wait_for(captured_event.wait(), timeout=15.0)
        except asyncio.TimeoutError:
            pass  # We'll try alternative methods below

        page.remove_listener("response", handle_response)

        if reply_tweet_id:
            return reply_tweet_id

        # Fallback: wait a moment and check for success indicators
        await page.wait_for_timeout(3000)

        # Check if reply was posted by looking for a success toast/notification
        # or by checking if the reply box was cleared
        try:
            toast = await page.query_selector('[data-testid="toast"]')
            if toast:
                logger.info("twitter_browser_reply_toast_detected")
        except Exception:
            pass

        # The network capture is the ONLY trustworthy success signal — toast /
        # cleared-composer heuristics can't tell a posted reply from a
        # rate-limit / duplicate / blocked failure. Without a real rest_id, fail
        # rather than persist a fake ID and mark the draft "sent".
        raise TwitterBrowserError(
            "reply post-state unconfirmed: no tweet ID captured from the network response"
        )
