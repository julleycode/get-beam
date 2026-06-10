"""Seed the community feature board with the candidate features distilled
from user feedback (community/audience-intelligence asks + integrations).

Idempotent: matches on exact title, only inserts what's missing.

Run (Railway shell or locally with DATABASE_URL set):
    python -m scripts.seed_feature_board
"""

import asyncio
import uuid

import structlog
from sqlalchemy import select

from apps.api.models.database import async_session
from apps.api.models.feature_request import FeatureRequest

logger = structlog.get_logger()

SEED_FEATURES: list[dict] = [
    {
        "title": "Subreddit map — which subreddits your visitors hang out in",
        "detail": (
            "For identified visitors, discover the subreddits they're active in "
            "so you know where to run ads and join conversations."
        ),
        "urgency": "useful",
    },
    {
        "title": "X/Twitter engagement themes — what they like, retweet, reply to",
        "detail": (
            "Per-visitor and per-segment rollup of what your identified visitors "
            "engage with on X — topics, accounts, content styles."
        ),
        "urgency": "useful",
    },
    {
        "title": "Lookalike discovery — more people like your best visitors",
        "detail": (
            "Find colleagues at the same company and similar-role people at "
            "similar companies, exportable as an outreach/ads audience."
        ),
        "urgency": "useful",
    },
    {
        "title": "Audience DNA — AI summary of who your audience really is",
        "detail": (
            "One card per segment: roles, industries, interests, communities, "
            "where they hang out — built from enrichment data Beam already has."
        ),
        "urgency": "useful",
    },
    {
        "title": "Facebook group insights — match members of a group you admin",
        "detail": (
            "Connect a Facebook group you run and see which of your website "
            "visitors are members. (Only works for groups you administer — "
            "there is no compliant way to see arbitrary users' groups.)"
        ),
        "urgency": "nice",
    },
    {
        "title": "PostHog sync — push Beam identities into PostHog profiles",
        "detail": (
            "When Beam identifies an anonymous visitor, enrich the matching "
            "PostHog person profile so your product analytics get names, "
            "companies, and roles."
        ),
        "urgency": "useful",
    },
]


async def seed() -> None:
    async with async_session() as db:
        created = 0
        for item in SEED_FEATURES:
            existing = await db.execute(
                select(FeatureRequest).where(FeatureRequest.title == item["title"])
            )
            if existing.scalar_one_or_none() is not None:
                continue
            db.add(
                FeatureRequest(
                    id=uuid.uuid4(),
                    title=item["title"],
                    detail=item["detail"],
                    urgency=item["urgency"],
                    source="seed",
                    status="new",
                )
            )
            created += 1
        await db.commit()
        logger.info("feature_board_seeded", created=created, total=len(SEED_FEATURES))
        print(f"Seeded {created} new feature(s) ({len(SEED_FEATURES) - created} already present).")


if __name__ == "__main__":
    asyncio.run(seed())
