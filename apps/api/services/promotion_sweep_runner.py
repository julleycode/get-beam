"""Click→verified promotion sweep (identity-honesty Phase 5).

Trigger-agnostic, mirroring ``resolution_runner``: ``run_promotion_sweep_once``
is the single "what runs" implementation; ``run_promotion_sweep`` is the
sweep-wide wrapper (own session + advisory lock) that the APScheduler job calls.
Triggers decide *when*; this module decides *what*.

Why a batch sweep and not an inline/per-click background task (locked SPEC
constraint): the ``/ingest`` hot path must never block on identity resolution,
and a per-click background task would drop work on a crash. A missed sweep cycle
is simply picked up by the next one, as long as the lookback window is wider than
the gap — see ``_window_minutes`` for the absolute floor that makes a routine
deploy restart survivable.

This module NEVER modifies ``identity_resolver``: it is a pure caller of the
existing public ``IdentityResolver.resolve()``. The privacy guards
(``do_not_resolve`` / suppression list) are the first two checks inside
``resolve()`` itself, so every caller — this sweep included — inherits them; no
query-level filter is needed or wanted here (a duplicate filter would drift).
"""

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.database import async_session
from apps.api.models.visitor import Visitor
from apps.api.models.visitor_email import VisitorEmail
from apps.api.services.identity_resolver import IdentityResolver

logger = structlog.get_logger()

# Advisory-lock key: single-flight across Railway replicas, each of which runs
# its own APScheduler. Optional for correctness (``_save_identified`` already
# absorbs a duplicate insert via IntegrityError) — this is for cleanliness and
# consistency with the resolution sweep.
_SWEEP_LOCK_KEY = "beam_promotion_sweep"

# Per-run cap. The sweep runs every 1-2 minutes over a >=15-minute window, so a
# normal run sees a handful of rows; the cap only bounds a pathological backlog.
PROMOTION_SWEEP_MAX_PER_RUN = 200

# Terminal-success identity states. ``merged`` is excluded as well as
# ``identified``: a plain ``!= "identified"`` would re-sweep already-merged rows
# every cycle for no benefit.
_TERMINAL_STATUSES = ("identified", "merged")

# Providers the DETERMINISTIC pre-waterfall path can record. Anything else on a
# swept row means the visitor fell through ``_check_prior_signals`` into the PAID
# provider waterfall — real provider spend on a click-derived row, which the
# query scope was specifically designed to make impossible. Treated as a bug.
_DETERMINISTIC_PROVIDERS = frozenset(
    {"form_capture", "svid_reconcile", "fingerprint", "email_click"}
)


def _window_minutes() -> int:
    """Lookback window: ``max(2 * cadence, absolute floor)``.

    A bare 2x cadence would be 2-4 minutes at the 1-2 minute cadence — narrower
    than a single deploy restart, which would silently age rows out of scope.
    """
    return max(
        2 * max(settings.promotion_sweep_interval_minutes, 1),
        settings.promotion_sweep_window_floor_minutes,
    )


async def run_promotion_sweep_once(db: AsyncSession) -> dict[str, int]:
    """Promote fresh tokenized-link clicks to a verified identity.

    Scope: ``visitor_emails`` rows with ``source == "utm"`` written inside the
    lookback window, whose visitor is not already in a terminal-success state.
    Each visitor is processed in isolation so one failure cannot abort the batch.

    Returns counters: processed, promoted (``identified``), merged (pointer at a
    canonical phantom import contact), unchanged, unexpected_paid (defensive —
    should always be 0).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=_window_minutes())

    result = await db.execute(
        select(Visitor)
        .join(
            VisitorEmail,
            (VisitorEmail.visitor_id == Visitor.visitor_id)
            & (VisitorEmail.site_id == Visitor.site_id),
        )
        .where(
            VisitorEmail.source == "utm",
            VisitorEmail.created_at >= cutoff,
            Visitor.identity_status.not_in(_TERMINAL_STATUSES),
        )
        .distinct()
        .limit(PROMOTION_SWEEP_MAX_PER_RUN)
    )
    visitors = list(result.scalars().all())

    counters = {
        "processed": 0,
        "promoted": 0,
        "merged": 0,
        "unchanged": 0,
        "unexpected_paid": 0,
    }
    if not visitors:
        return counters

    resolver = IdentityResolver(db)

    for visitor in visitors:
        counters["processed"] += 1
        try:
            identified = await resolver.resolve(visitor)
        except Exception as exc:
            logger.warning(
                "promotion_sweep_visitor_error",
                visitor_id=visitor.visitor_id[:8],
                error=str(exc),
            )
            continue

        if visitor.identity_status == "merged":
            # Imported-contact click: the email-dedup branch points this
            # click-derived visitor at the phantom import contact's canonical
            # row instead of duplicating the identity. Dashboard-visible via
            # canonical_visitor_id — a legitimate "verified" outcome.
            counters["merged"] += 1
        elif identified is not None:
            counters["promoted"] += 1
            provider = getattr(identified, "resolution_provider", None)
            if provider not in _DETERMINISTIC_PROVIDERS:
                # Defensive: a swept row should always short-circuit on the free
                # prior-signal path. Reaching a paid provider here means silent
                # spend on a click-derived row — a BUG, not a known-gap.
                counters["unexpected_paid"] += 1
                logger.error(
                    "promotion_sweep_unexpected_paid_provider",
                    visitor_id=visitor.visitor_id[:8],
                    provider=provider,
                )
        else:
            counters["unchanged"] += 1

    logger.info("promotion_sweep_batch_complete", **counters)
    return counters


async def _try_acquire_sweep_lock(db: AsyncSession) -> bool | None:
    """True when acquired, False when another replica holds it, None when the
    database has no advisory locks (SQLite in dev/test) — fail open, matching
    ``resolution_runner``."""
    try:
        result = await db.execute(
            sql_text("SELECT pg_try_advisory_lock(hashtext(:key))"),
            {"key": _SWEEP_LOCK_KEY},
        )
        return bool(result.scalar())
    except Exception as exc:
        logger.warning("promotion_sweep_lock_unavailable", error=str(exc))
        return None


async def _release_sweep_lock(db: AsyncSession) -> None:
    try:
        await db.execute(
            sql_text("SELECT pg_advisory_unlock(hashtext(:key))"),
            {"key": _SWEEP_LOCK_KEY},
        )
    except Exception:
        pass


async def run_promotion_sweep() -> None:
    """Sweep-wide entrypoint: own session, single-flight advisory lock.

    The enabled-check lives here as well as at registration time so a manual or
    future trigger can never run the sweep with the flag off.
    """
    if not settings.promotion_sweep_enabled:
        return

    async with async_session() as db:
        acquired = await _try_acquire_sweep_lock(db)
        if acquired is False:
            logger.info("promotion_sweep_lock_busy")
            return
        try:
            counters = await run_promotion_sweep_once(db)
            if counters["processed"]:
                logger.info(
                    "promotion_sweep_complete",
                    window_minutes=_window_minutes(),
                    **counters,
                )
        finally:
            if acquired:
                await _release_sweep_lock(db)
