"""Auto-draft service — generates personalized engagement drafts for high-intent visitors.

When a visitor is identified AND has social context (recent posts), this service:
1. Picks the most relevant recent post
2. Generates a contextual comment/reply draft using the user's voice
3. Saves it as a Draft with auto_generated=True and visitor_id set

The draft appears in the user's drafts queue for review before any engagement.
"""

import re
import uuid
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.draft import Draft, DraftStatus, DraftType
from apps.api.models.social_account import Platform
from apps.api.models.user import User
from apps.api.models.visitor import Visitor

logger = structlog.get_logger()

# Minimum social context posts needed to generate a draft
_MIN_POSTS_FOR_DRAFT = 1

# Map platform string to Platform enum
_PLATFORM_MAP: dict[str, Platform] = {
    "twitter": Platform.twitter,
    "linkedin": Platform.linkedin,
    "instagram": Platform.instagram,
    "tiktok": Platform.tiktok,
    "facebook": Platform.facebook,
}

# Character limits per platform for auto-drafts
_CHAR_LIMITS: dict[Platform, int] = {
    Platform.twitter: 280,
    Platform.linkedin: 3000,
    Platform.instagram: 2200,
    Platform.tiktok: 150,
    Platform.facebook: 8000,
}


class AutoDrafter:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def generate_for_visitor(
        self,
        visitor: Visitor,
        enrichment_data: dict,
        social_context: dict,
        user: User,
        trigger_reason: Optional[str] = None,
    ) -> Optional[Draft]:
        """Auto-generate an engagement draft for a high-intent identified visitor.

        Args:
            visitor: The Visitor ORM object.
            enrichment_data: Dict with 'full_name', 'job_title', etc.
            social_context: Dict with 'recent_posts' and 'topics'.
            user: The site owner who will review/send the draft.
            trigger_reason: Optional non-social reason to draft (e.g.
                ``"job_change:Acme->Globex"``). ADDITIVE and OPTIONAL: when
                omitted, behavior is byte-identical to before — a recent social
                post is still required. When supplied, the event ITSELF is the
                thing worth reaching out about, so the recent-post precondition
                is satisfied by a synthesized context line instead. Either way
                the result is still a ``pending`` draft for human review; this
                parameter does not create a send path.

        Returns:
            A saved Draft instance, or None if generation is not possible.
        """
        recent_posts = social_context.get("recent_posts", [])
        if len(recent_posts) < _MIN_POSTS_FOR_DRAFT:
            if not trigger_reason:
                logger.debug(
                    "auto_draft_skipped_no_posts",
                    visitor_id=visitor.visitor_id,
                )
                return None
            # Non-social trigger: the event is the context. Shaped like a post
            # dict so every downstream step (platform pick, char limits, prompt
            # construction) stays on the one existing code path.
            recent_posts = [
                {
                    "content": trigger_reason,
                    "platform": "linkedin",
                    "author": enrichment_data.get("full_name") or "them",
                }
            ]

        # Pick the best (most recent) post
        best_post = recent_posts[0]
        post_content = best_post.get("content", "")
        if not post_content.strip():
            return None

        platform_str = best_post.get("platform", "linkedin")
        platform = _PLATFORM_MAP.get(platform_str, Platform.linkedin)

        # Generate the draft text
        draft_text = await self._generate_draft_text(
            visitor_name=enrichment_data.get("full_name") or "this person",
            visitor_role=enrichment_data.get("job_title"),
            recent_post=best_post,
            user_tone=user.tone_preference or "casual",
            platform=platform,
            user_id=user.id,
        )

        context_summary = f"Re: {post_content[:100]}"

        # Resolve the site key at creation time. On this path the visitor is
        # always known, so precedence step 1 normally settles it; None is still
        # accepted and every consumer fails closed on it.
        from apps.api.services.engagement_tracker import derive_draft_site_id

        site_id = await derive_draft_site_id(
            self.db, user_id=user.id, visitor_id=visitor.visitor_id
        )

        draft = Draft(
            user_id=user.id,
            type=DraftType.comment,
            platform=platform,
            ai_content=draft_text,
            status=DraftStatus.pending,
            auto_generated=True,
            visitor_id=visitor.visitor_id,
            context_summary=context_summary,
            site_id=site_id,
        )
        self.db.add(draft)
        await self.db.commit()
        await self.db.refresh(draft)

        logger.info(
            "auto_draft_created",
            visitor_id=visitor.visitor_id[:8],
            platform=platform_str,
            draft_id=str(draft.id)[:8],
        )
        return draft

    # ── Private helpers ────────────────────────────────────────────────

    async def _generate_draft_text(
        self,
        visitor_name: str,
        visitor_role: Optional[str],
        recent_post: dict,
        user_tone: str,
        platform: Platform,
        user_id: uuid.UUID,
    ) -> str:
        """Generate draft text via the existing AI reply infrastructure."""
        try:
            from apps.api.services.ai_reply import generate_draft

            post_content = recent_post.get("content", "")
            author = recent_post.get("author", "them")

            # Add visitor context to the draft prompt
            context_hint = f"This person ({visitor_name}"
            if visitor_role:
                context_hint += f", {visitor_role}"
            context_hint += ") recently visited your site."

            draft_text = await generate_draft(
                platform=platform,
                original_content=post_content,
                original_author=author,
                tone=user_tone,
                context=context_hint,
                db=self.db,
                user_id=user_id,
                strategy="conversational",
            )
            return draft_text

        except Exception:
            logger.exception(
                "auto_draft_generation_failed",
                visitor_name=visitor_name,
                platform=platform.value,
            )
            # Only fall back to a canned mock draft in explicit mock mode. In real
            # mode an LLM failure must NOT persist a fake draft as if the AI wrote
            # it — re-raise so the caller logs + skips this draft.
            if settings.mock_external_apis:
                return self._mock_draft(visitor_name, visitor_role, recent_post, platform)
            raise

    def _mock_draft(
        self,
        visitor_name: str,
        visitor_role: Optional[str],
        recent_post: dict,
        platform: Platform,
    ) -> str:
        """Return a plausible mock draft for dev/test mode."""
        post_snippet = re.sub(r"\s+", " ", recent_post.get("content", ""))[:60]
        role_context = f" ({visitor_role})" if visitor_role else ""

        mock_by_platform: dict[Platform, str] = {
            Platform.twitter: f"Really interesting take on '{post_snippet}...' — curious what led you there.",
            Platform.linkedin: (
                f"Came across your recent post on '{post_snippet}...' — really resonates"
                f"{role_context}. Would love to connect and hear more about your perspective."
            ),
            Platform.instagram: f"This post got me thinking! Love the angle on '{post_snippet}...'",
            Platform.tiktok: "this is so real",
            Platform.facebook: f"Great perspective on '{post_snippet}...' — totally agree with your take.",
        }
        return mock_by_platform.get(platform, f"Loved your recent post — '{post_snippet}...'")
