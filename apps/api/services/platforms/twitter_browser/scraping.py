"""Timeline-scraping mixin: scroll the Following feed and extract tweets."""

import random
from datetime import datetime, timezone

import structlog

from apps.api.services.platforms.base import FeedPost
from apps.api.services.platforms.twitter_browser._core import (
    TwitterBrowserError,
    TwitterSessionExpiredError,
    _browser_lock,
)

logger = structlog.get_logger()


class ScrapingMixin:
    """Browser automation for scraping the home/Following timeline."""

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
