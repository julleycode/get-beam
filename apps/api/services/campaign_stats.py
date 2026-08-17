"""The single definition of the Beam campaign funnel.

Two exports, deliberately different in kind (marketing-claims-gap Phase 3, D6/B2):

* **Shared SQL count expressions** (:func:`sent_count_expr`,
  :func:`opened_count_expr`, :func:`clicked_count_expr`) — the ``sent`` /
  ``opened`` / ``clicked`` predicates as reusable SQLAlchemy expressions.
  ``routers/outcomes.py`` imports these INTO its existing grouped aggregate, so
  its no-row-materialization shape, its per-campaign grouping, and its query
  cost are all preserved exactly. "Single funnel definition" means one PREDICATE
  SET, not one Python function.
* **A pure** :func:`summarize` — used by the BENCHMARK path only. It takes rows
  already fetched and returns a :class:`CampaignStats`. Materializing rows is
  acceptable there because it is an offline weekly job over one site's period,
  never an authed request path.

Measurement honesty (Hazard 1):

* **No sends is not a measured zero.** With zero sends the rollup reports
  ``has_data=False`` and ``open_rate is None`` — surfaces must render "no data",
  never "0% open rate". With N sends and zero opens it reports a measured ``0.0``.
* **Open rate is unreliable in both directions.** Per ``routers/open_pixel.py``,
  Apple Mail Privacy Protection prefetches the pixel (overcount) and image
  blocking suppresses it (undercount); clicks are the reliable signal. Every
  open-rate value this module emits carries :data:`OPEN_RATE_CAVEAT`, and every
  surface must render the caveat rather than bury it.

Nothing here is gated on ``identity_signals_enabled`` — that flag covers identity
corroboration (``IdentitySignal``), not campaign open/click, which is recorded
ungated by ``routers/open_pixel.py`` and ``routers/events.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, NamedTuple

from sqlalchemy import func

from apps.api.models.campaign import CampaignTouchpoint

# Rendered next to EVERY open-rate value, in every surface (digest, report,
# planner prompt). Kept as one constant so the caveat cannot drift per surface.
OPEN_RATE_CAVEAT = (
    "Open rates are unreliable: Apple Mail Privacy Protection prefetches "
    "tracking pixels (overcounting) and blocked images suppress them "
    "(undercounting). Clicks are the reliable signal."
)


# ─── Shared count expressions (the predicate set) ───
#
# The asymmetry below is INTENTIONAL and mirrors the pre-existing
# routers/outcomes.py behavior exactly: `sent` carries `status == "sent"` AND the
# cutoff; `opened`/`clicked` carry only their is_not(None) predicate plus the
# cutoff. Changing it would silently move published /outcomes numbers.


def sent_count_expr(cutoff: datetime):
    """COUNT of touchpoints marked sent within the window."""
    return func.count().filter(
        CampaignTouchpoint.status == "sent",
        CampaignTouchpoint.sent_at >= cutoff,
    )


def opened_count_expr(cutoff: datetime):
    """COUNT of touchpoints sent in the window that recorded an open."""
    return func.count().filter(
        CampaignTouchpoint.opened_at.is_not(None),
        CampaignTouchpoint.sent_at >= cutoff,
    )


def clicked_count_expr(cutoff: datetime):
    """COUNT of touchpoints sent in the window that recorded a click."""
    return func.count().filter(
        CampaignTouchpoint.clicked_at.is_not(None),
        CampaignTouchpoint.sent_at >= cutoff,
    )


# ─── Pure rollup (benchmark path only) ───


class TouchpointRow(NamedTuple):
    """The minimal shape :func:`summarize` needs. Any object exposing these four
    attributes (including an ORM ``CampaignTouchpoint``) is accepted."""

    channel: str
    status: str
    opened_at: datetime | None
    clicked_at: datetime | None


class CampaignStats(NamedTuple):
    sends: int
    opens: int
    clicks: int
    conversions: int

    @property
    def has_data(self) -> bool:
        """False = no sends at all. Surfaces must render "no data" here, NEVER
        a 0% rate — an unsent campaign has not been measured."""
        return self.sends > 0

    @property
    def open_rate(self) -> float | None:
        """Opens / sends, or None when there were no sends. Always render with
        :data:`OPEN_RATE_CAVEAT`."""
        if self.sends <= 0:
            return None
        return self.opens / self.sends

    @property
    def click_rate(self) -> float | None:
        if self.sends <= 0:
            return None
        return self.clicks / self.sends


def summarize(
    rows: Iterable,
    *,
    channel: str | None = None,
    conversions: int = 0,
) -> CampaignStats:
    """Roll fetched touchpoint rows into a :class:`CampaignStats`. PURE.

    ``channel`` filters rows to a single delivery channel. The benchmark rollup
    passes ``channel="email"``; this is DEFENSIVE, not a fix for a live bug —
    ``campaign_sender.py`` is the sole ``CampaignTouchpoint`` constructor and
    hardcodes ``channel="email"``. The column is free ``String(50)`` and the
    unique constraint permits social rows, so the filter protects the invariant
    against future social-send work.

    ``/outcomes`` does NOT use this function (it reuses the count expressions
    above instead) and has never filtered on channel.
    """
    sends = opens = clicks = 0
    for row in rows:
        if channel is not None and row.channel != channel:
            continue
        if row.status == "sent":
            sends += 1
        if row.opened_at is not None:
            opens += 1
        if row.clicked_at is not None:
            clicks += 1
    return CampaignStats(
        sends=sends, opens=opens, clicks=clicks, conversions=int(conversions)
    )
