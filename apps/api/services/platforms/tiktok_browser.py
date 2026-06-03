"""TikTok browser automation via Playwright.

Bypasses TikTok API limitations:
- Comment API only works on own videos → browser enables commenting on any video
- Feed API returns own videos only → browser scrapes Following/ForYou feed

Same pattern as twitter_browser.py / linkedin_browser.py.
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


class TikTokBrowserError(Exception):
    pass


class TikTokSessionExpiredError(TikTokBrowserError):
    pass


class TikTokBrowserPoster:
    """Scrapes TikTok feed and posts comments via Playwright."""

    def __init__(self) -> None:
        self._cookie_path = Path(
            os.path.expanduser(settings.tiktok_browser_cookie_path)
        )
        self._headless = settings.tiktok_browser_headless
        self._hydrate_cookies_from_env()

    def _hydrate_cookies_from_env(self) -> None:
        if self._cookie_path.exists():
            return
        b64_data = settings.tiktok_browser_cookies_b64
        if not b64_data:
            return
        import base64
        try:
            raw = base64.b64decode(b64_data)
            self._cookie_path.parent.mkdir(parents=True, exist_ok=True)
            self._cookie_path.write_bytes(raw)
            logger.info("tiktok_browser_cookies_hydrated", path=str(self._cookie_path))
        except Exception:
            logger.exception("tiktok_browser_cookies_hydration_failed")

    # ── Public API ──

    async def setup_login(self, oauth_url: str | None = None) -> str | None:
        """Launch headed browser for manual TikTok login. Saves cookies.

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

        start_url = oauth_url or "https://www.tiktok.com/login"
        # If using OAuth, we wait for the callback redirect; otherwise wait for /foryou
        wait_pattern = (
            re.compile(r".*/api/v1/social/callback/tiktok\?")
            if oauth_url
            else re.compile(r"https://www\.tiktok\.com/(foryou|following|@)")
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
                async def intercept_callback(route):
                    nonlocal oauth_code
                    url = route.request.url
                    from urllib.parse import urlparse, parse_qs
                    parsed = urlparse(url)
                    qs = parse_qs(parsed.query)
                    if "code" in qs:
                        oauth_code = qs["code"][0]
                        logger.info("tiktok_browser_oauth_code_captured")
                    await route.continue_()

                await page.route("**/api/v1/social/callback/tiktok*", intercept_callback)

            logger.info("tiktok_browser_login_starting", url=start_url)
            await page.goto(start_url, wait_until="domcontentloaded")

            # Wait for user to log in — detect landing on /foryou or callback
            try:
                await page.wait_for_url(wait_pattern, timeout=600_000)
            except Exception:
                logger.error("tiktok_browser_login_timeout")
                await browser.close()
                raise TikTokBrowserError("Login timed out after 10 minutes.")

            await page.wait_for_timeout(2000)

            # If OAuth flow, navigate to TikTok to establish full session cookies
            if oauth_url and oauth_code:
                try:
                    await page.goto(
                        "https://www.tiktok.com/following",
                        wait_until="domcontentloaded",
                        timeout=15_000,
                    )
                    await page.wait_for_timeout(2000)
                except Exception:
                    pass  # Cookie saving still works even if nav fails

            await context.storage_state(path=str(self._cookie_path))
            logger.info("tiktok_browser_login_saved", path=str(self._cookie_path))
            await browser.close()

            return oauth_code

    async def fetch_feed(self, *, limit: int = 20) -> list[FeedPost]:
        if not self._cookie_path.exists():
            raise TikTokBrowserError(
                f"No saved TikTok session at {self._cookie_path}. "
                "Run: python apps/api/scripts/tiktok_login.py"
            )
        async with _browser_lock:
            return await self._do_fetch_feed(limit=limit)

    async def post_comment(self, video_url: str, text: str) -> str:
        if not self._cookie_path.exists():
            raise TikTokBrowserError(
                f"No saved TikTok session at {self._cookie_path}. "
                "Run: python apps/api/scripts/tiktok_login.py"
            )
        async with _browser_lock:
            return await self._do_post_comment(video_url, text)

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
            except TikTokSessionExpiredError:
                raise
            except TikTokBrowserError:
                raise
            except Exception as exc:
                await self._save_error_screenshot(page, "fetch_feed")
                raise TikTokBrowserError(f"Feed fetch failed: {exc}") from exc
            finally:
                await browser.close()

    async def _scrape_feed(self, page, *, limit: int = 20) -> list[FeedPost]:
        logger.info("tiktok_browser_fetching_feed", limit=limit)

        await page.goto(
            "https://www.tiktok.com/following",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        await page.wait_for_timeout(random.randint(2000, 4000))

        # TikTok doesn't always redirect to /login — it shows the page
        # with a login sidebar/modal. Check both URL and page content.
        if "/login" in page.url:
            raise TikTokSessionExpiredError("TikTok session expired.")

        # Check if we're not actually logged in (sidebar shows "Log In" button
        # and no personalized content is loaded)
        is_logged_in = await page.evaluate("""
            () => {
                // If there's a login button prominently displayed, user is not logged in
                const loginBtn = document.querySelector(
                    'a[href*="/login"], button[data-e2e="top-login-button"]'
                );
                // Check for avatar/profile indicators (logged-in state)
                const avatar = document.querySelector(
                    '[data-e2e="profile-icon"], [class*="avatar"]'
                );
                // If login button exists and no avatar, probably not logged in
                if (loginBtn && !avatar) return false;
                return true;
            }
        """)
        if not is_logged_in:
            raise TikTokSessionExpiredError(
                "TikTok session expired or not logged in. "
                "Run: python apps/api/scripts/tiktok_login.py"
            )

        # Wait for video items to load
        try:
            await page.wait_for_selector(
                'div[data-e2e="recommend-list-item-container"], '
                'div[class*="DivItemContainer"], '
                'div[class*="video-feed-item"]',
                timeout=15_000,
            )
        except Exception:
            await self._save_error_screenshot(page, "feed_no_videos")
            raise TikTokBrowserError("No videos loaded on TikTok feed.")

        collected: list[FeedPost] = []
        seen_ids: set[str] = set()
        max_scrolls = 10
        scroll_count = 0

        while len(collected) < limit and scroll_count < max_scrolls:
            new_posts = await self._extract_videos_from_page(page, seen_ids)
            collected.extend(new_posts)

            if len(collected) >= limit:
                break

            await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
            await page.wait_for_timeout(random.randint(1500, 2500))
            scroll_count += 1

            if len(new_posts) == 0 and scroll_count > 2:
                break

        logger.info("tiktok_browser_feed_fetched", count=len(collected))
        return collected[:limit]

    async def _extract_videos_from_page(
        self, page, seen_ids: set[str]
    ) -> list[FeedPost]:
        videos_data = await page.evaluate("""
            () => {
                const videos = [];
                // TikTok feed items
                const items = document.querySelectorAll(
                    'div[data-e2e="recommend-list-item-container"], ' +
                    'div[class*="DivItemContainer"]'
                );

                for (const item of items) {
                    try {
                        // Video link → extract ID
                        const videoLink = item.querySelector(
                            'a[href*="/video/"]'
                        );
                        if (!videoLink) continue;

                        const href = videoLink.getAttribute('href') || '';
                        const vidMatch = href.match(/\\/@([^/]+)\\/video\\/(\\d+)/);
                        if (!vidMatch) continue;

                        const authorUsername = vidMatch[1];
                        const videoId = vidMatch[2];

                        // Author display name
                        const nameEl = item.querySelector(
                            '[data-e2e="video-author-uniqueid"], ' +
                            'a[data-e2e="video-author-avatar"] + * span, ' +
                            'h3[data-e2e="video-author-uniqueid"]'
                        );
                        const authorName = nameEl
                            ? nameEl.textContent.trim()
                            : authorUsername;

                        // Avatar
                        const avatarImg = item.querySelector(
                            'a[data-e2e="video-author-avatar"] img, ' +
                            'img[class*="ImgAvatar"]'
                        );
                        const avatarUrl = avatarImg
                            ? avatarImg.getAttribute('src')
                            : null;

                        // Caption / description
                        const captionEl = item.querySelector(
                            '[data-e2e="video-desc"], ' +
                            'div[class*="DivVideoDesc"] span, ' +
                            'h1[data-e2e="video-desc"]'
                        );
                        const content = captionEl
                            ? captionEl.textContent.trim()
                            : '';

                        const postUrl = href.startsWith('http')
                            ? href
                            : 'https://www.tiktok.com' + href;

                        videos.push({
                            videoId,
                            authorUsername,
                            authorName,
                            avatarUrl,
                            content,
                            postUrl,
                        });
                    } catch (e) {
                        // Skip malformed item
                    }
                }
                return videos;
            }
        """)

        result: list[FeedPost] = []
        for v in videos_data:
            vid_id = v.get("videoId", "")
            if not vid_id or vid_id in seen_ids:
                continue
            seen_ids.add(vid_id)

            result.append(
                FeedPost(
                    platform_post_id=vid_id,
                    author_name=v.get("authorName", ""),
                    author_username=v.get("authorUsername", ""),
                    author_avatar_url=v.get("avatarUrl"),
                    content=v.get("content", ""),
                    post_url=v.get("postUrl", ""),
                    posted_at=datetime.now(timezone.utc),
                )
            )
        return result

    # ── Internal: Comment ──

    async def _do_post_comment(self, video_url: str, text: str) -> str:
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
                comment_id = await self._navigate_and_comment(page, video_url, text)
                await context.storage_state(path=str(self._cookie_path))
                return comment_id
            except TikTokSessionExpiredError:
                raise
            except TikTokBrowserError:
                raise
            except Exception as exc:
                await self._save_error_screenshot(page, "post_comment")
                raise TikTokBrowserError(f"Comment failed: {exc}") from exc
            finally:
                await browser.close()

    async def _navigate_and_comment(self, page, video_url: str, text: str) -> str:
        logger.info("tiktok_browser_navigating", url=video_url)

        await page.goto(video_url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(random.randint(2000, 3500))

        if "/login" in page.url:
            raise TikTokSessionExpiredError("TikTok session expired.")

        # Check for login modal overlay
        has_login_modal = await page.evaluate("""
            () => {
                const modal = document.querySelector(
                    'div[class*="LoginModal"], div[data-e2e="modal-overlay"]'
                );
                return !!modal;
            }
        """)
        if has_login_modal:
            raise TikTokSessionExpiredError("TikTok login modal detected.")

        # Wait for video to load
        try:
            await page.wait_for_selector('video, div[class*="DivVideoContainer"]', timeout=15_000)
        except Exception:
            await self._save_error_screenshot(page, "video_not_loaded")
            raise TikTokBrowserError(f"Video did not load at {video_url}")

        # Find comment input
        comment_box = None
        selectors = [
            'div[data-e2e="comment-input"] div[contenteditable="true"]',
            'div[class*="DivInputEditorContainer"] div[contenteditable="true"]',
            'div[role="textbox"][contenteditable="true"]',
            'div[data-e2e="comment-input"]',
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
            raise TikTokBrowserError("Could not find comment input.")

        await comment_box.click()
        await page.wait_for_timeout(random.randint(300, 600))

        for char in text:
            await page.keyboard.type(char, delay=random.randint(30, 100))
            if random.random() < 0.05:
                await page.wait_for_timeout(random.randint(200, 400))

        await page.wait_for_timeout(random.randint(800, 1500))

        # Click post button
        submit_selectors = [
            'div[data-e2e="comment-post"]',
            'button[data-e2e="comment-post"]',
            'div[class*="DivPostButton"]',
        ]
        clicked = False
        for sel in submit_selectors:
            try:
                btn = await page.wait_for_selector(sel, timeout=3_000)
                if btn:
                    await btn.click()
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            await page.keyboard.press("Enter")

        await page.wait_for_timeout(3000)

        synthetic_id = f"tt_browser_comment_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        logger.info("tiktok_browser_comment_posted", video_url=video_url, comment_id=synthetic_id)
        return synthetic_id

    # ── Utils ──

    async def _save_error_screenshot(self, page, context: str) -> None:
        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = f"/tmp/tiktok_browser_error_{context}_{timestamp}.png"
            await page.screenshot(path=path, full_page=False)
            logger.info("tiktok_browser_screenshot_saved", path=path)
        except Exception as exc:
            logger.warning("tiktok_browser_screenshot_failed", error=str(exc))
