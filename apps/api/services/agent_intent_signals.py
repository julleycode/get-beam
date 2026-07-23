"""Handoff Detection H3 — live AI-mediated intent signals.

Turns H1's on-demand ``agent_fetch_events`` stream into founder-facing intent
signals: near-real-time alerts when someone actively asks an AI agent about a
commercial page, plus rolling-window spike detection. NO new storage and NO
migration — everything here reads the existing H1 event stream.

Safety posture (SPEC AC-H3-3/4): these signals are CONTEXT, not action. Nothing
here ever independently triggers outreach or makes a person-level claim — the
alert copy is strictly SITE-level (see ``hot_alert.maybe_send_intent_alert``).

Fail-open per (site, page): one site's failure never blocks the sweep for the
rest (mirrors ``agent_handoff_correlation.run_handoff_correlation_sweep``). Never
touches the ingest hot path — only the periodic scheduler tick calls the sweep.
"""

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.agent_fetch_event import AgentFetchEvent
from apps.api.models.site import Site
from apps.api.services.hot_alert import maybe_send_intent_alert

logger = structlog.get_logger()

# Commercial-intent page prefixes. Module-level constant — no per-site config this
# phase (backlog: phase-03-per-site-commercial-page-config_NOTE).
COMMERCIAL_PAGE_PREFIXES = frozenset(
    {"/pricing", "/demo", "/signup", "/compare", "/vs", "/plans", "/trial"}
)

# Spike floor: a (site, page) must see at least this many on-demand fetches in the
# current 24h before it can qualify as a spike, regardless of baseline.
_SPIKE_FLOOR = 3
# Spike multiplier: current 24h must be at least this many times the trailing avg.
_SPIKE_MULTIPLIER = 2.0

# Sweep windows.
_CURRENT_WINDOW_HOURS = 24
_TRAILING_DAYS = 7
# The alert copy's "in the last N minutes" reflects the current-count window.
_ALERT_WINDOW_MINUTES = _CURRENT_WINDOW_HOURS * 60


def is_commercial_page(path: str | None) -> bool:
    """True iff ``path`` is (or is under) a commercial-intent page. Pure, no I/O.

    Normalizes with ``rstrip('/').lower()`` (an empty result — e.g. ``"/"`` or
    ``""`` — is never commercial). Matches ``normalized == prefix`` or
    ``normalized.startswith(prefix + "/")`` so ``/pricing`` and
    ``/pricing/enterprise`` match, but ``/pricing-blog`` does NOT (no ``/``
    boundary).
    """
    if not path:
        return False
    normalized = path.rstrip("/").lower()
    if not normalized:
        return False
    for prefix in COMMERCIAL_PAGE_PREFIXES:
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return True
    return False


def detect_spike(current_24h: int, trailing_7d_daily_avg: float) -> bool:
    """True iff ``current_24h`` is a spike over the trailing daily average. Pure.

    Floor-then-multiplier: the ``>= 3`` floor gates BEFORE the multiplier, so a
    single fetch against a zero baseline is NOT a spike (floor unmet), while
    3 fetches against a zero baseline IS (floor met, ``>= 2 * 0`` trivially true).
    """
    return current_24h >= _SPIKE_FLOOR and current_24h >= _SPIKE_MULTIPLIER * trailing_7d_daily_avg


async def _dominant_vendor(
    db: AsyncSession, site_id: str, page_path: str, since: datetime
) -> str:
    """Best-effort vendor label for a (site, page) window. Not a person claim.

    Single distinct vendor → that vendor name; mixed → the collective ``"AI
    agents"`` label. Site-scoped by construction.
    """
    result = await db.execute(
        select(AgentFetchEvent.vendor)
        .where(
            AgentFetchEvent.site_id == site_id,
            AgentFetchEvent.page_path == page_path,
            AgentFetchEvent.tier == "on-demand",
            AgentFetchEvent.created_at > since,
        )
        .distinct()
    )
    vendors = [v for (v,) in result.all() if v]
    if len(vendors) == 1:
        return vendors[0]
    return "AI agents"


