"""Outlier / internal-traffic damping — pure signal functions.

WHY THIS EXISTS (measured live on production, 2026-07-27): 3 of 4 customer sites
draw 89-95% of their 90-day events from fewer than 20 visitors each. On one site
a single visitor produced 30,562 events over 20 days from 12 distinct IP /16
blocks, with full scroll + dwell engagement — almost certainly the site owner or
their staff. Because ``resolution_runner`` orders candidates by
``intent_score.desc()``, these visitors are resolved FIRST on every sweep and eat
the site's daily identity-resolution budget (37.5% of it on one measured site).

Two harms, two treatments, both applied elsewhere (this module only DECIDES):
  1. analytics distortion  -> exclude from site-level cross-visitor aggregates
  2. budget skew           -> deprioritise (never exclude) in resolution ordering

SITE-RELATIVE, NEVER GLOBAL. Site scale in the measured data ranges from 29 to
532 visitors, so a fixed global event-count threshold is meaningless. Every
decision here is made against the site's OWN distribution of per-visitor event
counts.

ENGAGEMENT POLARITY IS INVERTED vs ``cadence_bot_flag``. That module flags a
visitor when engagement is ABSENT (a scraper fires pageviews and never scrolls).
This module requires engagement to be PRESENT: engagement is exactly what
separates a heavy HUMAN (the owner) from a heavy SCRAPER. A high-volume visitor
with no scroll/click/dwell is a crawler and belongs to the cadence/bot layer, not
here — so it must NOT be flagged as internal.

HONESTY CONSTRAINT (binding). "Heavy" is inferred, never proven. Nothing here
detects "the owner"; it detects a statistical outlier. All user-facing copy must
say "unusually high activity" and must never assert the visitor's identity.

Pure functions, zero I/O, zero DB session, no settings reads — every threshold is
passed in by the caller, matching the ``cadence_bot_flag`` convention so the
module carries no magic number.
"""

import statistics
from datetime import datetime

# Reused verbatim — already fully generic (event-type list in, ratio out).
from apps.api.services.cadence_bot_flag import compute_engagement_ratio

__all__ = [
    "compute_engagement_ratio",
    "compute_event_count_outlier_score",
    "compute_multi_day_persistence",
    "evaluate_outlier_flag",
]


def compute_event_count_outlier_score(
    visitor_event_count: int,
    site_event_counts: list[int],
    min_sample_size: int,
) -> float | None:
    """How far this visitor's event volume sits above their OWN site's typical visitor.

    Returns ``visitor_event_count / median(site_event_counts)`` — a scale-free
    ratio, so a 29-visitor site and a 532-visitor site are judged on the same
    axis. A visitor at their site's median scores 1.0; the measured Grade Coach
    outlier (1,993 events vs a median near 12) scores in the hundreds.

    Median, not mean: the outliers we are looking for would drag a mean upward
    and mask themselves.

    Returns ``None`` — "cannot judge" — when:
      * the site has fewer than ``min_sample_size`` visitors (no distribution to
        be an outlier against), mirroring ``compute_cadence_variance``'s
        sample-size floor, or
      * the site's median is <= 0 (degenerate; every ratio would be infinite).

    ``None`` NEVER means "flag it" — ``evaluate_outlier_flag`` treats it as False.
    """
    if len(site_event_counts) < min_sample_size:
        return None

    median = statistics.median(site_event_counts)
    if median <= 0:
        return None

    return visitor_event_count / median


def compute_multi_day_persistence(
    visit_timestamps: list[datetime], min_days: int
) -> bool:
    """True when the elevated activity spans ``min_days`` distinct calendar days.

    Guards against the single-day burst: one afternoon of 2,000 events is a load
    test, a bug, or a one-off scrape — not the sustained pattern of someone who
    works on the site every day. Distinct DAYS, never raw event count, for the
    same reason the cadence sweep counts visit-days.
    """
    if min_days <= 0:
        return True
    if not visit_timestamps:
        return False
    return len({ts.date() for ts in visit_timestamps}) >= min_days


def evaluate_outlier_flag(
    outlier_score: float | None,
    engagement_ratio: float,
    persistent: bool,
    min_sample_met: bool,
    outlier_threshold: float,
    min_engagement_ratio: float,
) -> bool:
    """Pure decision — True when this visitor's traffic should be damped.

    Strict conjunction of four conditions, sample-size precondition FIRST (same
    shape as ``evaluate_cadence_bot_flag`` / ``ingest_velocity.evaluate_velocity``):

      1. the site has enough visitors to have a distribution at all
      2. the volume ratio vs the site's own median clears ``outlier_threshold``
      3. the activity is sustained across multiple days, not a single burst
      4. engagement is PRESENT at or above ``min_engagement_ratio``
         — note ``>=``, the INVERSE of the cadence-bot flag's ``<=`` ceiling

    Condition 4 is the false-positive brake in the scraper direction, and
    conditions 2+3 are the brake in the enthusiastic-prospect direction. All four
    must hold; any one failing returns False.

    Both thresholds are passed IN — never read from settings here.
    """
    if not min_sample_met:
        return False
    if outlier_score is None:
        return False
    if not persistent:
        return False
    return (
        outlier_score >= outlier_threshold
        and engagement_ratio >= min_engagement_ratio
    )
