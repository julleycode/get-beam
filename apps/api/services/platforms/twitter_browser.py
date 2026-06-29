"""Twitter browser automation via Playwright.

Bypasses Twitter Free-tier API limitations:
- Replies blocked (403) → post via browser
- Timeline read blocked (402) → scrape via browser
"""

import asyncio
import json
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

from apps.api.config import settings
from apps.api.services.platforms.base import FeedPost

logger = structlog.get_logger()

# Module-level lock: only one browser session at a time
_browser_lock = asyncio.Lock()


class TwitterBrowserError(Exception):
    """Raised when browser-based reply posting fails."""
    pass


class TwitterSessionExpiredError(TwitterBrowserError):
    """Raised when saved cookies are expired / user is logged out."""
    pass


class TwitterBrowserPoster:
    """Posts Twitter replies via Playwright browser automation."""

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

    # ── Public API ──────────────────────────────────────

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

    async def fetch_timeline(self, *, limit: int = 20) -> list[FeedPost]:
        """Scrape the home timeline via browser automation.

        Scrolls the /home feed, extracts tweet data from the DOM,
        and returns normalized FeedPost objects.

        Args:
            limit: Maximum number of posts to return.

        Returns:
            List of FeedPost from the user's Following timeline.
        """
        if not self._cookie_path.exists():
            raise TwitterBrowserError(
                f"No saved Twitter session at {self._cookie_path}. "
                "Run: python apps/api/scripts/twitter_login.py"
            )

        async with _browser_lock:
            return await self._do_fetch_timeline(limit=limit)

    # ── Internal ────────────────────────────────────────

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

    async def _do_fetch_timeline(self, *, limit: int = 20) -> list[FeedPost]:
        """Scrape tweets from the Following timeline via browser."""
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
                posts = await self._scrape_timeline(page, limit=limit)
                # Update stored cookies
                await context.storage_state(path=str(self._cookie_path))
                return posts
            except TwitterSessionExpiredError:
                raise
            except TwitterBrowserError:
                raise
            except Exception as exc:
                await self._save_error_screenshot(page, "fetch_timeline")
                raise TwitterBrowserError(
                    f"Browser timeline fetch failed: {exc}"
                ) from exc
            finally:
                await browser.close()

    async def _scrape_timeline(
        self, page, *, limit: int = 20  # noqa: ANN001
    ) -> list[FeedPost]:
        """Navigate to /home, switch to Following tab, scroll and extract tweets.

        Strategy: go to /home first (tweets always load there), wait for
        content, *then* click the Following tab.  Direct navigation to
        /home/following often renders a blank feed even though the tab
        indicator is correct.
        """
        logger.info("twitter_browser_fetching_timeline", limit=limit)

        # ── Step 1: Load /home and wait for initial tweets ──
        await page.goto(
            "https://x.com/home",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        await page.wait_for_timeout(random.randint(2000, 3500))

        # Check for login redirect
        if "/login" in page.url or "/i/flow/login" in page.url:
            raise TwitterSessionExpiredError(
                "Twitter session expired. Re-run login: "
                "python apps/api/scripts/twitter_login.py"
            )

        # Wait for at least one tweet on the "For You" default tab
        try:
            await page.wait_for_selector(
                '[data-testid="tweet"]', timeout=15_000
            )
        except Exception:
            await self._save_error_screenshot(page, "home_no_tweets")
            raise TwitterBrowserError(
                "No tweets loaded on the /home page."
            )

        # ── Step 2: Click the "Following" tab ──
        logger.info("twitter_browser_switching_to_following_tab")
        switched = False
        tabs = await page.query_selector_all('[role="tab"]')
        for tab in tabs:
            txt = (await tab.inner_text()).strip()
            if "Following" in txt:
                await tab.click()
                switched = True
                logger.info("twitter_browser_clicked_following_tab")
                break

        if not switched:
            # Fallback: try direct URL navigation
            logger.warning("twitter_browser_following_tab_not_found_trying_url")
            await page.goto(
                "https://x.com/home/following",
                wait_until="domcontentloaded",
                timeout=30_000,
            )

        # Wait for the feed to refresh with Following content.
        # After the tab click the existing tweet elements may be swapped
        # out; we wait for network idle + a fresh tweet to appear.
        await page.wait_for_timeout(random.randint(2500, 4000))

        # Verify the Following tab is active
        try:
            active_tab = await page.query_selector(
                '[role="tab"][aria-selected="true"]'
            )
            if active_tab:
                active_text = (await active_tab.inner_text()).strip()
                logger.info(
                    "twitter_browser_active_tab",
                    tab_text=active_text,
                    url=page.url,
                )
        except Exception:
            pass

        # Wait for tweets under the Following feed
        try:
            await page.wait_for_selector(
                '[data-testid="tweet"]', timeout=15_000
            )
        except Exception:
            await self._save_error_screenshot(page, "following_no_tweets")
            raise TwitterBrowserError(
                "No tweets loaded on the Following timeline."
            )

        # Scroll and collect tweets until we have enough
        collected: list[FeedPost] = []
        seen_ids: set[str] = set()
        max_scrolls = 10  # Safety limit
        scroll_count = 0

        while len(collected) < limit and scroll_count < max_scrolls:
            # Extract tweets currently visible on page
            new_posts = await self._extract_tweets_from_page(page, seen_ids)
            collected.extend(new_posts)
            logger.debug(
                "twitter_browser_scroll_batch",
                new=len(new_posts),
                total=len(collected),
                scroll=scroll_count,
            )

            if len(collected) >= limit:
                break

            # Scroll down to load more
            await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
            await page.wait_for_timeout(random.randint(1500, 2500))
            scroll_count += 1

            # Check if new tweets appeared
            if len(new_posts) == 0 and scroll_count > 2:
                # No new tweets after scrolling, we've likely hit the end
                break

        logger.info(
            "twitter_browser_timeline_fetched",
            count=len(collected),
            scrolls=scroll_count,
        )
        return collected[:limit]

    async def _extract_tweets_from_page(
        self, page, seen_ids: set[str]  # noqa: ANN001
    ) -> list[FeedPost]:
        """Extract tweet data from currently visible tweet elements."""
        posts: list[FeedPost] = []

        # Use JavaScript to extract tweet data from the DOM
        tweets_data = await page.evaluate("""
            () => {
                const tweets = [];
                const articles = document.querySelectorAll('article[data-testid="tweet"]');

                for (const article of articles) {
                    try {
                        // Extract tweet link to get ID and author
                        const timeLink = article.querySelector('a[href*="/status/"] time');
                        const statusLink = timeLink
                            ? timeLink.closest('a')
                            : article.querySelector('a[href*="/status/"]');

                        if (!statusLink) continue;

                        const href = statusLink.getAttribute('href') || '';
                        const match = href.match(/\\/([^\\/]+)\\/status\\/(\\d+)/);
                        if (!match) continue;

                        const authorUsername = match[1];
                        const tweetId = match[2];

                        // Extract display name
                        // Find the user name element - it's usually in a div with dir="ltr"
                        // near the avatar
                        const userNameEl = article.querySelector(
                            '[data-testid="User-Name"]'
                        );
                        let authorName = authorUsername;
                        if (userNameEl) {
                            const nameSpan = userNameEl.querySelector(
                                'a[role="link"] span'
                            );
                            if (nameSpan) {
                                authorName = nameSpan.textContent || authorUsername;
                            }
                        }

                        // Extract avatar
                        const avatarImg = article.querySelector(
                            '[data-testid="Tweet-User-Avatar"] img'
                        );
                        const avatarUrl = avatarImg
                            ? avatarImg.getAttribute('src')
                            : null;

                        // Extract tweet text
                        const tweetTextEl = article.querySelector(
                            '[data-testid="tweetText"]'
                        );
                        const content = tweetTextEl
                            ? tweetTextEl.textContent || ''
                            : '';

                        // Extract timestamp
                        const timeEl = article.querySelector('time');
                        const postedAt = timeEl
                            ? timeEl.getAttribute('datetime') || ''
                            : '';

                        // Skip retweets (they have a "reposted" indicator)
                        const socialContext = article.querySelector(
                            '[data-testid="socialContext"]'
                        );
                        const isRetweet = socialContext
                            ? socialContext.textContent?.includes('reposted') || false
                            : false;

                        tweets.push({
                            tweetId,
                            authorUsername,
                            authorName,
                            avatarUrl,
                            content,
                            postedAt,
                            isRetweet,
                        });
                    } catch (e) {
                        // Skip malformed tweet
                    }
                }
                return tweets;
            }
        """)

        for t in tweets_data:
            tweet_id = t.get("tweetId", "")
            if not tweet_id or tweet_id in seen_ids:
                continue

            seen_ids.add(tweet_id)

            # Parse timestamp
            posted_at_str = t.get("postedAt", "")
            try:
                posted_at = datetime.fromisoformat(
                    posted_at_str.replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                posted_at = datetime.now(timezone.utc)

            author_username = t.get("authorUsername", "unknown")
            posts.append(
                FeedPost(
                    platform_post_id=tweet_id,
                    author_name=t.get("authorName", author_username),
                    author_username=author_username,
                    author_avatar_url=t.get("avatarUrl"),
                    content=t.get("content", ""),
                    post_url=f"https://x.com/{author_username}/status/{tweet_id}",
                    posted_at=posted_at,
                )
            )

        return posts

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

    async def _save_error_screenshot(self, page, context: str) -> None:  # noqa: ANN001
        """Save a screenshot for debugging on failure."""
        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = f"/tmp/twitter_browser_error_{context}_{timestamp}.png"
            await page.screenshot(path=path, full_page=False)
            logger.info("twitter_browser_error_screenshot_saved", path=path)
        except Exception as exc:
            logger.warning("twitter_browser_screenshot_failed", error=str(exc))