async def _count_on_demand(
    db: AsyncSession,
    site_id: str,
    page_path: str,
    window_start: datetime,
    window_end: datetime | None = None,
) -> int:
    """Count on-demand fetches to a (site, page) in a time window. Site-scoped."""
    conditions = [
        AgentFetchEvent.site_id == site_id,
        AgentFetchEvent.page_path == page_path,
        AgentFetchEvent.tier == "on-demand",
        AgentFetchEvent.created_at > window_start,
    ]
    if window_end is not None:
        conditions.append(AgentFetchEvent.created_at <= window_end)
    result = await db.execute(
        select(func.count()).select_from(AgentFetchEvent).where(*conditions)
    )
    return int(result.scalar() or 0)


async def run_intent_signal_sweep(db: AsyncSession) -> dict[str, int]:
    """Periodic sweep: alert on live commercial-page agent fetches + spikes.

    Iterates distinct ``(site_id, page_path)`` pairs seen in the last 24h with
    ``tier == 'on-demand'`` and a commercial ``page_path``; for each qualifying
    pair sends a live intent alert, and additionally a spike alert when the
    rolling-window ``detect_spike`` fires. Both queries fit the existing
    ``idx_agent_fetch_events_site_path_tier_created`` composite index — no new
    index needed.

    Fail-open per (site, page): each pair is processed in its own try/except so
    one site's failure never blocks the rest. Returns counters.
    """
    counters = {"processed": 0, "alerted": 0, "spiked": 0}

    now = datetime.now(timezone.utc)
    current_start = now - timedelta(hours=_CURRENT_WINDOW_HOURS)
    trailing_start = now - timedelta(days=_TRAILING_DAYS + 1) + timedelta(
        hours=_CURRENT_WINDOW_HOURS
    )  # i.e. now - 8d + 24h  →  covers the 7 days preceding the current 24h.
    trailing_end = current_start

    # Distinct (site_id, page_path) pairs active in the current window. Commercial
    # filter is applied in Python (is_commercial_page is pure/no-SQL).
    pairs_result = await db.execute(
        select(AgentFetchEvent.site_id, AgentFetchEvent.page_path)
        .where(
            AgentFetchEvent.tier == "on-demand",
            AgentFetchEvent.created_at > current_start,
            AgentFetchEvent.page_path.is_not(None),
        )
        .distinct()
    )
    pairs = [
        (site_id, page_path)
        for site_id, page_path in pairs_result.all()
        if is_commercial_page(page_path)
    ]

    for site_id, page_path in pairs:
        try:
            counters["processed"] += 1

            site = (
                await db.execute(select(Site).where(Site.site_id == site_id))
            ).scalar_one_or_none()
            if site is None:
                continue

            current_24h = await _count_on_demand(
                db, site_id, page_path, current_start
            )
            if current_24h <= 0:
                continue

            vendor = await _dominant_vendor(db, site_id, page_path, current_start)

            sent = await maybe_send_intent_alert(
                db,
                site=site,
                page_path=page_path,
                vendor=vendor,
                hit_count=current_24h,
                window_minutes=_ALERT_WINDOW_MINUTES,
            )
            if sent:
                counters["alerted"] += 1

            trailing_count = await _count_on_demand(
                db, site_id, page_path, trailing_start, trailing_end
            )
            trailing_avg = trailing_count / _TRAILING_DAYS
            if detect_spike(current_24h, trailing_avg):
                multiplier = (
                    round(current_24h / trailing_avg, 1)
                    if trailing_avg > 0
                    else None
                )
                spiked = await maybe_send_intent_alert(
                    db,
                    site=site,
                    page_path=page_path,
                    vendor=vendor,
                    hit_count=current_24h,
                    window_minutes=_ALERT_WINDOW_MINUTES,
                    is_spike=True,
                    multiplier=multiplier,
                )
                if spiked:
                    counters["spiked"] += 1
        except Exception:
            # Per-(site,page) fail-open: log keys only (no PII / no page bodies).
            logger.exception(
                "intent_signal_sweep_pair_failed",
                site_id=site_id,
            )

    logger.info("intent_signal_sweep_done", **counters)
    return counters
