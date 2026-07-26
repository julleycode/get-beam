"""Batch sweep applying the outlier / internal-traffic damping flag.

Thin DB-loop wrapper around the pure functions in ``outlier_traffic_damping.py``,
mirroring ``cadence_bot_flag_sweep.py``: pure logic lives next door, this file
only reads rows, calls the pure decision, and writes.

BATCH-ONLY. Nothing here runs on the ``POST /ingest`` hot path — the only caller
is the periodic APScheduler tick
(``jobs/scheduler._outlier_traffic_damping_sweep_job``).

PER-SITE OPT-IN. Only sites with ``internal_damping_enabled=True`` are read at
all. With no site opted in this issues exactly one cheap query and returns.

BOUNDED READ (non-negotiable). Every event query carries
``events.created_at >= now() - outlier_traffic_damping_lookback_days``.

SUGGESTION-ONLY. What this sweep writes is a LABEL, not a decision. The
``is_internal_suspect`` it sets drives a badge and a "review these" surface and
NOTHING else: it does not exclude the visitor from the daily-digest aggregate and
does not deprioritise them in ``resolution_runner``. Only an explicit human
confirmation (``internal_override == "internal"``) does either. Calibrated live
27-07-26: at 20x/3d the scorer flagged 34 visitors, 5 of whom were ALREADY
identified with a real email, out of only 28 identified visitors system-wide — so
acting on the score automatically would have silently hidden ~18% of every
customer's real leads. The machine suggests; the human decides.

REVERSIBLE WRITE — the critical difference from every existing flag in this repo.
``is_bot_suspect`` and ``is_abuse_flagged`` are one-way sticky, OR-merged forever.
``is_internal_suspect`` is NOT. This sweep writes the CURRENT verdict in both
directions: a visitor whose volume normalises is un-labelled and their badge
disappears. Even though the label is now inert on the automatic path, keeping it
self-correcting matters — a stale suggestion is a customer being repeatedly asked
about someone who is no longer unusual.

MANUAL OVERRIDE WINS, PERMANENTLY, IN BOTH DIRECTIONS. Any visitor with a
non-NULL ``internal_override`` is skipped entirely — never evaluated, never
written. That single skip is the enforcement mechanism: a human's "yes this is
internal" is never un-set by a later sweep, and a human's "no this is NOT
internal" is never re-flagged by one.

Fail-open per site and per visitor: one bad row never aborts the sweep.
"""

from datetime import datetime, timedelta

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.event import Event
from apps.api.models.site import Site
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services.outlier_traffic_damping import (
    compute_engagement_ratio,
    compute_event_count_outlier_score,
    compute_multi_day_persistence,
    evaluate_outlier_flag,
)

logger = structlog.get_logger()


async def _set_flag(
    db: AsyncSession, site_id: str, visitor_id: str, flagged: bool
) -> None:
    """Write the CURRENT verdict on both tables. Reversible by design.

    Deliberately NOT the sticky ``update().where(col.is_(False))`` shape used by
    ``cadence_bot_flag_sweep._flag_visitor`` — this write must be able to clear
    the flag as well as set it. The ``!= flagged`` guard is a no-op filter (skip
    rows already in the target state), not a stickiness mechanism.

    The ``internal_override IS NULL`` guard is repeated here as defence in depth:
    the caller already skips overridden visitors, and this makes it impossible
    for a future refactor to launder a manual call away at the SQL level.
    """
    await db.execute(
        update(Visitor)
        .where(
            Visitor.site_id == site_id,
            Visitor.visitor_id == visitor_id,
            Visitor.internal_override.is_(None),
            Visitor.is_internal_suspect != flagged,
        )
        .values(is_internal_suspect=flagged)
    )
    await db.execute(
        update(IdentifiedVisitor)
        .where(
            IdentifiedVisitor.site_id == site_id,
            IdentifiedVisitor.visitor_id == visitor_id,
            IdentifiedVisitor.is_internal_suspect != flagged,
        )
        .values(is_internal_suspect=flagged)
    )


