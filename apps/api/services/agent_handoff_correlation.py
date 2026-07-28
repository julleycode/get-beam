"""Handoff Detection H2 — fetch↔click correlation sweep.

Links an on-demand ``agent_fetch_events`` row (an AI agent fetched page X for
vendor V at time T) to the human ``Visitor`` whose AI-referral click landed on
the same page from the same vendor family within a bounded window after T. This
is Beam's headline "who is the human behind the agent" signal.

WRITE POLICY (deliberate precision-over-recall for a v1 differentiator badge):
only ``high`` and ``medium`` confidence links are ever INSERTed. A candidate that
would compute as ``low`` (outside the correlation window) is DISCARDED, never
written. The ``low`` value stays in the ``AgentHandoffLink.confidence`` schema so a
future phase can loosen this policy without a migration.

Emailability separation (SPEC AC-H2-3 — the program's highest-priority gate):
this module NEVER imports, references, or writes the agent-origin emailability
marker, and NEVER calls the emailability guard. A handoff link is pure attribution
metadata on a structurally separate table; it changes no one's emailable status.
An absence-tripwire in tests/unit/test_handoff_emailability_separation.py enforces this.

Fail-open per-row: each candidate fetch event is processed in its own try/except
with its own commit (mirrors ``agent_company_resolution.run_company_resolution_sweep``).
One bad row never aborts the sweep. Never touches the ingest hot path (SPEC Constraint 4).
"""

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.agent_fetch_event import AgentFetchEvent
from apps.api.models.agent_handoff_link import AgentHandoffLink
from apps.api.models.event import Event
from apps.api.services.ai_referral import classify_ai_source

logger = structlog.get_logger()

# fetch-side vendor (agent_classifier._VENDOR_TOKENS) → click-side ai_source label
# (ai_referral.AI_REFERRER_DOMAINS). LOCKED at VALIDATE (plan Decision 6). A fetch
# vendor with no entry here (e.g. ``bytespider`` — structurally never tier=on-demand,
# so never reaches this sweep anyway) short-circuits to "no candidate match".
_VENDOR_FAMILY_MAP: dict[str, str] = {
    "openai": "chatgpt",
    "anthropic": "claude",
    "perplexity": "perplexity",
    # Unreachable today — the google tokens are all index-tier, so they never
    # reach this sweep. Mapped anyway so that promoting one to on-demand later
    # cannot silently yield zero links: a missing entry short-circuits to "no
    # candidate match" without any error, which is the hardest kind of gap to
    # notice. "gemini" is the matching ai_referral label for gemini.google.com.
    "google": "gemini",
}

# Correlation window: a click is only a candidate within this many seconds AFTER
# the fetch. 30 min = 1800 s (plan Decision 7). This bound IS the medium/discard
# boundary — a delta beyond it computes as ``low`` and is discarded.
_WINDOW_SECONDS = 1800

# High-confidence delta ceiling: exact-page + family within this many seconds.
_HIGH_DELTA_SECONDS = 300

# Ceiling on referrer-carrying pageviews loaded per fetch event. Ordered oldest
# first, so the clicks nearest the fetch — the ones that can score ``high`` — are
# always inside the cap.
_CANDIDATE_SCAN_LIMIT = 500

# Only fetch events created within this lookback are swept for new links (bounds
# the unlinked-scan; older events are considered settled). Minutes.
#
# A fetch only becomes eligible once its 30-minute correlation window has closed,
# so the usable band is (now - lookback, now - 30min). This is set well above the
# minimum so a missed sweep — a restart, a failed run — does not age a fetch out
# before it was ever correlated. The scan stays cheap regardless: it is indexed,
# excludes already-linked rows, and is capped by ``limit``.
_UNLINKED_LOOKBACK_MINUTES = 180


