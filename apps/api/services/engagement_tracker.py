"""Engagement attribution tracker — measures Beam flywheel ROI.

Flow:
1. User engages (posts comment/DM via Beam) → record_engagement() → returns UTM tag
2. New visitor arrives with utm_source matching the UTM tag → attribute_visitor()
3. GET /engagement/roi → returns aggregate ROI stats

UTM tag format: beam_{uuid4_short} — short enough to fit in URL params.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.engagement_attribution import EngagementAttribution

logger = structlog.get_logger()

# Prefix for Beam-generated UTM tags
_UTM_PREFIX = "beam_"


def _make_utm_tag() -> str:
    """Generate a short unique UTM tag."""
    return f"{_UTM_PREFIX}{uuid.uuid4().hex[:12]}"


def make_utm_tag() -> str:
    """Public alias — the send path mints a tag before it has a row to attach it to.

    Exists so `sender.mint_attribution_tag` never reaches for the module-private
    name; the tag format stays owned here.
    """
    return _make_utm_tag()


_SEEN_TTL_SECONDS = 30 * 24 * 3600


async def _first_sighting(site_id: str, utm_tag: str, visitor_id: str) -> bool:
    """True exactly once per (site, tag, visitor) within the TTL. Fail-closed."""
    try:
        from apps.api.services.redis_client import get_redis

        key = f"engage_attr_seen:{site_id}:{utm_tag}:{visitor_id[:64]}"
        return bool(await get_redis().set(key, "1", nx=True, ex=_SEEN_TTL_SECONDS))
    except Exception as exc:
        logger.warning("engage_attr_dedupe_unavailable", error_type=type(exc).__name__)
        return False


async def derive_draft_site_id(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    visitor_id: Optional[str] = None,
) -> Optional[str]:
    """Resolve the site a new draft belongs to. Returns the site SLUG or None.

    Both `Draft` producers (`services/auto_drafter.py`, `routers/drafts.py`) call
    this so the precedence lives in exactly one place:

    1. `visitor_id` present → that visitor's site. `uq_visitors_site_visitor` is
       `(site_id, visitor_id)`, so the same visitor id CAN legitimately exist under
       two sites; more than one row is AMBIGUOUS and resolves to None rather than
       an arbitrary pick.
    2. Else the owning user has exactly ONE site → that site.
    3. Else → None.

    Returning None is a documented limit, not a failure: a multi-site user's
    manual draft carries no `visitor_id` (the manual path never sets one), so it
    lands on step 2, and a multi-site owner therefore resolves to None. Every
    consumer fails CLOSED on None — no attribution mint, no autonomy eligibility,
    excluded from site aggregates. That is the safe direction; the alternative is
    silently attributing a draft to the wrong tenant's site.

    Never raises: a derivation failure degrades to None so it can never block
    draft creation.
    """
    from apps.api.models.site import Site
    from apps.api.models.visitor import Visitor

    try:
        if visitor_id:
            # Tenant-scoped: only sites the drafting user OWNS are candidates.
            # Without the Site join a visitor_id that also exists under another
            # tenant's site would resolve to (or make ambiguous) a site this user
            # does not own, attributing the draft cross-tenant.
            result = await db.execute(
                select(Visitor.site_id)
                .join(Site, Site.site_id == Visitor.site_id)
                .where(Visitor.visitor_id == visitor_id, Site.user_id == user_id)
            )
            site_ids = {row[0] for row in result.all() if row[0]}
            if len(site_ids) == 1:
                return site_ids.pop()
            if len(site_ids) > 1:
                # Ambiguous across tenants — refuse to guess.
                logger.info(
                    "draft_site_id_ambiguous_visitor",
                    visitor_id=visitor_id[:8],
                    candidates=len(site_ids),
                )
                return None

        result = await db.execute(
            select(Site.site_id).where(Site.user_id == user_id).limit(2)
        )
        owned = [row[0] for row in result.all()]
        if len(owned) == 1:
            return owned[0]
        logger.info(
            "draft_site_id_unresolved",
            user_id=str(user_id)[:8],
            owned_sites=len(owned),
        )
        return None
    except Exception as exc:
        logger.warning("draft_site_id_derivation_failed", error_type=type(exc).__name__)
        return None


class EngagementTracker:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record_engagement(
        self,
        user_id: uuid.UUID,
        site_id: str,
        platform: str,
        engagement_type: str,
        post_url: Optional[str] = None,
        draft_id: Optional[uuid.UUID] = None,
    ) -> str:
        """Record a new engagement and return its unique UTM tag.

        Args:
            user_id: The Beam user performing the engagement.
            site_id: The site this engagement is attributed to.
            platform: 'twitter' | 'linkedin' | etc.
            engagement_type: 'comment' | 'dm' | 'like'
            post_url: URL of the post being engaged with.
            draft_id: Optional draft that was used for this engagement.

        Returns:
            utm_tag: Unique tag to append to outbound links for attribution.
        """
        utm_tag = _make_utm_tag()

        attribution = EngagementAttribution(
            user_id=user_id,
            site_id=site_id,
            platform=platform,
            engagement_type=engagement_type,
            target_post_url=post_url,
            draft_id=draft_id,
            utm_tag=utm_tag,
        )
        self.db.add(attribution)
        await self.db.commit()

        logger.info(
            "engagement_recorded",
            user_id=str(user_id)[:8],
            site_id=site_id,
            platform=platform,
            utm_tag=utm_tag,
        )
        return utm_tag

    def stage_engagement(
        self,
        *,
        user_id: uuid.UUID,
        site_id: str,
        platform: str,
        engagement_type: str,
        utm_tag: str,
        post_url: Optional[str] = None,
        draft_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Add an attribution row to the session WITHOUT committing.

        `record_engagement` commits internally, which the send path cannot use:
        the tag has to exist in the posted text BEFORE `post_comment` runs, but
        the row must land in the SAME transaction as `status=sent` (C3) so a
        failed post never leaves a committed attribution row behind. Staging
        lets `send_draft` own the commit boundary.

        The caller supplies `utm_tag` because it already embedded that exact tag
        in the content — regenerating one here would silently mint a tag that
        matches no link.
        """
        self.db.add(
            EngagementAttribution(
                user_id=user_id,
                site_id=site_id,
                platform=platform,
                engagement_type=engagement_type,
                target_post_url=post_url,
                draft_id=draft_id,
                utm_tag=utm_tag,
            )
        )

    async def attribute_visitor(
        self,
        site_id: str,
        utm_source: Optional[str],
        is_identified: bool = False,
        visitor_id: Optional[str] = None,
    ) -> bool:
        """Increment attribution counters when a visitor arrives with a Beam UTM tag.

        Called during event ingestion when utm_source matches a known Beam tag.
        Returns True when the counters were incremented.

        Hardening (public, unauthenticated ingest path):
        - Dedupe per (tag, visitor_id): every pageview batch of the same visitor
          carries the same utm_source, so counting per batch inflated
          ``new_visitors_count`` by the visitor's pageview count — and let any
          caller who saw a tagged link inflate it at will. A Redis SET NX marker
          (30-day TTL) makes it once per visitor. If Redis is unavailable we do
          NOT count (fail-closed: undercount beats an inflatable metric).
          ``visitor_id=None`` keeps the legacy un-deduped behavior for callers
          that have no visitor context.
        - Atomic increment: ``UPDATE ... SET n = n + 1`` instead of an ORM
          read-modify-write, so concurrent batches cannot lose updates.
        """
        if not utm_source or not utm_source.startswith(_UTM_PREFIX):
            return False

        result = await self.db.execute(
            select(EngagementAttribution.id).where(
                EngagementAttribution.utm_tag == utm_source,
                EngagementAttribution.site_id == site_id,
            )
        )
        attribution_id = result.scalar_one_or_none()
        if attribution_id is None:
            return False

        if visitor_id is not None and not await _first_sighting(
            site_id, utm_source, visitor_id
        ):
            return False

        values = {
            "new_visitors_count": EngagementAttribution.new_visitors_count + 1,
        }
        if is_identified:
            values["new_identified_count"] = EngagementAttribution.new_identified_count + 1
        await self.db.execute(
            update(EngagementAttribution)
            .where(EngagementAttribution.id == attribution_id)
            .values(**values)
        )
        await self.db.commit()

        logger.info(
            "visitor_attributed",
            utm_tag=utm_source,
            site_id=site_id,
            is_identified=is_identified,
        )
        return True

    async def get_engagement_roi(
        self,
        user_id: uuid.UUID,
        days: int = 30,
    ) -> dict:
        """Compute ROI stats for a user over the past N days.

        Returns:
            {
                total_engagements: int,
                new_visitors_attributed: int,
                identified_from_engagement: int,
                period_days: int,
            }
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)

        result = await self.db.execute(
            select(
                func.count(EngagementAttribution.id).label("total"),
                func.coalesce(func.sum(EngagementAttribution.new_visitors_count), 0).label("visitors"),
                func.coalesce(func.sum(EngagementAttribution.new_identified_count), 0).label("identified"),
            ).where(
                EngagementAttribution.user_id == user_id,
                EngagementAttribution.engaged_at >= since,
            )
        )
        row = result.one()

        return {
            "total_engagements": row.total or 0,
            "new_visitors_attributed": int(row.visitors or 0),
            "identified_from_engagement": int(row.identified or 0),
            "period_days": days,
        }
