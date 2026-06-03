"""LinkedIn browser automation via Playwright.

Bypasses LinkedIn API limitations:
- Feed read: LinkedIn API only returns own posts, not network feed
- Comments: API requires w_member_social scope which may be restricted

Same pattern as twitter_browser.py:
1. User logs in manually via headed browser → cookies saved
2. Headless sessions reuse saved cookies for feed scraping + commenting
"""

import asyncio
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

_browser_lock = asyncio.Lock()


class LinkedInBrowserError(Exception):
    pass


class LinkedInSessionExpiredError(LinkedInBrowserError):
    pass


class LinkedInBrowserPoster:
    """Scrapes LinkedIn feed and posts comments via Playwright."""

    def __init__(self) -> None:
        self._cookie_path = Path(
            os.path.expanduser(settings.linkedin_browser_cookie_path)
        )
        self._headless = settings.linkedin_browser_headless
        self._hydrate_cookies_from_env()

    def _hydrate_cookies_from_env(self) -> None:
        if self._cookie_path.exists():
            return
        b64_data = settings.linkedin_browser_cookies_b64
        if not b64_data:
            return
        import base64
        try:
            raw = base64.b64decode(b64_data)
            self._cookie_path.parent.mkdir(parents=True, exist_ok=True)
            self._cookie_path.write_bytes(raw)
            logger.info("linkedin_browser_cookies_hydrated", path=str(self._cookie_path))
        except Exception:
            logger.exception("linkedin_browser_cookies_hydration_failed")

    # ── Public API ──

    async def setup_login(self, oauth_url: str | None = None) -> str | None:
        """Launch headed browser for LinkedIn login. Saves cookies.

        Args:
            oauth_url: If provided, navigates to the OAuth authorize URL instead
                of the plain login page. After the user authorizes, intercepts
                the callback redirect and returns the OAuth code.
                This way one login gives us BOTH cookies AND OAuth tokens.

        Returns:
            The OAuth authorization code (if oauth_url was provided), or None.
        """
        from playwright.async_api import async_playwright

        self._cookie_path.parent.mkdir(parents=True, exist_ok=True)

        start_url = oauth_url or "https://www.linkedin.com/login"
        # If using OAuth, we wait for the callback redirect; otherwise wait for /feed
        wait_pattern = (
            re.compile(r".*/api/v1/social/callback/linkedin\?")
            if oauth_url
            else re.compile(r"https://www\.linkedin\.com/feed")
        )

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

            oauth_code: str | None = None

            if oauth_url:
                # Intercept the callback redirect to capture the code
                # before it actually hits our server
                async def intercept_callback(route):
                    nonlocal oauth_code
                    url = route.request.url
                    from urllib.parse import urlparse, parse_qs
                    parsed = urlparse(url)
                    qs = parse_qs(parsed.query)
                    if "code" in qs:
                        oauth_code = qs["code"][0]
                        logger.info("linkedin_browser_oauth_code_captured")
                    # Let the redirect continue (it will hit our callback endpoint)
                    await route.continue_()

                await page.route("**/api/v1/social/callback/linkedin*", intercept_callback)

            logger.info("linkedin_browser_login_starting", url=start_url)
            await page.goto(start_url, wait_until="domcontentloaded")

            try:
                await page.wait_for_url(wait_pattern, timeout=600_000)
            except Exception:
                logger.error("linkedin_browser_login_timeout")
                await browser.close()
                raise LinkedInBrowserError("Login timed out after 10 minutes.")

            await page.wait_for_timeout(2000)

            # If OAuth flow, navigate to /feed to establish full session cookies
            if oauth_url and oauth_code:
                try:
                    await page.goto(
                        "https://www.linkedin.com/feed/",
                        wait_until="domcontentloaded",
                        timeout=15_000,
                    )
                    await page.wait_for_timeout(2000)
                except Exception:
                    pass  # Cookie saving still works even if /feed nav fails

            await context.storage_state(path=str(self._cookie_path))
            logger.info("linkedin_browser_login_saved", path=str(self._cookie_path))
            await browser.close()

            return oauth_code

    async def fetch_feed(self, *, limit: int = 20) -> list[FeedPost]:
        if not self._cookie_path.exists():
            raise LinkedInBrowserError(
                f"No saved LinkedIn session at {self._cookie_path}. "
                "Run: python apps/api/scripts/linkedin_login.py"
            )
        async with _browser_lock:
            return await self._do_fetch_feed(limit=limit)

    async def post_comment(self, post_url: str, text: str) -> str:
        if not self._cookie_path.exists():
            raise LinkedInBrowserError(
                f"No saved LinkedIn session at {self._cookie_path}. "
                "Run: python apps/api/scripts/linkedin_login.py"
            )
        async with _browser_lock:
            return await self._do_post_comment(post_url, text)

    # ── Internal: Feed ──

    async def _do_fetch_feed(self, *, limit: int = 20) -> list[FeedPost]:
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
                posts = await self._scrape_feed(page, limit=limit)
                await context.storage_state(path=str(self._cookie_path))
                return posts
            except LinkedInSessionExpiredError:
                raise
            except LinkedInBrowserError:
                raise
            except Exception as exc:
                await self._save_error_screenshot(page, "fetch_feed")
                raise LinkedInBrowserError(f"Feed fetch failed: {exc}") from exc
            finally:
                await browser.close()

    async def _scrape_feed(self, page, *, limit: int = 20) -> list[FeedPost]:
        logger.info("linkedin_browser_fetching_feed", limit=limit)

        await page.goto(
            "https://www.linkedin.com/feed/",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        await page.wait_for_timeout(random.randint(2000, 3500))

        if "/login" in page.url or "/checkpoint" in page.url:
            raise LinkedInSessionExpiredError(
                "LinkedIn session expired. Re-run login."
            )

        # Wait for feed posts to load
        try:
            await page.wait_for_selector(
                'div.feed-shared-update-v2, div[data-urn]', timeout=15_000
            )
        except Exception:
            await self._save_error_screenshot(page, "feed_no_posts")
            raise LinkedInBrowserError("No posts loaded on LinkedIn feed.")

        collected: list[FeedPost] = []
        seen_ids: set[str] = set()
        max_scrolls = 10
        scroll_count = 0

        while len(collected) < limit and scroll_count < max_scrolls:
            new_posts = await self._extract_posts_from_page(page, seen_ids)
            collected.extend(new_posts)
            logger.debug(
                "linkedin_browser_scroll_batch",
                new=len(new_posts),
                total=len(collected),
            )

            if len(collected) >= limit:
                break

            await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
            await page.wait_for_timeout(random.randint(1500, 2500))
            scroll_count += 1

            if len(new_posts) == 0 and scroll_count > 2:
                break

        logger.info("linkedin_browser_feed_fetched", count=len(collected))
        return collected[:limit]

    async def _extract_posts_from_page(
        self, page, seen_ids: set[str]
    ) -> list[FeedPost]:
        posts_data = await page.evaluate("""
            () => {
                const posts = [];
                // LinkedIn feed posts are in divs with data-urn attributes
                const updates = document.querySelectorAll(
                    'div.feed-shared-update-v2, div[data-urn*="activity"]'
                );

                for (const update of updates) {
                    try {
                        // Extract URN (unique ID)
                        const urn = update.getAttribute('data-urn') || '';
                        const activityMatch = urn.match(/activity:(\\d+)/);
                        const postId = activityMatch ? activityMatch[1] : '';
                        if (!postId) continue;

                        // Author name
                        const actorEl = update.querySelector(
                            '.update-components-actor__name span[dir="ltr"] span, ' +
                            '.feed-shared-actor__name span, ' +
                            'span.feed-shared-actor__title span'
                        );
                        const authorName = actorEl
                            ? actorEl.textContent.trim()
                            : 'Unknown';

                        // Author profile link → extract username
                        const profileLink = update.querySelector(
                            'a.update-components-actor__container-link, ' +
                            'a.feed-shared-actor__container-link, ' +
                            'a[data-control-name="actor_container"]'
                        );
                        let authorUsername = '';
                        if (profileLink) {
                            const href = profileLink.getAttribute('href') || '';
                            const uMatch = href.match(/\\/in\\/([^/?]+)/);
                            authorUsername = uMatch ? uMatch[1] : '';
                        }

                        // Avatar
                        const avatarImg = update.querySelector(
                            '.update-components-actor__image img, ' +
                            '.feed-shared-actor__avatar img, ' +
                            'img.EntityPhoto-circle-3'
                        );
                        const avatarUrl = avatarImg
                            ? avatarImg.getAttribute('src')
                            : null;

                        // Post text content
                        const textEl = update.querySelector(
                            '.feed-shared-update-v2__description, ' +
                            '.feed-shared-text, ' +
                            'div.update-components-text, ' +
                            'span.break-words'
                        );
                        const content = textEl
                            ? textEl.textContent.trim()
                            : '';

                        // Post URL
                        const postUrl = 'https://www.linkedin.com/feed/update/urn:li:activity:' + postId;

                        // Timestamp — LinkedIn shows relative times ("2h", "1d")
                        const timeEl = update.querySelector(
                            '.update-components-actor__sub-description span, ' +
                            '.feed-shared-actor__sub-description span, ' +
                            'time'
                        );
                        const timeText = timeEl ? timeEl.textContent.trim() : '';

                        posts.push({
                            postId,
                            authorName,
                            authorUsername,
                            avatarUrl,
                            content,
                            postUrl,
                            timeText,
                        });
                    } catch (e) {
                        // Skip malformed post
                    }
                }
                return posts;
            }
        """)

        result: list[FeedPost] = []
        for p in posts_data:
            post_id = p.get("postId", "")
            if not post_id or post_id in seen_ids:
                continue
            seen_ids.add(post_id)

            result.append(
                FeedPost(
                    platform_post_id=post_id,
                    author_name=p.get("authorName", "Unknown"),
                    author_username=p.get("authorUsername", ""),
                    author_avatar_url=p.get("avatarUrl"),
                    content=p.get("content", ""),
                    post_url=p.get("postUrl", ""),
                    posted_at=datetime.now(timezone.utc),
                )
            )
        return result

    # ── Internal: Comment ──

    async def _do_post_comment(self, post_url: str, text: str) -> str:
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
                comment_id = await self._navigate_and_comment(page, post_url, text)
                await context.storage_state(path=str(self._cookie_path))
                return comment_id
            except LinkedInSessionExpiredError:
                raise
            except LinkedInBrowserError:
                raise
            except Exception as exc:
                await self._save_error_screenshot(page, "post_comment")
                raise LinkedInBrowserError(f"Comment failed: {exc}") from exc
            finally:
                await browser.close()

    async def _navigate_and_comment(self, page, post_url: str, text: str) -> str:
        logger.info("linkedin_browser_navigating", url=post_url)

        await page.goto(post_url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(random.randint(1500, 3000))

        if "/login" in page.url or "/checkpoint" in page.url:
            raise LinkedInSessionExpiredError("LinkedIn session expired.")

        # Wait for post content
        try:
            await page.wait_for_selector(
                '.feed-shared-update-v2, div[data-urn], .scaffold-finite-scroll',
                timeout=15_000,
            )
        except Exception:
            await self._save_error_screenshot(page, "post_not_loaded")
            raise LinkedInBrowserError(f"Post did not load at {post_url}")

        # Click "Comment" button to open comment box (if not already open)
        comment_button = await page.query_selector(
            'button[aria-label*="Comment"], '
            'button[aria-label*="comment"], '
            'button.comment-button, '
            'button.social-actions-button[aria-label*="Comment"]'
        )
        if comment_button:
            await comment_button.click()
            await page.wait_for_timeout(random.randint(800, 1500))

        # Find the comment text box
        comment_box = None
        selectors = [
            'div.ql-editor[data-placeholder*="Add a comment"]',
            'div.ql-editor[role="textbox"]',
            'div[role="textbox"][aria-label*="comment"]',
            'div[role="textbox"][contenteditable="true"]',
            'div.comments-comment-texteditor div[role="textbox"]',
        ]
        for sel in selectors:
            try:
                comment_box = await page.wait_for_selector(sel, timeout=5_000)
                if comment_box:
                    break
            except Exception:
                continue

        if not comment_box:
            await self._save_error_screenshot(page, "no_comment_box")
            raise LinkedInBrowserError("Could not find comment text box.")

        await comment_box.click()
        await page.wait_for_timeout(random.randint(300, 600))

        # Type with human-like delays
        for char in text:
            await page.keyboard.type(char, delay=random.randint(30, 100))
            if random.random() < 0.05:
                await page.wait_for_timeout(random.randint(200, 400))

        await page.wait_for_timeout(random.randint(800, 1500))

        # Click submit button
        submit_selectors = [
            'button.comments-comment-box__submit-button',
            'button[data-control-name="comment_submit"]',
            'button[aria-label="Post comment"]',
            'button[type="submit"]',
        ]
        clicked = False
        for sel in submit_selectors:
            try:
                btn = await page.wait_for_selector(sel, timeout=3_000)
                if btn and await btn.is_enabled():
                    await btn.click()
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            # Try pressing Ctrl+Enter as fallback
            await page.keyboard.press("Control+Enter")

        await page.wait_for_timeout(3000)

        synthetic_id = f"li_browser_comment_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        logger.info("linkedin_browser_comment_posted", post_url=post_url, comment_id=synthetic_id)
        return synthetic_id

    # ── Utils ──

    async def _save_error_screenshot(self, page, context: str) -> None:
        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = f"/tmp/linkedin_browser_error_{context}_{timestamp}.png"
            await page.screenshot(path=path, full_page=False)
            logger.info("linkedin_browser_screenshot_saved", path=path)
        except Exception as exc:
            logger.warning("linkedin_browser_screenshot_failed", error=str(exc))
