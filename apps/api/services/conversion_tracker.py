"""Conversion goal matching + campaign attribution.

Called from the event-ingest hot path, so the contract is strict:

- ``process_batch`` NEVER raises — any failure is logged and swallowed so the
  pixel always gets its 204.
- Zero work unless the batch actually contains matchable events AND the site
  has enabled goals (one indexed query to find out).
- Core-style statements only (no ORM relationship loads) and the caller's
  session — no session of our own, no lazy-load MissingGreenlet surprises.

Attribution model (honest by design): last CLICK within
``ATTRIBUTION_WINDOW_DAYS``. Opens never attribute (Apple Mail Privacy
Protection prefetches them). A conversion with no qualifying click is still
recorded as ``organic`` — the baseline that makes the attributed number
credible.
"""

from datetime import datetime, timedelta
from typing import NamedTuple
from urllib.parse import urlsplit
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.campaign import Campaign, CampaignTouchpoint
from apps.api.models.outcome import CampaignClick, Conversion, ConversionGoal
from apps.api.schemas.events import EventBatch

logger = structlog.get_logger()

ATTRIBUTION_WINDOW_DAYS = 30
MAX_GOALS_PER_SITE = 20
# Per-conversion value ceiling ($1M in cents) — clamps hostile/buggy inputs.
MAX_VALUE_CENTS = 100_000_000
# clicked_at is stamped with SERVER time while occurred_at comes from the
# CLIENT's event.ts — a click and a conversion landing in the same pixel batch
# can therefore be a few seconds "out of order". Allow a small skew so the
# immediate click→convert case (the most common one) still attributes.
_CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)


def normalize_path(raw: str | None) -> str:
    """Reduce a URL or bare path to a comparable path.

    Lowercased, query/fragment stripped, trailing slash stripped (root ``/``
    preserved). Returns ``""`` when nothing usable remains.
    """
    if not raw:
        return ""
    value = raw.strip()
    if not value:
        return ""
    if "://" in value:
        value = urlsplit(value).path or "/"
    else:
        value = value.split("#", 1)[0].split("?", 1)[0]
    value = value.strip().lower()
    if not value:
        return ""
    if not value.startswith("/"):
        value = "/" + value
    if len(value) > 1:
        value = value.rstrip("/") or "/"
    return value


def matches_goal(pattern: str, match_type: str, path: str) -> bool:
    """Pure predicate: does a normalized path satisfy a goal pattern?"""
    if not path or not pattern:
        return False
    if match_type == "exact":
        return path == pattern
    if match_type == "prefix":
        return path.startswith(pattern)
    if match_type == "contains":
        return pattern in path
    return False


def build_dedupe_key(
    goal_id: UUID,
    repeatable: bool,
    visitor_id: str,
    occurred_at: datetime,
    event_id: str | None = None,
    source: str = "url_match",
) -> str:
    """Uniqueness carrier enforcing the dedupe policy at the DB layer.

    - non-repeatable: once per (goal, visitor), forever.
    - repeatable via js_event/webhook with a caller idempotency id: once per
      event_id (exact — an order id can safely be retried).
    - repeatable otherwise (url_match): once per visitor per UTC day — robust
      to refreshes and beacon replays without session bookkeeping.
    """
    if not repeatable:
        return f"{goal_id}:{visitor_id}"
    if event_id and source in ("js_event", "webhook"):
        return f"{goal_id}:{visitor_id}:{event_id}"
    return f"{goal_id}:{visitor_id}:{occurred_at:%Y%m%d}"


class Attribution(NamedTuple):
    touchpoint_id: UUID
    campaign_id: UUID
    channel: str | None
    matched_by: str  # click_link | same_visitor


async def attribute_visitor(
    db: AsyncSession, site_id: str, visitor_id: str, at: datetime
) -> Attribution | None:
    """Last qualifying campaign click for this visitor, or None (organic).

    Two indexed point lookups, in trust order:
    1. ``campaign_clicks`` — the durable touchpoint↔landing-vid link recorded
       at ``_tp`` landing time; survives cross-device clicks.
    2. Fallback: a touchpoint sent TO this visitor_id that has clicked_at set
       (same-browser case; covers touchpoints from before campaign_clicks
       existed, which can't be backfilled).
    """
    cutoff = at - timedelta(days=ATTRIBUTION_WINDOW_DAYS)

    row = (
        await db.execute(
            select(
                CampaignClick.touchpoint_id,
                CampaignClick.campaign_id,
                CampaignTouchpoint.channel,
            )
            .join(CampaignTouchpoint, CampaignTouchpoint.id == CampaignClick.touchpoint_id)
            .where(
                CampaignClick.site_id == site_id,
                CampaignClick.visitor_id == visitor_id,
                CampaignClick.clicked_at >= cutoff,
                CampaignClick.clicked_at <= at + _CLOCK_SKEW_TOLERANCE,
            )
            .order_by(CampaignClick.clicked_at.desc())
            .limit(1)
        )
    ).first()
    if row:
        return Attribution(row[0], row[1], row[2], "click_link")

    row = (
        await db.execute(
            select(
                CampaignTouchpoint.id,
                CampaignTouchpoint.campaign_id,
                CampaignTouchpoint.channel,
            )
            .join(Campaign, Campaign.id == CampaignTouchpoint.campaign_id)
            .where(
                Campaign.site_id == site_id,
                CampaignTouchpoint.visitor_id == visitor_id,
                CampaignTouchpoint.clicked_at.is_not(None),
                CampaignTouchpoint.clicked_at >= cutoff,
                CampaignTouchpoint.clicked_at <= at + _CLOCK_SKEW_TOLERANCE,
            )
            .order_by(CampaignTouchpoint.clicked_at.desc())
            .limit(1)
        )
    ).first()
    if row:
        return Attribution(row[0], row[1], row[2], "same_visitor")

    return None