def _compute_confidence(
    *, vendor: str, exact_page: bool, delta_seconds: int
) -> str | None:
    """Pure confidence tier for one fetch↔click candidate, or ``None`` to discard.

    Returns ``"high"`` / ``"medium"`` (write) or ``None`` (discard as ``low``).
    - ``high``: exact page + same vendor family + ``delta <= 300s``.
    - ``medium``: exact page + family + ``300 < delta <= 1800s``, OR family +
      window-bound but page mismatch.
    - Perplexity cap: a ``perplexity`` fetch is never ``high`` (undeclared-crawler
      trust discount) — capped to ``medium``.
    - ``None`` (discarded ``low``): delta outside ``[0, 1800]``.
    """
    if delta_seconds < 0 or delta_seconds > _WINDOW_SECONDS:
        return None
    if exact_page and delta_seconds <= _HIGH_DELTA_SECONDS:
        result = "high"
    else:
        # exact-page slow delta, OR page mismatch — both medium within window.
        result = "medium"
    if vendor == "perplexity" and result == "high":
        result = "medium"
    return result


def correlate_fetch_to_clicks(
    *,
    fetch_site_id: str,
    fetch_vendor: str,
    fetch_page_path: str | None,
    fetch_at: datetime,
    candidate_events: list,
) -> dict | None:
    """Pure fetch↔click correlation — pick the best click for one fetch event.

    ``candidate_events`` are pageview-shaped objects exposing ``site_id``,
    ``visitor_id``, ``page_path``, ``referrer``, ``created_at`` (already site- and
    window-scoped by the caller's SQL; this function re-checks BOTH site and window
    defensively — AC-H2-5 belt-and-suspenders). Filters to same-vendor-family
    AI-referral clicks, applies the tie-break (exact page wins first, then smallest
    delta), and computes the confidence tier.

    Returns a dict ``{visitor_id, confidence, delta_seconds, matched_page}`` for a
    writable (high/medium) link, or ``None`` when there is no qualifying match.
    ``matched_page`` is always the fetch event's ``page_path`` (``None`` is a valid
    stored value when the agent fetched an unknown path).
    """
    expected = _VENDOR_FAMILY_MAP.get(fetch_vendor)
    if expected is None:
        return None

    matches: list[tuple[bool, int, object]] = []
    for ev in candidate_events:
        # AC-H2-5: never link across sites, regardless of timing/vendor.
        if getattr(ev, "site_id", None) != fetch_site_id:
            continue
        if classify_ai_source(getattr(ev, "referrer", None)) != expected:
            continue
        # Event.created_at is naive (models/event.py DateTime without tz) while
        # AgentFetchEvent.created_at / fetch_at are aware (Base DateTime(timezone=True)).
        # Subtracting mixed-awareness datetimes raises TypeError, so normalize both
        # operands to aware UTC before computing the delta. Defensive on either side.
        ev_created = ev.created_at
        if ev_created.tzinfo is None:
            ev_created = ev_created.replace(tzinfo=timezone.utc)
        fetch_at_aware = fetch_at
        if fetch_at_aware.tzinfo is None:
            fetch_at_aware = fetch_at_aware.replace(tzinfo=timezone.utc)
        delta = int((ev_created - fetch_at_aware).total_seconds())
        if delta < 0 or delta > _WINDOW_SECONDS:
            continue
        exact = fetch_page_path is not None and ev.page_path == fetch_page_path
        matches.append((exact, delta, ev))

    if not matches:
        return None

    # Tie-break: exact-page candidates first, then smallest delta.
    matches.sort(key=lambda m: (not m[0], m[1]))
    exact, delta, ev = matches[0]

    confidence = _compute_confidence(
        vendor=fetch_vendor, exact_page=exact, delta_seconds=delta
    )
    if confidence is None:
        return None

    return {
        "visitor_id": ev.visitor_id,
        "confidence": confidence,
        "delta_seconds": delta,
        "matched_page": fetch_page_path,
    }


