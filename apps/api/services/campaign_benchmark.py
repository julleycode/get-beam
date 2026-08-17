"""Weekly cross-tenant campaign benchmark: category normalization + aggregation.

Two parts (marketing-claims-gap Phase 3):

1. :func:`normalize_category` — a PURE, deterministic mapper from the free-text
   ``sites.category`` column onto a small closed vocabulary. ``sites.category``
   is ``String(100)`` free text with no option list anywhere (onboarding never
   offered one, and the site-analysis path stores unbounded model output), so
   grouping on the raw value would yield buckets-of-one and defeat the k-floor.
   Anything unmapped becomes ``"other"`` and is still COUNTED — never dropped.

   This mapper is intended to be reusable by ``agents/segmenter.py`` later. It
   is deliberately NOT wired there in this phase.

2. :func:`aggregate_weekly_benchmarks` — the job body. For each site with
   ``benchmark_contribution_enabled = True`` it rolls the period up, groups by
   normalized category, sums, and counts contributing sites.

Two hard privacy invariants, both load-bearing:

* **k-floor.** A category pooling fewer than :data:`BENCHMARK_K_FLOOR` sites
  produces NO row at all — discarded, never written as a suppressed/partial row.
* **Write-nothing-when-blocked.** A site whose ``benchmark_contribution_enabled``
  is False or NULL contributes nothing and leaves NO trace anywhere — not even a
  skipped-site counter keyed by site. Its rows are never fetched.

``benchmark_contribution_enabled`` is a SEPARATE consent basis from the identity
co-op's ``Site.contribution_enabled``. Reusing the co-op flag would be a
purpose-limitation breach: it authorizes PII-bearing identity sharing against
specific policy text, not campaign-performance aggregation.

**No period-over-period delta is computed or published anywhere in this module.**
Near the k-floor, differencing consecutive periods can narrow an individual
tenant's numbers, so only absolute pooled values are ever surfaced.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from apps.api.config import settings
from apps.api.models.campaign import Campaign, CampaignTouchpoint
from apps.api.models.campaign_benchmark import CampaignBenchmark
from apps.api.models.database import async_session
from apps.api.models.outcome import Conversion
from apps.api.models.site import Site
from apps.api.services.campaign_stats import summarize

logger = structlog.get_logger()

# Minimum distinct contributing sites before a category row may be written.
# NOT comparable to traffic_fit.MIN_SAMPLE (50) — that counts EVENTS for one
# site; this counts TENANTS. Beam has a handful of sites per category today, so
# a tenant floor of 50 would mean the feature never emits a row. 5 is the
# smallest floor that still prevents a single-tenant readback. Revisit upward as
# the tenant count grows (see backlog/benchmark-k-floor-review_NOTE_16-08-26.md).
BENCHMARK_K_FLOOR = 5

_WINDOW = timedelta(days=7)

# The closed vocabulary. Keep small: more buckets means fewer sites per bucket
# means fewer categories clear the k-floor.
BENCHMARK_CATEGORIES = (
    "saas",
    "ecommerce",
    "agency",
    "marketplace",
    "fintech",
    "healthcare",
    "education",
    "media",
    "real_estate",
    "travel",
    "nonprofit",
    "other",
)

# Substring → bucket. Ordered: the FIRST match wins, so put more specific
# tokens before the generic ones they contain.
_CATEGORY_TOKENS: tuple[tuple[str, str], ...] = (
    ("real estate", "real_estate"),
    ("realestate", "real_estate"),
    ("property", "real_estate"),
    ("e-commerce", "ecommerce"),
    ("ecommerce", "ecommerce"),
    ("e commerce", "ecommerce"),
    ("shopify", "ecommerce"),
    ("retail", "ecommerce"),
    ("dtc", "ecommerce"),
    ("store", "ecommerce"),
    ("shop", "ecommerce"),
    ("marketplace", "marketplace"),
    ("classifieds", "marketplace"),
    ("fintech", "fintech"),
    ("banking", "fintech"),
    ("insurance", "fintech"),
    ("payments", "fintech"),
    ("finance", "fintech"),
    ("crypto", "fintech"),
    ("healthcare", "healthcare"),
    ("health", "healthcare"),
    ("medical", "healthcare"),
    ("clinic", "healthcare"),
    ("biotech", "healthcare"),
    ("pharma", "healthcare"),
    ("education", "education"),
    ("edtech", "education"),
    ("school", "education"),
    ("course", "education"),
    ("university", "education"),
    ("training", "education"),
    ("nonprofit", "nonprofit"),
    ("non-profit", "nonprofit"),
    ("charity", "nonprofit"),
    ("ngo", "nonprofit"),
    ("travel", "travel"),
    ("tourism", "travel"),
    ("hospitality", "travel"),
    ("hotel", "travel"),
    ("agency", "agency"),
    ("consult", "agency"),
    ("freelance", "agency"),
    ("studio", "agency"),
    ("marketing", "agency"),
    ("media", "media"),
    ("publishing", "media"),
    ("news", "media"),
    ("blog", "media"),
    ("newsletter", "media"),
    ("content", "media"),
    ("saas", "saas"),
    ("software", "saas"),
    ("b2b tech", "saas"),
    ("developer tool", "saas"),
    ("devtool", "saas"),
    ("platform", "saas"),
    ("app", "saas"),
    ("tech", "saas"),
)


def normalize_category(raw: str | None) -> str:
    """Map free-text ``sites.category`` onto :data:`BENCHMARK_CATEGORIES`.

    Pure and deterministic; case- and whitespace-insensitive. Unknown or missing
    input returns ``"other"`` — which is a real bucket that still gets counted,
    not a discard. No LLM: the grouping key must be stable across runs.
    """
    if not raw:
        return "other"
    text = " ".join(str(raw).strip().lower().replace("_", " ").split())
    if not text:
        return "other"
    if text in BENCHMARK_CATEGORIES:
        return text
    for token, bucket in _CATEGORY_TOKENS:
        if token in text:
            return bucket
    return "other"


def period_label(moment: datetime) -> str:
    """ISO-week label for a window, e.g. ``"2026-W33"``. Deterministic."""
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"


async def _site_period_stats(db, site_id: str, cutoff: datetime):
    """Bounded per-site fetch + pure rollup. Offline weekly job path only."""
    rows = (
        await db.execute(
            select(
                CampaignTouchpoint.channel,
                CampaignTouchpoint.status,
                CampaignTouchpoint.opened_at,
                CampaignTouchpoint.clicked_at,
            )
            .join(Campaign, Campaign.id == CampaignTouchpoint.campaign_id)
            .where(Campaign.site_id == site_id, CampaignTouchpoint.sent_at >= cutoff)
        )
    ).all()
    conversions = (
        await db.execute(
            select(Conversion.id).where(
                Conversion.site_id == site_id, Conversion.occurred_at >= cutoff
            )
        )
    ).all()
    return summarize(rows, channel="email", conversions=len(conversions))


async def aggregate_weekly_benchmarks() -> int:
    """Aggregate one weekly period. Returns the number of rows written.

    Returns 0 immediately when ``campaign_benchmark_enabled`` is False — nothing
    is read and nothing is written.
    """
    if not settings.campaign_benchmark_enabled:
        return 0

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - _WINDOW
    period = period_label(now)

    async with async_session() as db:
        # Opted-in sites ONLY. Sites that never opted in are not even fetched,
        # so there is no per-site trace of them anywhere in this job.
        site_rows = (
            await db.execute(
                select(Site.site_id, Site.category).where(
                    Site.benchmark_contribution_enabled.is_(True)
                )
            )
        ).all()

        pooled: dict[str, dict[str, int]] = {}
        for site_id, category in site_rows:
            stats = await _site_period_stats(db, site_id, cutoff)
            bucket = pooled.setdefault(
                normalize_category(category),
                {"sends": 0, "opens": 0, "clicks": 0, "conversions": 0, "site_count": 0},
            )
            bucket["sends"] += stats.sends
            bucket["opens"] += stats.opens
            bucket["clicks"] += stats.clicks
            bucket["conversions"] += stats.conversions
            bucket["site_count"] += 1

        written = 0
        for category_normalized, agg in sorted(pooled.items()):
            if agg["site_count"] < BENCHMARK_K_FLOOR:
                # Discarded outright — never written as a suppressed row, and
                # never logged with anything that identifies the contributors.
                logger.info(
                    "campaign_benchmark_below_k_floor",
                    category=category_normalized,
                    period=period,
                )
                continue
            stmt = pg_insert(CampaignBenchmark).values(
                category_normalized=category_normalized,
                period=period,
                sends=agg["sends"],
                opens=agg["opens"],
                clicks=agg["clicks"],
                conversions=agg["conversions"],
                site_count=agg["site_count"],
            )
            await db.execute(
                stmt.on_conflict_do_update(
                    constraint="uq_campaign_benchmarks_category_period",
                    set_={
                        "sends": stmt.excluded.sends,
                        "opens": stmt.excluded.opens,
                        "clicks": stmt.excluded.clicks,
                        "conversions": stmt.excluded.conversions,
                        "site_count": stmt.excluded.site_count,
                    },
                )
            )
            written += 1
        await db.commit()

    if written:
        logger.info("campaign_benchmarks_written", period=period, rows=written)
    return written


async def benchmark_for_category(db, category: str | None, period: str | None = None):
    """Read the most recent benchmark row for a site's category, or None.

    Returns None when the flag is off or no row cleared the k-floor. Callers
    render "no data" in that case — never a zero.
    """
    if not settings.campaign_benchmark_enabled:
        return None
    stmt = select(CampaignBenchmark).where(
        CampaignBenchmark.category_normalized == normalize_category(category)
    )
    if period is not None:
        stmt = stmt.where(CampaignBenchmark.period == period)
    stmt = stmt.order_by(CampaignBenchmark.period.desc()).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()
