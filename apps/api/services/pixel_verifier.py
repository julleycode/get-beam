"""Verify that the ReTargetAgent tracking pixel is installed on a website."""

import re
from typing import TypedDict

import httpx
import structlog

logger = structlog.get_logger()

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class VerifyResult(TypedDict):
    status: str  # verified | not_found | fetch_error
    verified: bool
    message: str


async def verify_pixel(url: str, site_id: str) -> VerifyResult:
    """Fetch a website URL and check if the ReTargetAgent pixel is installed."""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=15.0,
            headers={"User-Agent": BROWSER_UA},
            verify=False,
        ) as client:
            response = await client.get(url)
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
    has_correct_site = bool(
        re.search(rf'data-site="{re.escape(site_id)}"', html)
        or re.search(rf"data-site='{re.escape(site_id)}'", html)
        or re.search(rf"\?site={re.escape(site_id)}", html)
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
            status="not_found",
            verified=False,
            message="Found a ReTargetAgent pixel, but it's configured for a different site. Please check the site ID in your snippet.",
        )

    logger.info("pixel_not_found", url=url, site_id=site_id)
    return VerifyResult(
        status="not_found",
        verified=False,
        message="Pixel not found on your website. Make sure you've added the code snippet and saved your changes.",
    )
