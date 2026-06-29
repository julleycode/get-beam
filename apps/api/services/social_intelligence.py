"""Social Intelligence service — fetches recent social posts for high-intent visitors.

For identified visitors with intent_score >= 60, this service fetches their
recent social content from:
1. The posts table (content already scraped via EasyEngage feed)
2. Twitter API (if bearer token configured and handle known)

Results are stored as `social_context` JSON on the EnrichmentProfile.
"""

from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.enrichment import EnrichmentProfile

logger = structlog.get_logger()

# Minimum intent score to fetch social context
SOCIAL_CONTEXT_MIN_INTENT = 60

# Simple topic keywords — no heavy NLP dependency
_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "AI/ML": ["ai", "machine learning", "llm", "gpt", "model", "neural", "inference", "rag"],
    "SaaS": ["saas", "b2b", "product", "startup", "founder", "mrr", "arr", "churn"],
    "Marketing": ["marketing", "seo", "content", "growth", "funnel", "ads", "campaign", "ctr"],
    "Engineering": ["code", "engineering", "developer", "backend", "frontend", "api", "deploy", "bug"],
    "Sales": ["sales", "crm", "pipeline", "outreach", "deal", "lead", "prospect", "close"],
    "Hiring": ["hiring", "job", "talent", "recruit", "candidate", "interview", "team"],
}


class SocialIntelligence:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def fetch_social_context(
        self,
        enrichment_profile: EnrichmentProfile,
        visitor_intent: float = 0.0,
    ) -> dict:
        """Fetch and aggregate recent social posts for an identified visitor.

        Returns a dict with:
          - recent_posts: list of {platform, content, url, posted_at, author}
          - topics: list of detected topic strings
          - sentiment: None (reserved for future enrichment)
        """
        if visitor_intent < SOCIAL_CONTEXT_MIN_INTENT:
            logger.debug(
                "social_context_skipped_low_intent",
                visitor_id=enrichment_profile.visitor_id,
                intent=visitor_intent,
            )
            return {"recent_posts": [], "topics": [], "sentiment": None}

        context: dict = {"recent_posts": [], "topics": [], "sentiment": None}

        # 1. Check posts table for any scraped content from this person
        scraped = await self._fetch_from_posts_table(
            enrichment_profile.twitter_handle,
        )
        context["recent_posts"].extend(scraped)

        # 2. Fetch from Twitter API if we have a handle and haven't found posts yet
        if enrichment_profile.twitter_handle and len(context["recent_posts"]) < 3:
            tweets = await self._fetch_recent_tweets(
                enrichment_profile.twitter_handle,
                limit=5,
            )
            # Deduplicate by content
            existing_contents = {p["content"] for p in context["recent_posts"]}
            for t in tweets:
                if t["content"] not in existing_contents:
                    context["recent_posts"].append(t)
                    existing_contents.add(t["content"])

        # 3. Extract topics from all collected posts
        context["topics"] = self._extract_topics(context["recent_posts"])

        logger.info(
            "social_context_fetched",
            visitor_id=enrichment_profile.visitor_id,
            post_count=len(context["recent_posts"]),
            topics=context["topics"],
        )
        return context

    async def store_social_context(
        self,
        enrichment_profile: EnrichmentProfile,
        context: dict,
    ) -> None:
        """Persist social context onto the enrichment profile."""
        enrichment_profile.social_context = context
        enrichment_profile.social_context_updated_at = datetime.now(timezone.utc)
        await self.db.commit()

    # ── Private helpers ────────────────────────────────────────────────

    async def _fetch_from_posts_table(
        self,
        twitter_handle: Optional[str],
    ) -> list[dict]:
        """Look up posts in the DB that were already scraped for this person."""
        if not twitter_handle:
            return []
        try:
            from apps.api.models.post import Post
            from apps.api.models.social_account import Platform

            handle_clean = twitter_handle.lstrip("@").lower()
            result = await self.db.execute(
                select(Post)
                .where(
                    Post.platform == Platform.twitter,
                    Post.author_username.ilike(handle_clean),
                )
                .order_by(Post.posted_at.desc())
                .limit(5)
            )
            posts = result.scalars().all()
            return [
                {
                    "platform": "twitter",
                    "content": p.content or "",
                    "url": p.post_url or "",
                    "posted_at": p.posted_at.isoformat() if p.posted_at else None,
                    "author": p.author_username,
                }
                for p in posts
                if p.content
            ]
        except Exception:
            logger.exception("social_context_db_posts_failed")
            return []

    async def _fetch_recent_tweets(
        self,
        handle: str,
        limit: int = 5,
    ) -> list[dict]:
        """Fetch recent tweets via Twitter API v2 or return mock data."""
        if not settings.twitter_bearer_token:
            return []

        handle_clean = handle.lstrip("@")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # First resolve handle → user_id
                user_resp = await client.get(
                    f"https://api.twitter.com/2/users/by/username/{handle_clean}",
                    headers={"Authorization": f"Bearer {settings.twitter_bearer_token}"},
                )
                if user_resp.status_code != 200:
                    logger.warning(
                        "twitter_user_lookup_failed",
                        handle=handle_clean,
                        status=user_resp.status_code,
                    )
                    return []

                user_id = user_resp.json().get("data", {}).get("id")
                if not user_id:
                    return []

                # Fetch recent tweets
                tweets_resp = await client.get(
                    f"https://api.twitter.com/2/users/{user_id}/tweets",
                    headers={"Authorization": f"Bearer {settings.twitter_bearer_token}"},
                    params={
                        "max_results": min(limit, 10),
                        "tweet.fields": "created_at,text",
                        "exclude": "retweets,replies",
                    },
                )
                if tweets_resp.status_code != 200:
                    logger.warning(
                        "twitter_tweets_failed",
                        handle=handle_clean,
                        status=tweets_resp.status_code,
                    )
                    return []

                tweets_data = tweets_resp.json().get("data", [])
                return [
                    {
                        "platform": "twitter",
                        "content": t.get("text", ""),
                        "url": f"https://twitter.com/{handle_clean}/status/{t['id']}",
                        "posted_at": t.get("created_at"),
                        "author": handle_clean,
                    }
                    for t in tweets_data
                ]
        except Exception:
            logger.exception("twitter_api_call_failed", handle=handle_clean)
            return []

    def _extract_topics(self, posts: list[dict]) -> list[str]:
        """Extract topic labels from post content using keyword matching."""
        if not posts:
            return []

        all_text = " ".join(p.get("content", "") for p in posts).lower()
        detected: list[str] = []

        for topic, keywords in _TOPIC_KEYWORDS.items():
            if any(kw in all_text for kw in keywords):
                detected.append(topic)

        return detected[:5]  # Cap at 5 topics

