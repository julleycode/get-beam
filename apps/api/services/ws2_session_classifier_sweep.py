"""Batch sweep that applies the WS2 agent-operated flag (bounded-read).

Thin DB-loop wrapper around the pure functions in ``ws2_session_classifier.py``,
mirroring ``cadence_bot_flag_sweep.py`` exactly: pure logic lives next door, this
file only reads rows, calls the pure decision, and writes.

BATCH-ONLY. Nothing here runs on the ``POST /ingest`` hot path — the only caller
is the periodic APScheduler tick (``jobs/scheduler._ws2_classifier_sweep_job``).
``routers/events.py`` is untouched by this feature.

BOUNDED READ (non-negotiable). Every query carries
``events.created_at >= now() - ws2_classifier_lookback_days``. Without the cap a
visitor with years of history would force an unbounded ``events`` scan on every
tick — a self-inflicted DoS that grows with the table.

STICKY, VISIBILITY-ONLY WRITE. ``is_agent_operated`` is OR-merged (only ever set
to true, never cleared) exactly like ``is_bot_suspect``'s sticky semantics — but
it is a STRUCTURALLY DIFFERENT column: this module never writes
``is_abuse_flagged`` or ``do_not_resolve``, never imports ``agent_visit``, never
imports ``cadence_bot_flag``/``agent_classifier``, and nothing downstream reads
``is_agent_operated`` for outreach eligibility or aggregate exclusion.

Fail-open per site and per visitor: one bad row never aborts the sweep.

ACTIVATED 07-08-26 (WS2 agent-session activation plan). This module shipped
DORMANT: its only input, ``agent_sig``, did not exist end to end. All three
missing legs have now landed together — (1) tracker.js collects the signals again
(strictly after the consent gate), (2) ``events.agent_sig`` exists as a nullable
JSONB column, and (3) ``routers/events.py`` persists it, which
``_extract_agent_sig`` below now reads. The sweep is still gated OFF by default
(``ws2_classifier_enabled``) and still flags nobody until an operator enables it
after the migration is live-applied.

Stage 1 is no longer structurally unreachable either: tracker.js line 4's
``navigator.webdriver`` early-return — which used to discard the very sessions
this layer exists to catch, before any signal could be recorded — was deleted as
part of the same activation.
"""

from datetime import datetime, timedelta

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.event import Event
from apps.api.models.site import Site
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services.ws2_session_classifier import (
    compute_dead_center_rate,
    evaluate_session_classifier,
)

logger = structlog.get_logger()


def _extract_agent_sig(event: Event) -> dict | None:
    """Per-event agent_sig accessor. Reads the real ``events.agent_sig`` column.

    The pixel ships ABBREVIATED wire keys (w/h/p/d/c) so the built tracker stays
    inside its <6KB gzip budget; this function is the single place they are
    expanded back into the classifier's field names. Keeping the translation here
    means the sweep body below stays a faithful clone of
    ``cadence_bot_flag_sweep`` and the classifier never learns the wire format.

    ``p`` is a pointer-entropy PROXY, not a measured entropy: the pixel reports 0
    when no pointermove was seen before the first interaction (agent-like) and 1
    once real pointer movement occurred (human-like). It slots straight into the
    existing ``max_pointer_entropy`` threshold comparison.

    Returns None when the column is NULL — every event written before the column
    existed, and every older pixel build. The behavioral gate then fails safe.
    """
    raw = getattr(event, "agent_sig", None)
    if not isinstance(raw, dict) or not raw:
        return None
    return {
        "webdriver": raw.get("w"),
        "ua_ch_headless": raw.get("h"),
        "ptr_entropy": raw.get("p"),
        "dead_center_ct": raw.get("d"),
    }


async def _flag_visitor(db: AsyncSession, site_id: str, visitor_id: str) -> None:
    """Sticky OR-merge write on both tables. Never un-flags."""
    await db.execute(
        update(Visitor)
        .where(
            Visitor.site_id == site_id,
            Visitor.visitor_id == visitor_id,
            Visitor.is_agent_operated.is_(False),
        )
        .values(is_agent_operated=True)
    )
    await db.execute(
        update(IdentifiedVisitor)
        .where(
            IdentifiedVisitor.site_id == site_id,
            IdentifiedVisitor.visitor_id == visitor_id,
            IdentifiedVisitor.is_agent_operated.is_(False),
        )
        .values(is_agent_operated=True)
    )


