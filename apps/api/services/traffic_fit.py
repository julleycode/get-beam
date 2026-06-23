"""Per-site traffic-fit estimate — "can beam actually identify this site's visitors?"

beam resolves person-level identity for US traffic only (IP geofence; see
apps/web/public/beam/privacy.html). A site whose visitors are mostly non-US will
see ~0 identified visitors no matter how long the pixel runs. This module turns
that structural limit into an honest, up-front readout: the US share of located
traffic, the measured US match rate, and a single "~X% identifiable" estimate —
so a poor-fit site learns it in minutes instead of churning after weeks of empty
dashboards. It also doubles as a sales-qualification signal (which sites beam
actually serves).

Same inputs as browser_breakdown: identity from `Visitor.identity_status`, geo
from `Visitor.country_code` (already resolved at ingestion).
"""

from datetime import datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.visitor import Visitor

logger = structlog.get_logger()

# Person-level identification is US-only (IP geofence). Keep in sync with the
# coverage statement in apps/web/public/beam/privacy.html.
SERVABLE_COUNTRIES: set[str] = {"US"}

# Below this many geo-known visitors the US-share estimate is noise.
MIN_SAMPLE = 50

# Fallback within-US match rate when too few US visitors to measure one (the
# landing quotes 60–80%; 0.6 is the conservative floor).
DEFAULT_US_MATCH = 0.6

# Need at least this many US visitors before trusting a *measured* match rate.
MIN_US_FOR_MEASURED = 20

TOP_COUNTRIES = 6


def _fit_estimate(located: int, us_count: int, identified_us: int) -> dict:
    """US share + identifiable-% estimate from raw counts. Pure (no DB) so it can
    be unit-tested directly. `identifiable_estimate` = US share × the US match
    rate (measured once there are enough US visitors, else a conservative
    default)."""
    us_share = us_count / located if located else 0.0
    us_match_rate = identified_us / us_count if us_count else None
    match_estimate = (
        us_match_rate
        if us_count >= MIN_US_FOR_MEASURED and us_match_rate is not None
        else DEFAULT_US_MATCH
    )
    return {
        "us_share": round(us_share, 4),
        "us_match_rate": round(us_match_rate, 4) if us_match_rate is not None else None,
        "identifiable_estimate": round(us_share * match_estimate, 4),
    }


def _fit_verdict(located: int, us_share: float) -> tuple[str, str]:
    """Map geo-known sample size + US share to a status + plain-English message.
    Pure (no DB) so it can be unit-tested directly."""
    if located < MIN_SAMPLE:
        return (
            "insufficient_data",
            f"Need ~{MIN_SAMPLE} located visitors to estimate fit — check back "
            "once more traffic arrives.",
        )
    pct = round(us_share * 100)
    if us_share >= 0.5:
        return (
            "good_fit",
            f"{pct}% of your located traffic is US — beam's core market. Most "
            "visitors are eligible for identification.",
        )
    if us_share >= 0.2:
        return (
            "partial_fit",
            f"{pct}% of your located traffic is US. beam will identify that "
            "slice; the rest is outside its US-only coverage.",
        )
    return (
        "poor_fit",
        f"Only {pct}% of your located traffic is US. beam identifies US "
        "visitors only, so most of your traffic won't resolve.",
    )


async def compute_traffic_fit(
    db: AsyncSession, site_id: str, window_days: int = 30
) -> dict:
    """US-coverage fit estimate for one site over the trailing `window_days`."""
    since = datetime.utcnow() - timedelta(days=window_days)

    rows = (
        await db.execute(
            select(Visitor.identity_status, Visitor.country_code).where(
                Visitor.site_id == site_id, Visitor.last_seen >= since
            )
        )
    ).all()

    total = len(rows)
    country_counts: dict[str, int] = {}
    us_count = 0
    identified_us = 0
    for identity_status, country_code in rows:
        cc = (country_code or "").upper()
        if not cc:
            continue
        country_counts[cc] = country_counts.get(cc, 0) + 1
        if cc in SERVABLE_COUNTRIES:
            us_count += 1
            if identity_status and identity_status not in ("anonymous", ""):
                identified_us += 1

    located = sum(country_counts.values())
    est = _fit_estimate(located, us_count, identified_us)
    status, message = _fit_verdict(located, est["us_share"])

    top_countries = [
        {
            "country": cc,
            "count": cnt,
            "share": round(cnt / located, 4) if located else 0.0,
        }
        for cc, cnt in sorted(
            country_counts.items(), key=lambda kv: kv[1], reverse=True
        )[:TOP_COUNTRIES]
    ]

    logger.info(
        "traffic_fit_computed",
        site_id=site_id,
        located=located,
        us_share=est["us_share"],
        status=status,
    )

    return {
        "site_id": site_id,
        "window_days": window_days,
        "total_visitors": total,
        "located_visitors": located,
        "us_share": est["us_share"],
        "unknown_share": round((total - located) / total, 4) if total else 0.0,
        "servable_count": us_count,
        "identified_servable": identified_us,
        "us_match_rate": est["us_match_rate"],
        "identifiable_estimate": est["identifiable_estimate"],
        "top_countries": top_countries,
        "status": status,
        "message": message,
    }
