"""Read-only workspace tools for the Gemini agent loop (/ai/ask, planner).

Every handler closes over an already-open AsyncSession plus the calling user,
so:
- tenant scoping is baked in — every query filters through the caller's own
  sites; model-supplied ids can never cross tenants;
- handlers are strictly READ-ONLY (no commit/flush — the session is shared
  with the request / Celery transaction the loop runs inside);
- model-supplied arguments are untrusted (steerable by injected visitor text
  earlier in the loop): types are checked, lengths/limits clamped;
- visitor- or LLM-derived text is sanitized before leaving the handler; the
  loop additionally fences `untrusted=True` payloads.

Unknown or foreign ids return {"error": "..."} as tool DATA (mirroring the
routers' 404-not-403 policy) so the model can recover without learning which
ids exist.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.prompt_safety import clean_text, sanitize_profiles
from apps.api.agents.segmenter import build_visitor_profiles
from apps.api.models.campaign import Campaign
from apps.api.models.draft import Draft, DraftStatus
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.segment import Segment, SegmentMember
from apps.api.models.site import Site
from apps.api.models.social_account import SocialAccount
from apps.api.models.user import User
from apps.api.models.visitor import Visitor
from apps.api.services.content_reader import build_recent_content
from apps.api.services.gemini_client import ToolSpec

_NO_ARGS = {"type": "object", "properties": {}}
_SITE_ID_ARG = {
    "type": "object",
    "properties": {
        "site_id": {"type": "string", "description": "The site_id (from the seed context or list_sites)."}
    },
    "required": ["site_id"],
}


async def site_snapshot(db: AsyncSession, site: Site) -> dict:
    """Counts for one site — shared by the /ai/ask context line and the
    get_site_stats tool so the two can never drift apart."""
    # Local import: routers ↔ agents would otherwise risk an import cycle.
    from apps.api.routers.visitors import _compute_visitor_stat_counts

    counts = await _compute_visitor_stat_counts(db, site.site_id)
    camp_rows = (
        await db.execute(
            select(Campaign.status, func.count())
            .where(Campaign.site_id == site.site_id)
            .group_by(Campaign.status)
        )
    ).all()
    camp = {status: int(n) for status, n in camp_rows}
    seg_count = (
        await db.execute(
            select(func.count())
            .select_from(Segment)
            .where(Segment.site_id == site.site_id)
        )
    ).scalar() or 0
    return {
        "site_id": site.site_id,
        "name": clean_text(site.name, 80),
        "url": clean_text(site.url, 120),
        "pixel_installed": bool(site.pixel_verified),
        "total_visitors": counts["total"],
        "identified": counts["identified"],
        "enriched": counts["enriched"],
        "ready_to_identify": counts["eligible_for_resolution"],
        "enriched_unsegmented": counts["enriched_unsegmented"],
        "segments": int(seg_count),
        "campaigns": {
            "draft": camp.get("draft", 0),
            "active": camp.get("active", 0),
            "completed": camp.get("completed", 0),
        },
    }


async def _owned_site(db: AsyncSession, user: User, site_id: object) -> Site | None:
    """Resolve a model-supplied site_id to one of the CALLER'S sites, or None."""
    if not isinstance(site_id, str) or not site_id or len(site_id) > 50:
        return None
    return (
        await db.execute(
            select(Site).where(Site.site_id == site_id, Site.user_id == user.id)
        )
    ).scalar_one_or_none()