async def _sweep_site(db: AsyncSession, site_id: str, cutoff: datetime) -> int:
    """Evaluate every visitor of one site inside the bounded window. Returns flags set."""
    from apps.api.config import settings

    flagged = 0

    result = await db.execute(
        select(Event.visitor_id, Event.event_type, Event.created_at, Event).where(
            Event.site_id == site_id,
            Event.created_at >= cutoff,
        )
    )

    # Accumulate the strongest agent_sig-derived signals per visitor. click_ct is
    # available from event rows directly; the entropy/dead-centre/fast-path fields
    # come from _extract_agent_sig (None until persistence lands -> fail safe).
    per_visitor: dict[str, dict] = {}
    for visitor_id, event_type, _created_at, event in result.all():
        if not visitor_id:
            continue
        agg = per_visitor.setdefault(
            visitor_id,
            {
                "click_ct": 0,
                "dead_center_ct": 0,
                "pointer_entropy": None,
                "webdriver": None,
                "ua_ch_headless": None,
            },
        )
        if event_type == "click":
            agg["click_ct"] += 1
        sig = _extract_agent_sig(event)
        if sig:
            # Take the most-agent-like value seen this window (min entropy,
            # any true fast-path signal, summed dead-centre count).
            entropy = sig.get("ptr_entropy")
            if entropy is not None:
                agg["pointer_entropy"] = (
                    entropy
                    if agg["pointer_entropy"] is None
                    else min(agg["pointer_entropy"], entropy)
                )
            agg["dead_center_ct"] += sig.get("dead_center_ct") or 0
            if sig.get("webdriver"):
                agg["webdriver"] = True
            if sig.get("ua_ch_headless"):
                agg["ua_ch_headless"] = True

    for visitor_id, agg in per_visitor.items():
        try:
            # Precondition BEFORE any ratio math: enough clicks to judge a
            # dead-centre rate (a session with 1 click is noise, not a behavior).
            min_clicks_met = agg["click_ct"] >= settings.ws2_classifier_min_clicks

            dead_center_rate = compute_dead_center_rate(
                agg["dead_center_ct"], agg["click_ct"]
            )

            if not evaluate_session_classifier(
                agg["webdriver"],
                agg["ua_ch_headless"],
                agg["pointer_entropy"],
                dead_center_rate,
                min_clicks_met,
                settings.ws2_classifier_max_pointer_entropy,
                settings.ws2_classifier_min_dead_center_rate,
            ):
                continue

            await _flag_visitor(db, site_id, visitor_id)
            flagged += 1
            # Ids, counts and computed signal values only — never PII.
            logger.info(
                "ws2_agent_operated_set",
                site_id=site_id,
                visitor_id=visitor_id,
                pointer_entropy=agg["pointer_entropy"],
                dead_center_rate=dead_center_rate,
                click_ct=agg["click_ct"],
            )
        except Exception as exc:
            # Fail-open per visitor: one bad row never aborts the site's sweep.
            logger.warning(
                "ws2_classifier_visitor_failed",
                site_id=site_id,
                visitor_id=visitor_id,
                error=str(exc),
            )

    return flagged


async def run_ws2_classifier_sweep(db: AsyncSession) -> dict[str, int]:
    """Top-level entrypoint. Returns counters: sites, flagged.

    No-op (and zero queries) when ``ws2_classifier_enabled`` is False — the
    OFF-by-default gate, matching the ``cadence_bot_flag_enabled`` posture.
    """
    from apps.api.config import settings

    counters = {"sites": 0, "flagged": 0}
    if not settings.ws2_classifier_enabled:
        return counters

    # NAIVE UTC deliberately: events.created_at is a naive DateTime column
    # (models/event.py), and asyncpg rejects an aware bound parameter against it.
    # Same convention as cadence_bot_flag_sweep / visitor_aggregator.
    cutoff = datetime.utcnow() - timedelta(days=settings.ws2_classifier_lookback_days)

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
            logger.warning("ws2_classifier_site_failed", site_id=site_id, error=str(exc))

    return counters
