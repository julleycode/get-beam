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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.engagement_attribution import EngagementAttribution

logger = structlog.get_logger()

# Prefix for Beam-generated UTM tags
_UTM_PREFIX = "beam_"


def _make_utm_tag() -> str:
    """Generate a short unique UTM tag."""
    return f"{_UTM_PREFIX}{uuid.uuid4().hex[:12]}"


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

    async def attribute_visitor(
        self,
        site_id: str,
        utm_source: Optional[str],
        is_identified: bool = False,
    ) -> None:
        """Increment attribution counters when a visitor arrives with a Beam UTM tag.

        Called during event ingestion when utm_source matches a known Beam tag.
        """
        if not utm_source or not utm_source.startswith(_UTM_PREFIX):
            return

        result = await self.db.execute(
            select(EngagementAttribution).where(
                EngagementAttribution.utm_tag == utm_source,
                EngagementAttribution.site_id == site_id,
            )
        )
        attribution = result.scalar_one_or_none()
        if not attribution:
            return

        attribution.new_visitors_count += 1
        if is_identified:
            attribution.new_identified_count += 1
        await self.db.commit()

        logger.info(
            "visitor_attributed",
            utm_tag=utm_source,
            site_id=site_id,
            is_identified=is_identified,
        )

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
