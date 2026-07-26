"""Behavioral stealth-crawler detection — pure signal functions (AC-1/2/3/13).

The fifth, ORTHOGONAL bot layer. Beam's four existing layers (tracker.js
webdriver check, bot_filter UA regex, agent_classifier self-declaring vendor
list, ingest_velocity flood shape) all reason about identity strings or
short-window traffic shape. A polite, low-volume daily crawl with a convincing UA
sails past all four and shows up in the dashboard as a real "Returning" visitor.

This module looks at BEHAVIOR OVER TIME instead, over two signals:

    cadence   = coefficient of variation (stddev/mean) of inter-visit gaps.
                A cron job produces near-identical gaps -> CV near 0. A human
                produces jitter -> CV well above 0.
    engagement = engagement-event-count / total-event-count. A scraper fires
                pageviews; it does not bother faking scroll/click/time-on-page.

The flag requires BOTH conditions (AC-3), matching the dual-condition philosophy
in ``ingest_velocity.evaluate_velocity``. Requiring low engagement as well as
rigid cadence is exactly what keeps the "power user" false positive out: someone
who checks the site every morning at 9am but actually reads and clicks has a low
CV and a HIGH engagement ratio, so the conjunction never fires (AC-13).

Sample-size preconditions are evaluated BEFORE any ratio math (same shape as
``ingest_velocity``): a 2-visit "perfectly regular" series is noise, not a
cadence.

VISIBILITY-ONLY (AC-5/6/7). Nothing here — and nothing that consumes it — sets
``is_abuse_flagged`` or ``do_not_resolve``, is read by ``is_emailable_identity``,
or joins the ``agent_visits`` table. Pure functions, zero I/O, zero DB session,
zero imports outside the stdlib.
"""

import statistics
from datetime import datetime

# Event types that a scripted fetcher has no incentive to fake. Matches the types
# apps/pixel/src/tracker.js actually emits. "pageview" is deliberately absent —
# it is the denominator, not a signal of engagement.
ENGAGEMENT_EVENT_TYPES = frozenset({"click", "scroll", "time_on_page", "conversion"})


def compute_cadence_variance(visit_timestamps: list[datetime]) -> float | None:
    """Coefficient of variation of inter-visit gaps. Pure, no I/O.

    Returns ``stddev(gaps) / mean(gaps)`` over the consecutive deltas (in
    seconds) of the sorted timestamps — a scale-free regularity measure, so an
    hourly bot and a daily bot both score near 0.

    Returns ``None`` when fewer than 2 gaps are computable (i.e. fewer than 3
    timestamps): the sample-size floor. ``None`` also on a degenerate mean of 0
    (all timestamps identical), which is not a cadence at all.
    """
    if len(visit_timestamps) < 3:
        return None

    ordered = sorted(visit_timestamps)
    gaps = [
        (later - earlier).total_seconds()
        for earlier, later in zip(ordered, ordered[1:])
    ]
    if len(gaps) < 2:
        return None

    mean_gap = statistics.fmean(gaps)
    if mean_gap <= 0:
        return None

    return statistics.stdev(gaps) / mean_gap


def compute_engagement_ratio(event_types: list[str]) -> float:
    """Fraction of events that are engagement events. Pure, no I/O.

    Returns ``0.0`` for an empty list — never divides by zero. An empty history
    scoring 0.0 is safe because the caller's separate min-visits precondition
    gates the decision before this value can matter.
    """
    if not event_types:
        return 0.0
    engaged = sum(1 for event_type in event_types if event_type in ENGAGEMENT_EVENT_TYPES)
    return engaged / len(event_types)


def evaluate_cadence_bot_flag(
    variance: float | None,
    engagement_ratio: float,
    min_visits_met: bool,
    max_variance_threshold: float,
    max_engagement_ratio: float,
) -> bool:
    """Pure decision function — True when this visitor looks like a stealth crawler.

    Structural sibling of ``ingest_velocity.evaluate_velocity``:
    precondition-before-ratio, then a strict conjunction.

    Both thresholds are passed IN (never read from settings here) so the module
    carries no magic number and the caller is forced to source them from
    operator-tunable config.
    """
    if not min_visits_met:
        return False
    if variance is None:
        return False
    return variance <= max_variance_threshold and engagement_ratio <= max_engagement_ratio