async def record_conversion(
    db: AsyncSession,
    *,
    site_id: str,
    goal: ConversionGoal,
    visitor_id: str,
    occurred_at: datetime,
    value_cents: int | None = None,
    url: str = "",
    source: str = "url_match",
    event_id: str | None = None,
) -> tuple[bool, Attribution | None]:
    """Attribute + insert one conversion. Idempotent; does NOT commit.

    Returns (inserted, attribution): inserted is False when deduped;
    attribution is None for organic conversions.
    """
    attribution = await attribute_visitor(db, site_id, visitor_id, occurred_at)

    value = goal.value_cents or 0 if value_cents is None else value_cents
    value = max(0, min(int(value), MAX_VALUE_CENTS))

    result = await db.execute(
        pg_insert(Conversion)
        .values(
            site_id=site_id,
            goal_id=goal.id,
            visitor_id=visitor_id,
            touchpoint_id=attribution.touchpoint_id if attribution else None,
            campaign_id=attribution.campaign_id if attribution else None,
            channel=attribution.channel if attribution else None,
            attribution="campaign" if attribution else "organic",
            matched_by=attribution.matched_by if attribution else None,
            source=source,
            value_cents=value,
            url=(url or "")[:2000],
            dedupe_key=build_dedupe_key(
                goal.id, goal.repeatable, visitor_id, occurred_at, event_id, source
            ),
            occurred_at=occurred_at,
        )
        .on_conflict_do_nothing(constraint="uq_conversions_dedupe_key")
    )
    inserted = bool(result.rowcount)
    if inserted:
        logger.info(
            "conversion_recorded",
            site_id=site_id,
            goal=goal.name,
            attribution="campaign" if attribution else "organic",
            matched_by=attribution.matched_by if attribution else None,
            source=source,
        )
    return inserted, attribution


async def process_batch(db: AsyncSession, batch: EventBatch) -> int:
    """Match a pixel batch against the site's goals. Never raises.

    Returns the number of conversions inserted (0 on any failure).
    """
    try:
        return await _process_batch(db, batch)
    except Exception as exc:
        logger.warning(
            "conversion_tracking_failed", site_id=batch.site_id, error=str(exc)
        )
        try:
            await db.rollback()
        except Exception:
            pass
        return 0


async def _process_batch(db: AsyncSession, batch: EventBatch) -> int:
    pageviews = [e for e in batch.events if e.type == "pageview"]
    js_conversions = [e for e in batch.events if e.type == "conversion" and e.goal]
    if not pageviews and not js_conversions:
        return 0

    goals = (
        (
            await db.execute(
                select(ConversionGoal).where(
                    ConversionGoal.site_id == batch.site_id,
                    ConversionGoal.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    if not goals:
        return 0
    url_goals = [g for g in goals if g.goal_type == "url_match"]
    # beamConvert() may target ANY enabled goal by name (a url_match goal can
    # also take explicit values), so the name map spans all goal types.
    goals_by_name = {g.name.strip().lower(): g for g in goals}

    # (goal, event) candidates, deduped in-memory by dedupe key so one batch
    # can't insert the same conversion twice before the DB constraint sees it.
    seen_keys: set[str] = set()
    inserted = 0

    for event in pageviews:
        if not url_goals:
            break
        path = normalize_path(event.page_path or event.url)
        if not path:
            continue
        occurred_at = (
            event.ts.replace(tzinfo=None) if event.ts.tzinfo else event.ts
        )
        for goal in url_goals:
            if not matches_goal(goal.pattern, goal.match_type, path):
                continue
            key = build_dedupe_key(
                goal.id, goal.repeatable, batch.visitor_id, occurred_at
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            did_insert, _ = await record_conversion(
                db,
                site_id=batch.site_id,
                goal=goal,
                visitor_id=batch.visitor_id,
                occurred_at=occurred_at,
                url=event.url or "",
                source="url_match",
            )
            if did_insert:
                inserted += 1

    for event in js_conversions:
        goal = goals_by_name.get((event.goal or "").strip().lower())
        if not goal:
            continue
        occurred_at = (
            event.ts.replace(tzinfo=None) if event.ts.tzinfo else event.ts
        )
        value_cents = (
            round(event.value * 100) if event.value is not None else None
        )
        key = build_dedupe_key(
            goal.id,
            goal.repeatable,
            batch.visitor_id,
            occurred_at,
            event.event_id,
            "js_event",
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        did_insert, _ = await record_conversion(
            db,
            site_id=batch.site_id,
            goal=goal,
            visitor_id=batch.visitor_id,
            occurred_at=occurred_at,
            value_cents=value_cents,
            url=event.url or "",
            source="js_event",
            event_id=event.event_id,
        )
        if did_insert:
            inserted += 1

    if inserted:
        await db.commit()
    return inserted
