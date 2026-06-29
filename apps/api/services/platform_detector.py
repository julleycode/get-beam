"""Detect which platform a website is built on by fetching its HTML."""

import re
from typing import TypedDict

import httpx
import structlog

from apps.api.services.url_guard import is_safe_public_url, safe_get

logger = structlog.get_logger()

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

BROWSER_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}


class PlatformResult(TypedDict):
    platform: str  # shopify | wordpress | wix | squarespace | webflow | unknown
    confidence: float  # 0.0 - 1.0
    has_gtm: bool
    gtm_id: str | None


def _detect_shopify(html: str, headers: dict[str, str]) -> float:
    score = 0.0
    if "cdn.shopify.com" in html:
        score += 0.4
    if "Shopify.theme" in html or "Shopify.shop" in html:
        score += 0.3
    if re.search(r'<meta\s+name="shopify', html, re.IGNORECASE):
        score += 0.2
    if headers.get("x-shopid") or headers.get("x-shopify-stage"):
        score += 0.3
    return min(score, 1.0)


def _detect_wordpress(html: str, headers: dict[str, str]) -> float:
    score = 0.0
    if re.search(r'<meta\s+name="generator"\s+content="WordPress', html, re.IGNORECASE):
        score += 0.5
    if "/wp-content/" in html or "/wp-includes/" in html:
        score += 0.3
    if "wp-emoji-release" in html:
        score += 0.1
    if headers.get("x-powered-by", "").startswith("WP"):
        score += 0.2
    if "wp-json" in html or "/xmlrpc.php" in html:
        score += 0.1
    return min(score, 1.0)


def _detect_wix(html: str, headers: dict[str, str]) -> float:
    score = 0.0
    if re.search(r'<meta\s+name="generator"\s+content="Wix', html, re.IGNORECASE):
        score += 0.5
    if "static.wixstatic.com" in html:
        score += 0.3
    if "wix-code-sdk" in html or "wixstatic" in html:
        score += 0.2
    if headers.get("x-wix-request-id"):
        score += 0.3
    return min(score, 1.0)


def _detect_squarespace(html: str, headers: dict[str, str]) -> float:
    score = 0.0
    if re.search(r'<meta\s+name="generator"\s+content="Squarespace', html, re.IGNORECASE):
        score += 0.5
    if "static1.squarespace.com" in html or "static.squarespace.com" in html:
        score += 0.3
    if "<!-- This is Squarespace" in html:
        score += 0.3
    if "squarespace-cdn" in html:
        score += 0.2
    return min(score, 1.0)


def _detect_webflow(html: str, headers: dict[str, str]) -> float:
    score = 0.0
    if re.search(r'<meta\s+name="generator"\s+content="Webflow', html, re.IGNORECASE):
        score += 0.5
    if "data-wf-page" in html or "data-wf-site" in html:
        score += 0.3
    if "assets.website-files.com" in html or "assets-global.website-files.com" in html:
        score += 0.2
    if "webflow" in headers.get("server", "").lower():
        score += 0.2
    return min(score, 1.0)


def _detect_gtm(html: str) -> tuple[bool, str | None]:
    """Check if Google Tag Manager is installed and extract container ID."""
    match = re.search(r"googletagmanager\.com/gtm\.js\?id=(GTM-[A-Z0-9]+)", html)
    if match:
        return True, match.group(1)
    match = re.search(r"googletagmanager\.com/ns\.html\?id=(GTM-[A-Z0-9]+)", html)
    if match:
        return True, match.group(1)
    return False, None


async def _probe_shopify_api(client: httpx.AsyncClient, base_url: str) -> bool:
    """Check Shopify-exclusive API endpoints (/cart.js, /products.json)."""
    base = base_url.rstrip("/")
    try:
        r = await client.get(f"{base}/cart.js", timeout=5.0)
        if r.status_code == 200 and "items" in r.text[:500]:
            return True
    except Exception:
        pass
    try:
        r = await client.get(f"{base}/products.json?limit=1", timeout=5.0)
        if r.status_code == 200 and "products" in r.text[:500]:
            return True
    except Exception:
        pass
    return False


async def detect_platform(url: str) -> PlatformResult:
    """Fetch a URL and detect which platform the website runs on."""
    # Normalize URL
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    # SSRF guard: refuse private/loopback/link-local/metadata targets before the
    # server makes any outbound request on a user-supplied URL.
    if not await is_safe_public_url(url):
        logger.warning("platform_detect_url_blocked", url=url)
        return PlatformResult(
            platform="unknown", confidence=0.0, has_gtm=False, gtm_id=None
        )

    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=15.0,
            headers=BROWSER_HEADERS,
        ) as client:
            response = await safe_get(client, url)
            html = response.text
            headers = {k.lower(): v for k, v in response.headers.items()}

            # If we got a 403/challenge page, still check headers for platform clues
            if response.status_code == 403:
                if headers.get("x-shopid") or headers.get("x-shopify-stage"):
                    logger.info("platform_detected_from_headers", url=url, platform="shopify")
                    has_gtm, gtm_id = _detect_gtm(html)
                    return PlatformResult(
                        platform="shopify", confidence=0.8, has_gtm=has_gtm, gtm_id=gtm_id
                    )
                if "shopify" in html.lower():
                    has_gtm, gtm_id = _detect_gtm(html)
                    return PlatformResult(
                        platform="shopify", confidence=0.6, has_gtm=has_gtm, gtm_id=gtm_id
                    )
    except Exception as e:
        logger.warning("platform_detect_fetch_failed", url=url, error=str(e))
        return PlatformResult(
            platform="unknown", confidence=0.0, has_gtm=False, gtm_id=None
        )

    # Detect each platform
    scores: dict[str, float] = {
        "shopify": _detect_shopify(html, headers),
        "wordpress": _detect_wordpress(html, headers),
        "wix": _detect_wix(html, headers),
        "squarespace": _detect_squarespace(html, headers),
        "webflow": _detect_webflow(html, headers),
    }

    # Pick highest score
    best_platform = max(scores, key=scores.get)  # type: ignore[arg-type]
    best_score = scores[best_platform]

    # Detect GTM
    has_gtm, gtm_id = _detect_gtm(html)

    # If no platform detected with high confidence, try Shopify API probe
    if best_score < 0.3:
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=10.0,
                headers=BROWSER_HEADERS,
            ) as client:
                if await _probe_shopify_api(client, url):
                    best_platform = "shopify"
                    best_score = 0.7
                    logger.info("shopify_detected_via_api_probe", url=url)
        except Exception:
            pass

    if best_score < 0.2:
        best_platform = "unknown"
        best_score = 0.0

    logger.info(
        "platform_detected",
        url=url,
        platform=best_platform,
        confidence=best_score,
        has_gtm=has_gtm,
        scores={k: v for k, v in scores.items() if v > 0},
    )

    return PlatformResult(
        platform=best_platform,
        confidence=round(best_score, 2),
        has_gtm=has_gtm,
        gtm_id=gtm_id,
    )
