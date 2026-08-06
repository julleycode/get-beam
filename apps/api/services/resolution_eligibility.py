"""Shared identity-resolution candidate eligibility.

Sites whose url hostname matches ``settings.resolve_all_us_domains`` (default
the owner's own getbeam.fyi) resolve every US visitor regardless of intent
score. All other sites keep the intent >= RESOLUTION_MIN_INTENT gate so
customer provider budgets aren't burned on low-intent traffic. AI-attributable
humans also qualify regardless of intent: either ``Visitor.ai_source`` is set
or a same-site, same-visitor ``AgentHandoffLink`` exists.
"""

from collections.abc import Collection
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from sqlalchemy import func, or_, select

from apps.api.config import settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement

    from apps.api.models.visitor import Visitor


def _hostname(url: str | None) -> str:
    if not url:
        return ""
    raw = url if "://" in url else f"https://{url}"
    host = (urlparse(raw).hostname or "").lower()
    return host.removeprefix("www.")


def site_resolves_all_us(site_url: str | None) -> bool:
    """True when the site's url hostname is in resolve_all_us_domains."""
    domains = {
        d.strip().lower().removeprefix("www.")
        for d in settings.resolve_all_us_domains.split(",")
        if d.strip()
    }
    return bool(domains) and _hostname(site_url) in domains


def ai_attributable_visitor_filter(
    *, handoff_linked: "ColumnElement[bool] | None" = None
):
    """SQL predicate for AI referral or same-site handoff attribution.

    Count/filter queries use the default correlated ``EXISTS``. Callers that
    already joined a deduplicated handoff-id set can inject that joined boolean
    to reuse it for filtering and ordering.
    """
    from apps.api.models.agent_handoff_link import AgentHandoffLink
    from apps.api.models.visitor import Visitor

    if handoff_linked is None:
        handoff_linked = (
            select(AgentHandoffLink.id)
            .where(
                AgentHandoffLink.site_id == Visitor.site_id,
                AgentHandoffLink.visitor_id == Visitor.visitor_id,
            )
            .exists()
        )
    return or_(Visitor.ai_source.is_not(None), handoff_linked)


def resolution_candidate_filter(
    all_us_site_ids: Collection[str] = (),
    no_floor_site_ids: Collection[str] = (),
    *,
    handoff_linked: "ColumnElement[bool] | None" = None,
):
    """SQL predicate for the complete resolution-candidate eligibility rule."""
    from apps.api.models.visitor import resolution_intent_filter

    return or_(
        resolution_intent_filter(all_us_site_ids, no_floor_site_ids),
        ai_attributable_visitor_filter(handoff_linked=handoff_linked),
    )


def resolution_not_deferred_filter():
    """SQL predicate excluding visitors held back by a provider outage.

    ``resolution_deferred_until`` is set when every provider tier that could
    have identified the visitor was down (see
    ``IdentityResolver.resolve``). Such rows stay ``anonymous`` so they get
    another chance, which means every query that feeds ``resolve()`` has to skip
    them until their watermark passes — otherwise "retryable" degrades into
    "retried on every single sweep".

    Both sweeps ORDER BY ``intent_score DESC`` under a LIMIT, and a deferred
    visitor keeps gaining intent while it waits. Miss this filter in any one
    sweep and that sweep re-selects the same deferred rows every run: it pays
    for ``check_ip_privacy`` on each, pushes the backoff forward, and crowds
    newer visitors out of the batch entirely.
    """
    from apps.api.models.visitor import Visitor

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return or_(
        Visitor.resolution_deferred_until.is_(None),
        Visitor.resolution_deferred_until <= now,
    )


async def is_resolution_candidate(
    db: "AsyncSession",
    visitor: "Visitor",
    *,
    site_url: str | None,
    no_floor_site_ids: Collection[str] | None = None,
) -> bool:
    """Evaluate the shared candidate rule for one already-loaded visitor."""
    from apps.api.models.agent_handoff_link import AgentHandoffLink
    from apps.api.models.visitor import RESOLUTION_MIN_INTENT

    if (
        (visitor.intent_score or 0) >= RESOLUTION_MIN_INTENT
        or visitor.ai_source is not None
        or (
            site_resolves_all_us(site_url)
            and (visitor.country_code or "").upper() == "US"
        )
    ):
        return True

    if no_floor_site_ids is None:
        no_floor_site_ids = await first_win_boost_site_ids(db, [visitor.site_id])
    if visitor.site_id in no_floor_site_ids:
        return True

    handoff_id = (
        await db.execute(
            select(AgentHandoffLink.id)
            .where(
                AgentHandoffLink.site_id == visitor.site_id,
                AgentHandoffLink.visitor_id == visitor.visitor_id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return handoff_id is not None


async def first_win_boost_site_ids(db, site_ids) -> list[str]:
    """Of the given site_ids, return those still inside the first-win boost
    window (fewer than settings.first_win_boost_count IdentifiedVisitor rows).
    Empty when the boost is disabled (count <= 0).
    """
    # Imported here: models must never import services, and this keeps the
    # module import-cycle-free either direction.
    from apps.api.models.visitor import IdentifiedVisitor

    limit = settings.first_win_boost_count
    ids = [s for s in (site_ids or ()) if s]
    if limit <= 0 or not ids:
        return []

    rows = (
        await db.execute(
            select(IdentifiedVisitor.site_id, func.count().label("n"))
            .where(IdentifiedVisitor.site_id.in_(ids))
            .group_by(IdentifiedVisitor.site_id)
        )
    ).all()
    counts = {row.site_id: (row.n or 0) for row in rows}
    # Sites absent from the grouped result have zero identified visitors — they
    # are inside the window too, so default to 0 rather than dropping them.
    return [sid for sid in ids if counts.get(sid, 0) < limit]
