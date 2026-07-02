"""Scan an installed Beam pixel and report which detection signals are active.

Fetches the site's HTML once (SSRF-guarded, like pixel_verifier) and derives
each signal from what the tracker snippet actually enables. Signals fall into
three buckets:

- always-on capabilities that light up as soon as the pixel is installed
  (SPA tracking, offline queue, fingerprint, persistent ID, GPC respect)
- install-dependent options read off the script tag itself
  (async loading, data-consent, data-stack, first-party src)
- page facts (forms present -> email capture has something to capture)

On any fetch failure the full signal list is still returned with every signal
inactive, so the onboarding UI can always render "N of M active".
"""

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


class DetectionSignal(TypedDict):
    key: str
    name: str
    category: str
    active: bool
    description: str


def _build_signals(
    *,
    installed: bool,
    async_load: bool,
    first_party: bool,
    consent_on: bool,
    stack_on: bool,
    has_forms: bool,
) -> list[DetectionSignal]:
    return [
        # ── Tracking ──
        DetectionSignal(
            key="pixel_installed",
            name="Beam pixel",
            category="Tracking",
            active=installed,
            description="Tracking script found with the correct Site ID",
        ),
        DetectionSignal(
            key="spa_tracking",
            name="SPA route tracking",
            category="Tracking",
            active=installed,
            description="Client-side route changes are tracked as pageviews",
        ),
        DetectionSignal(
            key="offline_queue",
            name="Offline event queue",
            category="Tracking",
            active=installed,
            description="Events queue locally and flush when the connection returns",
        ),
        DetectionSignal(
            key="async_loading",
            name="Non-blocking load",
            category="Tracking",
            active=installed and async_load,
            description="Script loads async so it never slows your page",
        ),
        # ── Identification ──
        DetectionSignal(
            key="persistent_id",
            name="Persistent visitor ID",
            category="Identification",
            active=installed,
            description="Cookie + localStorage fallback keeps identity across sessions",
        ),
        DetectionSignal(
            key="device_fingerprint",
            name="Device fingerprint",
            category="Identification",
            active=installed,
            description="Stable device signature re-recognizes returning visitors",
        ),
        DetectionSignal(
            key="form_capture",
            name="Form email capture",
            category="Identification",
            active=installed and has_forms,
            description="Forms detected — submitted emails identify visitors directly",
        ),
        DetectionSignal(
            key="identity_stack",
            name="Identity vendor stack",
            category="Identification",
            active=installed and stack_on,
            description="Optional third-party identity vendors (data-stack)",
        ),
        DetectionSignal(
            key="first_party",
            name="First-party serving",
            category="Identification",
            active=installed and first_party,
            description="Pixel served from your own domain — resists Safari ITP",
        ),
        # ── Privacy ──
        DetectionSignal(
            key="consent_banner",
            name="Consent banner",
            category="Privacy",
            active=installed and consent_on,
            description="EU-gated cookie consent prompt (data-consent)",
        ),
        DetectionSignal(
            key="gpc_respect",
            name="GPC / DNT respected",
            category="Privacy",
            active=installed,
            description="Visitors with Global Privacy Control or DNT are never tracked",
        ),
    ]


def _host_of(url: str) -> str:
    try:
        host = httpx.URL(url).host or ""
    except Exception:
        return ""
    return host.lower().removeprefix("www.")


def _signals_from_html(html: str, site_id: str, site_url: str) -> list[DetectionSignal]:
    """Pure HTML -> signals derivation (separable for unit tests)."""
    tag_match = re.search(r"<script\b[^>]*tracker(?:\.min)?\.js[^>]*>", html, re.I)
    tag = tag_match.group(0) if tag_match else ""

    has_correct_site = bool(
        re.search(rf'data-site="{re.escape(site_id)}"', html)
        or re.search(rf"data-site='{re.escape(site_id)}'", html)
        or re.search(rf"\?site={re.escape(site_id)}", html)
    )
    installed = bool(tag) and has_correct_site

    async_load = bool(re.search(r"\b(async|defer)\b", tag, re.I))

    consent_match = re.search(r"""data-consent=["']?(\w+)""", tag, re.I)
    consent_on = bool(consent_match) and consent_match.group(1).lower() in (
        "eu",
        "all",
        "cmp",
    )

    stack_on = bool(re.search(r"""data-stack=["']?1""", tag))

    src_match = re.search(r"""src=["']([^"']+)""", tag, re.I)
    first_party = bool(
        src_match
        and _host_of(src_match.group(1))
        and _host_of(src_match.group(1)) == _host_of(site_url)
    )

    has_forms = bool(re.search(r"<form\b", html, re.I))

    return _build_signals(
        installed=installed,
        async_load=async_load,
        first_party=first_party,
        consent_on=consent_on,
        stack_on=stack_on,
        has_forms=has_forms,
    )


def _all_inactive() -> list[DetectionSignal]:
    return _build_signals(
        installed=False,
        async_load=False,
        first_party=False,
        consent_on=False,
        stack_on=False,
        has_forms=False,
    )


async def scan_detection_signals(url: str, site_id: str) -> list[DetectionSignal]:
    """Fetch a website and report which Beam detection signals are active."""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    # SSRF guard: never let a user-supplied site URL point our fetch at an
    # internal / cloud-metadata address.
    if not await is_safe_public_url(url):
        logger.warning("detection_scan_url_blocked", url=url, site_id=site_id)
        return _all_inactive()

    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=15.0,
            headers={"User-Agent": BROWSER_UA},
        ) as client:
            response = await safe_get(client, url)
            html = response.text
    except Exception as e:
        logger.warning(
            "detection_scan_fetch_failed", url=url, site_id=site_id, error=str(e)
        )
        return _all_inactive()

    signals = _signals_from_html(html, site_id, url)
    logger.info(
        "detection_scan_done",
        site_id=site_id,
        active=sum(1 for s in signals if s["active"]),
        total=len(signals),
    )
    return signals
