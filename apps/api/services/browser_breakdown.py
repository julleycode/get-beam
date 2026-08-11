"""Per-browser capture breakdown + Safari-coverage estimate.

Answers "is our pixel being blocked on Safari/iOS?" — the signal that decides
whether a first-party install is worth building. Two views:

1. Per-browser captured + identified counts (the survivors).
2. A geo-weighted Safari-coverage estimate: compare the Safari share we *did*
   capture against the share expected for this site's country mix. A big
   shortfall = ITP / content-blockers eating Safari visitors before they ever
   fire an event (the casualties — invisible in the raw counts).

Browser comes from `Event.user_agent`; identification from
`Visitor.identity_status`; geo from `Visitor.country_code` (already resolved).
"""

from datetime import datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.event import Event
from apps.api.models.visitor import Visitor

logger = structlog.get_logger()

# Below this many captured visitors the Safari-coverage estimate is noise.
MIN_SAMPLE = 100

# The bucket `classify_browser` returns for Chrome/Chromium, and the label used
# when that bucket is known to be farbling its fingerprint. Named constants so
# the relabel in the caller can never drift from the classifier's own vocabulary.
CHROMIUM_FAMILY = "Chrome"
FARBLED_FAMILY = "Chrome (farbled)"

# Approximate all-platform Safari usage share by country (StatCounter, mid-2026).
# Static v1 — refresh from the monthly StatCounter CSV. The exact values matter
# less than the directional shortfall vs what we actually capture.
GLOBAL_SAFARI_BASELINE = 0.19
SAFARI_BASELINE: dict[str, float] = {
    "US": 0.31, "CA": 0.30, "GB": 0.30, "IE": 0.33, "AU": 0.38, "NZ": 0.36,
    "JP": 0.32, "CH": 0.28, "DK": 0.30, "NO": 0.28, "SE": 0.25, "NL": 0.22,
    "FR": 0.20, "IT": 0.20, "ES": 0.20, "DE": 0.18, "AT": 0.20, "BE": 0.22,
    "FI": 0.24, "SG": 0.30, "HK": 0.30, "AE": 0.28,
    "BR": 0.14, "MX": 0.14, "IN": 0.13, "ID": 0.10, "RU": 0.16, "CN": 0.16,
    "KR": 0.16, "ZA": 0.16, "PL": 0.10, "TR": 0.12, "VN": 0.20, "TH": 0.16,
}


def classify_browser(ua: str) -> str:
    """Map a User-Agent to a brand family. Order matters: Edge/Opera/Samsung
    and iOS-Chrome all carry "Chrome", and Chrome carries "Safari", so the
    specific tokens must be tested before the generic ones."""
    u = (ua or "").lower()
    if not u:
        return "Unknown"
    if "edg" in u:  # Edg/, EdgiOS, EdgA
        return "Edge"
    if "opr/" in u or "opera" in u:
        return "Opera"
    if "samsungbrowser" in u:
        return "Samsung Internet"
    if "fxios" in u or "firefox" in u:
        return "Firefox"
    if "crios" in u:  # iOS Chrome — brand Chrome (note: WebKit engine under the hood)
        return "Chrome"
    if "chrome" in u or "chromium" in u:
        return "Chrome"
    if "safari" in u:  # only reached when not Chrome-family above
        return "Safari"
    return "Other"


def _coverage_status(total: int, ratio: float | None) -> tuple[str, str]:
    """Map the captured-vs-expected Safari ratio to a status + message."""
    if total < MIN_SAMPLE or ratio is None:
        return (
            "insufficient_data",
            f"Need at least {MIN_SAMPLE} captured visitors to estimate Safari "
            "coverage reliably.",
        )
    pct = round(ratio * 100)
    if ratio < 0.6:
        return (
            "likely_blocked",
            f"Capturing only ~{pct}% of the Safari visitors expected for your "
            "geo mix — likely ITP / content-blockers dropping the pixel. A "
            "first-party install would recover most of them.",
        )
    if ratio < 0.85:
        return (
            "watch",
            f"Safari capture is ~{pct}% of expected — some erosion, worth "
            "watching. Not yet a clear first-party trigger.",
        )
    return ("ok", "Safari capture is in line with your geo mix — no blocking signal.")


