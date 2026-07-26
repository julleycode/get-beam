"""Verify that the Beam tracking pixel is installed on a website."""

import re
from datetime import datetime, timedelta, timezone
from typing import TypedDict

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.url_guard import is_safe_public_url, pinned_client, safe_get

logger = structlog.get_logger()

# How far back live traffic counts as proof the pixel is installed.
# Rationale: low-traffic indie sites routinely go several days without a single
# pageview, so a 24h window would flap. A week is short enough that a REMOVED
# pixel stops verifying at the next check, and long enough that a real but
# quiet site is never told "not installed" while it is plainly sending events.
# Deliberately a module constant, not a Settings field — no config churn.
EVENT_PROOF_WINDOW_DAYS = 7

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class VerifyResult(TypedDict):
    status: str  # verified | wrong_site | not_found | fetch_error
    verified: bool
    message: str


async def verify_pixel(
    url: str, site_id: str, db: AsyncSession | None = None
) -> VerifyResult:
    """Verify the Beam pixel is installed on ``url``.

    Two-stage check:
      1. static — fetch the HTML and look for tracker.js + this site's id.
      2. event fallback (only when ``db`` is given and stage 1 did NOT verify) —
         if the site sent us events recently, the pixel is demonstrably running
         even though we could not see it in the served HTML.

    ``db`` is optional so existing callers (and tests) keep working unchanged.
    """
    static = await _verify_pixel_static(url, site_id)

    # Fast path: a static match is proof enough — never touch the DB.
    if static["verified"] or db is None:
        return static

    return await _verify_via_events(db, site_id, static)


async def _verify_via_events(
    db: AsyncSession, site_id: str, static: VerifyResult
) -> VerifyResult:
    """Fall back to live traffic as proof of install.

    Static regex matching structurally cannot see installs that never appear in
    the served HTML: GTM Custom HTML tags, JS-only SPA injection, iframe site
    builders, or any origin behind a bot challenge (we get the interstitial, not
    the page). All of those still send events. Applies on fetch_error too — a
    Cloudflare-challenged site with flowing traffic is installed.
    """
    try:
        # Local import: matches the local-import pattern in routers/events.py
        # and keeps services/ free of a module-level dependency on models/.
        from apps.api.models.event import Event

        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            days=EVENT_PROOF_WINDOW_DAYS
        )
        # Uses the existing ix_events_site_created index.
        result = await db.execute(
            select(Event.id)
            .where(Event.site_id == site_id, Event.created_at >= cutoff)
            .limit(1)
        )
        row = result.scalar_one_or_none()
    except Exception as e:
        logger.warning("pixel_verify_event_fallback_failed", site_id=site_id, error=str(e))
        return static

    if row is None:
        return static

    logger.info("pixel_verified_via_events", site_id=site_id, static_status=static["status"])
    return VerifyResult(
        status="verified",
        verified=True,
        message="Pixel verified via live traffic — your site is sending events.",
    )


async def _verify_pixel_static(url: str, site_id: str) -> VerifyResult:
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
        # pinned_client (not a bare AsyncClient): each redirect hop connects to
        # the IP the SSRF guard validated, closing the DNS-rebinding TOCTOU.
        async with pinned_client(
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
    #   entity-escaped:    data-site=&quot;site_abc&quot;  /  &#34; / &#39;
    #   array pair:        ["data-site","site_abc"]
    # The key is matched case-insensitively via a SCOPED inline flag — HTML
    # attribute names are case-insensitive, but the site id is NOT (only the
    # key gets (?i:...), never the id).
    # The window between key and id allows quote/backslash/colon/equals/space/
    # comma AND whole HTML entity sequences, repeated — that covers entity
    # escaping and deep-indented multiline snippets alike. We deliberately do
    # NOT html.unescape() the whole document: that would turn documentation
    # blocks (&lt;script ...&gt;) into real-looking tags and manufacture false
    # verifieds well beyond the single accepted case documented in the tests.
    id_pat = re.escape(site_id)
    _win = r'(?:&quot;|&apos;|&#0*3[49];|[\\"\'=:\s,]){1,12}'
    has_correct_site = bool(
        re.search(rf"(?i:data-site){_win}{id_pat}(?![0-9a-zA-Z])", html)
        # query param: ? or & or an entity-escaped & before site=
        or re.search(rf"(?:[?&]|&amp;|&#0*38;)site={id_pat}(?![0-9a-zA-Z])", html)
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
