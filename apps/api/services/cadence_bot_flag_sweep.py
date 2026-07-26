"""Batch sweep that applies the cadence bot flag (AC-4/5/12, bounded-read).

Thin DB-loop wrapper around the pure functions in ``cadence_bot_flag.py``,
mirroring the ``agent_intent_signals`` / ``agent_handoff_correlation`` module
shape: pure logic lives next door, this file only reads rows, calls the pure
decision, and writes.

BATCH-ONLY (AC-4). Nothing here runs on the ``POST /ingest`` hot path — the only
caller is the periodic APScheduler tick (``jobs/scheduler._cadence_bot_flag_sweep_job``).
``routers/events.py`` is untouched by this feature.

BOUNDED READ (non-negotiable). Every query carries
``events.created_at >= now() - cadence_bot_flag_lookback_days``. Without the cap
a visitor with years of history would force an unbounded ``events`` scan on every
tick — a self-inflicted DoS that grows with the table.

STICKY, VISIBILITY-ONLY WRITE. ``is_bot_suspect`` is OR-merged (only ever set to
true, never cleared) exactly like ``is_abuse_flagged``'s sticky semantics — but it
is a STRUCTURALLY DIFFERENT column: this module never writes ``is_abuse_flagged``
or ``do_not_resolve``, never imports ``agent_visit``, and nothing downstream reads
``is_bot_suspect`` for outreach eligibility or aggregate exclusion.

Fail-open per site and per visitor: one bad row never aborts the sweep.
"""

from datetime import datetime, timedelta

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.event import Event
from apps.api.models.site import Site
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services.cadence_bot_flag import (
    compute_cadence_variance,
    compute_engagement_ratio,
    evaluate_cadence_bot_flag,
)

logger = structlog.get_logger()


async def _flag_visitor(db: AsyncSession, site_id: str, visitor_id: str) -> None:
    """Sticky OR-merge write on both tables. Never un-flags."""
    await db.execute(
        update(Visitor)
        .where(
            Visitor.site_id == site_id,
            Visitor.visitor_id == visitor_id,
            Visitor.is_bot_suspect.is_(False),
        )
        .values(is_bot_suspect=True)
    )
    await db.execute(
        update(IdentifiedVisitor)
        .where(
            IdentifiedVisitor.site_id == site_id,
            IdentifiedVisitor.visitor_id == visitor_id,
            IdentifiedVisitor.is_bot_suspect.is_(False),
        )
        .values(is_bot_suspect=True)
    )


async def _sweep_site(db: AsyncSession, site_id: str, cutoff: datetime) -> int:
    """Evaluate every visitor of one site inside the bounded window. Returns flags set."""
    from apps.api.config import settings

    flagged = 0

    result = await db.execute(
        select(Event.visitor_id, Event.event_type, Event.created_at).where(
            Event.site_id == site_id,
            Event.created_at >= cutoff,
        )
    )

    per_visitor: dict[str, tuple[list[datetime], list[str]]] = {}
    for visitor_id, event_type, created_at in result.all():
        if not visitor_id:
            continue
        timestamps, event_types = per_visitor.setdefault(visitor_id, ([], []))
        event_types.append(event_type or "")
        if created_at is not None:
            timestamps.append(created_at)

    for visitor_id, (timestamps, event_types) in per_visitor.items():
        try:
            # Precondition BEFORE any ratio math: distinct visit DAYS, not raw
            # event count — a single burst of 500 pageviews is one visit.
            distinct_visit_days = len({ts.date() for ts in timestamps})
            min_visits_met = distinct_visit_days >= settings.cadence_bot_flag_min_visits
            if not min_visits_met:
                continue

            variance = compute_cadence_variance(timestamps)
            engagement_ratio = compute_engagement_ratio(event_types)

            if not evaluate_cadence_bot_flag(
                variance,
                engagement_ratio,
                min_visits_met,
                settings.cadence_bot_flag_max_variance_threshold,
                settings.cadence_bot_flag_max_engagement_ratio,
            ):
                continue

            await _flag_visitor(db, site_id, visitor_id)
            flagged += 1
            # Ids, counts and computed signal values only — never PII (AC-12).
            logger.info(
                "cadence_bot_flag_set",
                site_id=site_id,
                visitor_id=visitor_id,
                variance=variance,
                engagement_ratio=engagement_ratio,
                distinct_visit_days=distinct_visit_days,
            )
        except Exception as exc:
            # Fail-open per visitor: one bad row never aborts the site's sweep.
            logger.warning(
                "cadence_bot_flag_visitor_failed",
                site_id=site_id,
                visitor_id=visitor_id,
                error=str(exc),
            )

    return flagged


async def run_cadence_bot_flag_sweep(db: AsyncSession) -> dict[str, int]:
    """Top-level entrypoint. Returns counters: sites, flagged.

    No-op (and zero queries) when ``cadence_bot_flag_enabled`` is False — the
    OFF-by-default gate, matching the ``agent_detection_enabled`` posture.
    """
    from apps.api.config import settings

    counters = {"sites": 0, "flagged": 0}
    if not settings.cadence_bot_flag_enabled:
        return counters

    # NAIVE UTC deliberately: events.created_at is a naive `DateTime` column
    # (models/event.py), and asyncpg rejects an aware bound parameter against it.
    # Same convention as visitor_aggregator's naive-branch handling.
    cutoff = datetime.utcnow() - timedelta(
        days=settings.cadence_bot_flag_lookback_days
    )

    result = await db.execute(select(Site.site_id))
    site_ids = [site_id for (site_id,) in result.all() if site_id]

    for site_id in site_ids:
        try:
            counters["flagged"] += await _sweep_site(db, site_id, cutoff)
            counters["sites"] += 1
            await db.commit()
        except Exception as exc:
            # Fail-open per site: one site's failure never blocks the rest.
            await db.rollback()
            logger.warning(
                "cadence_bot_flag_site_failed", site_id=site_id, error=str(exc)
            )

    return counters
