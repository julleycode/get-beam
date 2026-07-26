"""Verify that the Beam tracking pixel is installed on a website."""

import re
from typing import TypedDict

import httpx
import structlog

from apps.api.services.url_guard import is_safe_public_url, safe_get

logger = structlog.get_logger()

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class VerifyResult(TypedDict):
    status: str  # verified | wrong_site | not_found | fetch_error
    verified: bool
    message: str


async def verify_pixel(url: str, site_id: str) -> VerifyResult:
    """Fetch a website URL and check if the Beam pixel is installed."""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    # SSRF guard: never let a user-supplied site URL point our fetch at an
    # internal / cloud-metadata address.
    if not await is_safe_public_url(url):
        logger.warning("pixel_verify_url_blocked", url=url, site_id=site_id)
        return VerifyResult(
            status="fetch_error",
            verified=False,
            message="Could not reach your website. Please check the URL is correct.",
        )

    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=15.0,
            headers={"User-Agent": BROWSER_UA},
        ) as client:
            response = await safe_get(client, url)
            html = response.text
    except httpx.TimeoutException:
        logger.warning("pixel_verify_timeout", url=url, site_id=site_id)
        return VerifyResult(
            status="fetch_error",
            verified=False,
            message="Could not reach your website (timeout). Please check the URL and try again.",
        )
    except Exception as e:
        logger.warning("pixel_verify_fetch_failed", url=url, error=str(e))
        return VerifyResult(
            status="fetch_error",
            verified=False,
            message=f"Could not reach your website. Please check the URL is correct.",
        )

    # Check for tracker.js with correct site_id
    # Match patterns:
    #   src="...tracker.js" data-site="site_abc123"
    #   src="...tracker.js?site=site_abc123"
    has_tracker = bool(re.search(r"tracker\.js", html))
    # The site id shows up in different shapes depending on how the snippet was
    # embedded; the raw HTML may never contain a plain data-site attribute:
    #   plain attr:        data-site="site_abc"  /  data-site='site_abc'
    #   src query param:   tracker.js?site=site_abc
    #   Pages Router JSON: "data-site":"site_abc"        (__NEXT_DATA__)
    #   App Router RSC:    data-site\":\"site_abc\"      (next/script injects the
    #                      tag client-side; HTML has only the escaped payload)
    # One windowed pattern covers every data-site shape: the key, a short run of
    # quote/backslash/colon/equals/space, then the id. The trailing lookahead
    # keeps site_abc from matching site_abcdef.
    id_pat = re.escape(site_id)
    has_correct_site = bool(
        re.search(rf'data-site[\\"\'=:\s]{{1,8}}{id_pat}(?![0-9a-zA-Z])', html)
        or re.search(rf"\?site={id_pat}(?![0-9a-zA-Z])", html)
    )

    if has_tracker and has_correct_site:
        logger.info("pixel_verified", url=url, site_id=site_id)
        return VerifyResult(
            status="verified",
            verified=True,
            message="Pixel is installed and working correctly!",
        )

    if has_tracker and not has_correct_site:
        logger.info("pixel_wrong_site", url=url, site_id=site_id)
        return VerifyResult(
            status="wrong_site",
            verified=False,
            message="A Beam pixel was found, but its Site ID does not match this site. "
            "Make sure you installed the snippet generated for THIS site.",
        )

    logger.info("pixel_not_found", url=url, site_id=site_id)
    return VerifyResult(
        status="not_found",
        verified=False,
        message="Pixel not found on your website. Make sure you've added the code snippet and saved your changes.",
    )