async def _sweep_site(db: AsyncSession, site_id: str, cutoff: datetime) -> dict[str, int]:
    """Evaluate every judgeable visitor of one site. Returns per-site counters."""
    from apps.api.config import settings

    counters = {"flagged": 0, "cleared": 0, "skipped_override": 0}

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

    if not per_visitor:
        return counters

    # Manual overrides win permanently and in BOTH directions: read them once and
    # exclude those visitors from evaluation entirely.
    override_rows = await db.execute(
        select(Visitor.visitor_id).where(
            Visitor.site_id == site_id,
            Visitor.internal_override.isnot(None),
        )
    )
    overridden = {vid for (vid,) in override_rows.all() if vid}

    # The site's OWN distribution — computed across ALL its visitors in the
    # window (including overridden ones: they are still part of what this site's
    # traffic actually looks like), never a global constant.
    site_event_counts = [len(types) for _, types in per_visitor.values()]

    for visitor_id, (timestamps, event_types) in per_visitor.items():
        try:
            if visitor_id in overridden:
                counters["skipped_override"] += 1
                continue

            outlier_score = compute_event_count_outlier_score(
                len(event_types),
                site_event_counts,
                settings.outlier_traffic_damping_min_site_visitors,
            )
            min_sample_met = outlier_score is not None
            persistent = compute_multi_day_persistence(
                timestamps, settings.outlier_traffic_damping_min_visit_days
            )
            engagement_ratio = compute_engagement_ratio(event_types)

            flagged = evaluate_outlier_flag(
                outlier_score,
                engagement_ratio,
                persistent,
                min_sample_met,
                settings.outlier_traffic_damping_outlier_threshold,
                settings.outlier_traffic_damping_min_engagement_ratio,
            )

            await _set_flag(db, site_id, visitor_id, flagged)
            counters["flagged" if flagged else "cleared"] += 1

            if flagged:
                # Ids, counts and computed signal values only — never PII.
                logger.info(
                    "outlier_traffic_damping_set",
                    site_id=site_id,
                    visitor_id=visitor_id,
                    outlier_score=outlier_score,
                    engagement_ratio=engagement_ratio,
                    event_count=len(event_types),
                )
        except Exception as exc:
            # Fail-open per visitor: one bad row never aborts the site's sweep.
            logger.warning(
                "outlier_traffic_damping_visitor_failed",
                site_id=site_id,
                visitor_id=visitor_id,
                error=str(exc),
            )

    return counters


async def run_outlier_traffic_damping_sweep(db: AsyncSession) -> dict[str, int]:
    """Top-level entrypoint. Returns counters: sites, flagged, cleared, skipped_override.

    No-op when no site has ``internal_damping_enabled=True`` — the per-site
    opt-in gate, matching the default-OFF posture of every other detection
    feature in this repo.
    """
    from apps.api.config import settings

    counters = {"sites": 0, "flagged": 0, "cleared": 0, "skipped_override": 0}

    result = await db.execute(
        select(Site.site_id).where(Site.internal_damping_enabled.is_(True))
    )
    site_ids = [site_id for (site_id,) in result.all() if site_id]
    if not site_ids:
        return counters

    # NAIVE UTC deliberately: events.created_at is a naive `DateTime` column
    # (models/event.py), and asyncpg rejects an aware bound parameter against it.
    cutoff = datetime.utcnow() - timedelta(
        days=settings.outlier_traffic_damping_lookback_days
    )

    for site_id in site_ids:
        try:
            site_counters = await _sweep_site(db, site_id, cutoff)
            for key, value in site_counters.items():
                counters[key] += value
            counters["sites"] += 1
            await db.commit()
        except Exception as exc:
            # Fail-open per site: one site's failure never blocks the rest.
            await db.rollback()
            logger.warning(
                "outlier_traffic_damping_site_failed", site_id=site_id, error=str(exc)
            )

    return counters