async def compute_browser_breakdown(
    db: AsyncSession, site_id: str, window_days: int = 30
) -> dict:
    """Per-browser captured/identified counts + a geo-weighted Safari-coverage
    estimate for one site over the trailing `window_days`."""
    since = datetime.utcnow() - timedelta(days=window_days)

    # Latest User-Agent per visitor (one row each) within the window.
    ua_rows = (
        await db.execute(
            select(Event.visitor_id, Event.user_agent)
            .where(Event.site_id == site_id, Event.created_at >= since)
            .distinct(Event.visitor_id)
            .order_by(Event.visitor_id, Event.created_at.desc())
        )
    ).all()
    ua_by_visitor = {vid: ua for vid, ua in ua_rows}

    # Each captured visitor with its identity status + resolved country, plus
    # the two privacy-shaped flags. Both ride along on the SAME query — no extra
    # round-trip, no join, no index: this is the only place in the codebase that
    # already pairs a browser family with a visitor row.
    v_rows = (
        await db.execute(
            select(
                Visitor.visitor_id,
                Visitor.identity_status,
                Visitor.country_code,
                Visitor.do_not_resolve,
                Visitor.has_unstable_fingerprint,
            ).where(Visitor.site_id == site_id, Visitor.last_seen >= since)
        )
    ).all()

    browsers: dict[str, dict[str, int]] = {}
    country_counts: dict[str, int] = {}
    total_opted_out = 0
    for (
        visitor_id,
        identity_status,
        country_code,
        do_not_resolve,
        has_unstable_fp,
    ) in v_rows:
        family = classify_browser(ua_by_visitor.get(visitor_id, ""))
        # Farbling browsers (Brave, Firefox RFP, CanvasBlocker, Tor) are
        # indistinguishable from plain Chrome by UA alone — Brave ships a
        # byte-identical UA. Relabel from the OBSERVED property, never the
        # vendor: the same bucket holds several unrelated products.
        if has_unstable_fp and family == CHROMIUM_FAMILY:
            family = FARBLED_FAMILY
        bucket = browsers.setdefault(
            family, {"captured": 0, "identified": 0, "opted_out": 0}
        )
        bucket["captured"] += 1
        if identity_status and identity_status not in ("anonymous", ""):
            bucket["identified"] += 1
        if do_not_resolve:
            bucket["opted_out"] += 1
            total_opted_out += 1
        cc = (country_code or "").upper()
        if cc:
            country_counts[cc] = country_counts.get(cc, 0) + 1

    total = sum(b["captured"] for b in browsers.values())

    browser_list = [
        {
            "browser": name,
            "captured": b["captured"],
            "identified": b["identified"],
            "identification_rate": round(b["identified"] / b["captured"], 4)
            if b["captured"]
            else 0.0,
            "opted_out": b["opted_out"],
            "optout_rate": round(b["opted_out"] / b["captured"], 4)
            if b["captured"]
            else 0.0,
            "share": round(b["captured"] / total, 4) if total else 0.0,
        }
        for name, b in browsers.items()
    ]
    browser_list.sort(key=lambda r: r["captured"], reverse=True)

    # Expected Safari share = country-mix-weighted baseline. Country counts can
    # be sparser than browser counts (some visitors lack geo), so weight over
    # the geo-known subset.
    geo_total = sum(country_counts.values())
    expected_safari = (
        sum(
            (cnt / geo_total) * SAFARI_BASELINE.get(cc, GLOBAL_SAFARI_BASELINE)
            for cc, cnt in country_counts.items()
        )
        if geo_total
        else GLOBAL_SAFARI_BASELINE
    )
    safari_captured = browsers.get("Safari", {}).get("captured", 0)
    actual_safari = safari_captured / total if total else 0.0
    ratio = (actual_safari / expected_safari) if expected_safari else None
    status, message = _coverage_status(total, ratio)

    logger.info(
        "browser_breakdown_computed",
        site_id=site_id,
        total=total,
        safari_status=status,
    )

    return {
        "site_id": site_id,
        "window_days": window_days,
        "total_visitors": total,
        "browsers": browser_list,
        # Sticky visitor-level opt-out (GPC/DNT honored at `tracker.js` →
        # `events.optout` → BOOL_OR → `visitors.do_not_resolve`). This is the
        # number `resolve()` actually gates on, so it is the decision-relevant
        # rate — the event-level rate is a noisier view of the same thing.
        "privacy_optout": {
            "visitors": total,
            "opted_out": total_opted_out,
            "rate": round(total_opted_out / total, 4) if total else 0.0,
        },
        "safari_coverage": {
            "actual_share": round(actual_safari, 4),
            "expected_share": round(expected_safari, 4),
            "coverage_ratio": round(ratio, 4) if ratio is not None else None,
            "status": status,
            "message": message,
        },
    }