def build_ask_tools(db: AsyncSession, user: User) -> list[ToolSpec]:
    """The /ai/ask allowlist: read-only lookups over the caller's workspace."""

    async def list_sites() -> dict:
        rows = (
            await db.execute(select(Site).where(Site.user_id == user.id))
        ).scalars().all()
        return {
            "sites": [
                {
                    "site_id": s.site_id,
                    "name": clean_text(s.name, 80),
                    "url": clean_text(s.url, 120),
                    "pixel_installed": bool(s.pixel_verified),
                }
                for s in rows
            ]
        }

    async def get_site_stats(site_id: str = "") -> dict:
        site = await _owned_site(db, user, site_id)
        if site is None:
            return {"error": "site not found"}
        return await site_snapshot(db, site)

    async def get_segments(site_id: str = "") -> dict:
        site = await _owned_site(db, user, site_id)
        if site is None:
            return {"error": "site not found"}
        rows = (
            await db.execute(
                select(Segment)
                .where(Segment.site_id == site.site_id)
                .order_by(Segment.created_at.desc())
                .limit(20)
            )
        ).scalars().all()
        return {
            "segments": [
                {
                    "segment_id": str(s.id),
                    "name": clean_text(s.name, 200),
                    "description": clean_text(s.description or "", 500),
                    "visitor_count": s.visitor_count,
                    "priority": clean_text(s.priority, 20),
                }
                for s in rows
            ]
        }

    async def get_campaigns(site_id: str = "", status: str = "") -> dict:
        site = await _owned_site(db, user, site_id)
        if site is None:
            return {"error": "site not found"}
        query = select(Campaign).where(Campaign.site_id == site.site_id)
        if isinstance(status, str) and status:
            query = query.where(Campaign.status == clean_text(status, 20))
        rows = (
            await db.execute(query.order_by(Campaign.created_at.desc()).limit(20))
        ).scalars().all()
        return {
            "campaigns": [
                {
                    "campaign_id": str(c.id),
                    "name": clean_text(c.name, 200),
                    "status": c.status,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "touchpoints": len((c.plan or {}).get("touchpoints") or []),
                }
                for c in rows
            ]
        }

    async def get_segment_visitors(segment_id: str = "", limit: int = 5) -> dict:
        try:
            seg_uuid = uuid.UUID(str(segment_id))
        except (TypeError, ValueError, AttributeError):
            return {"error": "segment not found"}
        seg = (
            await db.execute(
                select(Segment)
                .join(Site, Site.site_id == Segment.site_id)
                .where(Segment.id == seg_uuid, Site.user_id == user.id)
            )
        ).scalar_one_or_none()
        if seg is None:
            return {"error": "segment not found"}
        try:
            limit_n = max(1, min(int(limit), 10))
        except (TypeError, ValueError):
            limit_n = 5
        member_ids = [
            row[0]
            for row in (
                await db.execute(
                    select(SegmentMember.visitor_id)
                    .where(SegmentMember.segment_id == seg.id)
                    .limit(limit_n)
                )
            ).all()
        ]
        if not member_ids:
            return {"visitors": []}
        visitors = list(
            (
                await db.execute(
                    select(Visitor).where(
                        Visitor.site_id == seg.site_id,
                        Visitor.visitor_id.in_(member_ids),
                    )
                )
            ).scalars().all()
        )
        profiles = await build_visitor_profiles(db, seg.site_id, visitors)
        return {"visitors": sanitize_profiles(profiles)}

    async def get_pending_drafts_count() -> dict:
        pending = (
            await db.execute(
                select(func.count())
                .select_from(Draft)
                .where(Draft.user_id == user.id, Draft.status == DraftStatus.pending)
            )
        ).scalar() or 0
        return {"pending_drafts": int(pending)}

    return [
        ToolSpec(
            name="list_sites",
            description="List the user's sites with pixel install status.",
            parameters=_NO_ARGS,
            handler=list_sites,
            mock_args={},
        ),
        ToolSpec(
            name="get_site_stats",
            description=(
                "Visitor, segment, and campaign counts for one of the user's sites."
            ),
            parameters=_SITE_ID_ARG,
            handler=get_site_stats,
            untrusted=False,  # numeric counts + owner-controlled (cleaned) name/url
        ),
        ToolSpec(
            name="get_segments",
            description="List AI-built visitor segments for one site (newest first).",
            parameters=_SITE_ID_ARG,
            handler=get_segments,
        ),
        ToolSpec(
            name="get_campaigns",
            description=(
                "List campaigns for one site, optionally filtered by status "
                "(draft/approved/active/completed/paused)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "site_id": {"type": "string", "description": "The site_id."},
                    "status": {
                        "type": "string",
                        "description": "Optional status filter, e.g. 'draft' or 'active'.",
                    },
                },
                "required": ["site_id"],
            },
            handler=get_campaigns,
        ),
        ToolSpec(
            name="get_segment_visitors",
            description=(
                "Sample enriched visitor profiles belonging to one segment "
                "(segment_id from get_segments)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "segment_id": {"type": "string", "description": "The segment UUID."},
                    "limit": {
                        "type": "integer",
                        "description": "Max profiles to return (1-10, default 5).",
                    },
                },
                "required": ["segment_id"],
            },
            handler=get_segment_visitors,
        ),
        ToolSpec(
            name="get_pending_drafts_count",
            description="Number of social reply drafts awaiting the user's approval.",
            parameters=_NO_ARGS,
            handler=get_pending_drafts_count,
            untrusted=False,  # a single count
        ),
    ]


def build_planner_tools(
    db: AsyncSession, segment: Segment, user_id: uuid.UUID | None
) -> list[ToolSpec]:
    """Campaign-planner allowlist: on-demand personalization lookups, scoped
    to THIS segment's members and the site owner's connected accounts."""

    async def get_recent_content(visitor_id: str = "") -> dict:
        vid = str(visitor_id)[:100]
        member = (
            await db.execute(
                select(SegmentMember).where(
                    SegmentMember.segment_id == segment.id,
                    SegmentMember.visitor_id == vid,
                )
            )
        ).scalar_one_or_none()
        if member is None:
            return {"error": "visitor not in this segment"}
        profile = (
            await db.execute(
                select(EnrichmentProfile).where(
                    EnrichmentProfile.site_id == segment.site_id,
                    EnrichmentProfile.visitor_id == vid,
                )
            )
        ).scalar_one_or_none()
        if profile is None:
            return {"recent_content": ""}
        return {
            "recent_content": clean_text(
                build_recent_content(profile.social_context), 800
            )
        }

    async def get_connected_accounts() -> dict:
        if user_id is None:
            return {"accounts": []}
        rows = (
            await db.execute(
                select(SocialAccount).where(
                    SocialAccount.user_id == user_id,
                    SocialAccount.is_active.is_(True),
                )
            )
        ).scalars().all()
        return {
            "accounts": [
                {"platform": a.platform.value, "username": clean_text(a.username, 80)}
                for a in rows
            ]
        }

    return [
        ToolSpec(
            name="get_connected_accounts",
            description=(
                "List the user's connected social accounts (platform + username) — "
                "required before choosing social reply/DM channels."
            ),
            parameters=_NO_ARGS,
            handler=get_connected_accounts,
            untrusted=False,  # owner-controlled usernames, cleaned
            mock_args={},
        ),
        ToolSpec(
            name="get_recent_content",
            description=(
                "Fetch what one visitor in this segment recently posted "
                "(YouTube/Reddit/X or research summary) for personalization."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "visitor_id": {
                        "type": "string",
                        "description": "A visitor_id from the profiles in the prompt.",
                    }
                },
                "required": ["visitor_id"],
            },
            handler=get_recent_content,
        ),
    ]
