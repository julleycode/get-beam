#!/usr/bin/env python3
"""Login to Twitter/X via browser and save cookies.

Usage:
    pip install playwright && playwright install chromium
    python apps/api/scripts/twitter_login.py

After login, this script:
1. Saves cookies to ~/.retarget/twitter_cookies.json
2. Prints a base64 string you can set as TWITTER_BROWSER_COOKIES_B64 on Railway
"""

import asyncio
import base64
import json
import re
import sys
from pathlib import Path


COOKIE_PATH = Path.home() / ".retarget" / "twitter_cookies.json"


async def main() -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Install playwright first: pip install playwright && playwright install chromium")
        sys.exit(1)

    COOKIE_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("\n🐦 Twitter/X Login — a browser window will open.")
    print("   Log in normally, then wait. Cookies are saved automatically.\n")

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
        await page.goto("https://x.com/login", wait_until="domcontentloaded")

        print("⏳ Waiting for you to log in (up to 10 minutes)...")
        try:
            await page.wait_for_url(
                re.compile(r"https://(x\.com|twitter\.com)/home"),
                timeout=600_000,
            )
        except Exception:
            print("❌ Login timed out. Please try again.")
            await browser.close()
            sys.exit(1)

        # Small delay for cookies to settle
        await page.wait_for_timeout(3000)

        # Save storage state
        await context.storage_state(path=str(COOKIE_PATH))
        await browser.close()

    # Read and encode for Railway env var
    raw = COOKIE_PATH.read_bytes()
    b64 = base64.b64encode(raw).decode()

    print(f"\n✅ Cookies saved to: {COOKIE_PATH}")
    print(f"\n📋 Set this on Railway:\n")
    print(f"railway variables --set \"TWITTER_BROWSER_COOKIES_B64={b64}\"")
    print(f"\n(String is {len(b64)} chars)")


if __name__ == "__main__":
    asyncio.run(main())