async def run_handoff_correlation_sweep(
    db: AsyncSession, limit: int = 20
) -> dict[str, int]:
    """Link recent unlinked on-demand agent fetches to human AI-referral clicks.

    Candidate fetch events: ``tier == 'on-demand'``, created within the last
    ``_UNLINKED_LOOKBACK_MINUTES``, with no existing ``agent_handoff_links`` row.
    For each, query same-site ``pageview`` events in the 30-minute window, run the
    pure correlation, and INSERT a high/medium link (never ``low``).

    Every query is ``site_id``-scoped — no cross-site fetch/click pair can ever
    link (AC-H2-5). Fail-open per row: own try/except, own commit, keys-only
    ``logger.exception`` on failure, continue.

    Returns counters: processed (fetch events examined), linked (links written).
    """
    counters = {"processed": 0, "linked": 0}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=_UNLINKED_LOOKBACK_MINUTES)

    link_exists = (
        select(AgentHandoffLink.id)
        .where(AgentHandoffLink.agent_fetch_event_id == AgentFetchEvent.id)
        .exists()
    )
    # Only correlate a fetch once its whole correlation window has elapsed. A
    # link is written at most once (``~link_exists`` then excludes the fetch
    # forever), so correlating early would settle on whichever click happened to
    # exist at that moment: a weak page-mismatch click at T+3min would be written
    # as ``medium`` and permanently shut out the exact-page click at T+12min that
    # should have scored ``high``. Waiting for the window to close means every
    # sweep sees the complete candidate set.
    window_closed = now - timedelta(seconds=_WINDOW_SECONDS)
    result = await db.execute(
        select(AgentFetchEvent)
        .where(
            AgentFetchEvent.tier == "on-demand",
            AgentFetchEvent.created_at > cutoff,
            AgentFetchEvent.created_at <= window_closed,
            ~link_exists,
        )
        .limit(limit)
    )
    fetch_events = list(result.scalars().all())
    if not fetch_events:
        # Still log. An empty sweep and a sweep that never ran are otherwise
        # indistinguishable in the logs, which makes "zero handoff links"
        # impossible to diagnose without querying the database by hand.
        logger.info("agent_handoff_correlation_sweep_done", **counters)
        return counters

    for fetch_event in fetch_events:
        try:
            counters["processed"] += 1

            # AgentFetchEvent.created_at is aware (Base DateTime(timezone=True))
            # but Event.created_at is naive (models/event.py). Comparing/subtracting
            # them — both in the SQL filter below and inside correlate_fetch_to_clicks
            # — raises on mixed awareness. Coerce fetch_at to naive UTC so it matches
            # the naive Event column the sweep queries and diffs against.
            fetch_at = fetch_event.created_at
            if fetch_at.tzinfo is not None:
                fetch_at = fetch_at.astimezone(timezone.utc).replace(tzinfo=None)
            window_end = fetch_at + timedelta(seconds=_WINDOW_SECONDS)
            # site_id-scoped (AC-H2-5): only this site's pageviews are candidates.
            # Bounded on purpose. A candidate must carry a referrer to stand any
            # chance — ``correlate_fetch_to_clicks`` drops everything whose
            # referrer is not a known AI host — so filtering empty referrers in
            # SQL removes the bulk of a busy site's pageviews before they are
            # ever loaded. The cap is the backstop that keeps one fetch on a
            # high-traffic site from pulling an unbounded result set into memory,
            # multiplied by up to ``limit`` fetch events per sweep.
            ev_result = await db.execute(
                select(Event)
                .where(
                    Event.site_id == fetch_event.site_id,
                    Event.event_type == "pageview",
                    Event.created_at >= fetch_at,
                    Event.created_at <= window_end,
                    Event.referrer != "",
                    Event.referrer.is_not(None),
                )
                .order_by(Event.created_at)
                .limit(_CANDIDATE_SCAN_LIMIT)
            )
            candidate_events = list(ev_result.scalars().all())

            match = correlate_fetch_to_clicks(
                fetch_site_id=fetch_event.site_id,
                fetch_vendor=fetch_event.vendor,
                fetch_page_path=fetch_event.page_path,
                fetch_at=fetch_at,
                candidate_events=candidate_events,
            )
            if match is None:
                continue

            db.add(
                AgentHandoffLink(
                    site_id=fetch_event.site_id,
                    visitor_id=match["visitor_id"],
                    agent_fetch_event_id=fetch_event.id,
                    confidence=match["confidence"],
                    method="temporal-page-match",
                    delta_seconds=match["delta_seconds"],
                    matched_page=match["matched_page"],
                )
            )
            await db.commit()
            counters["linked"] += 1
        except Exception:
            # Per-row fail-open: one bad row must not abort the sweep. Log keys
            # only (no PII / no referrer bodies).
            await db.rollback()
            logger.exception(
                "agent_handoff_correlation_row_failed",
                id=str(fetch_event.id),
                site_id=fetch_event.site_id,
            )

    logger.info("agent_handoff_correlation_sweep_done", **counters)
    return counters
