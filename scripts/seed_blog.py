"""Seed sample blog posts so the public /blog and SEO auditor have real pages.

Idempotent: skips a post if its slug already exists. Run:
    python scripts/seed_blog.py
"""

import asyncio

from sqlalchemy import select

from apps.api.models.blog_post import BlogPost  # noqa: F401
from apps.api.models.database import Base, async_session, engine
from apps.api.models.site import Site  # noqa: F401 — resolve blog_posts.site_id FK
from apps.api.services import blog_service

# Topics chosen for genuine SEO value to Beam (visitor ID / retargeting niche).
_SEED_POSTS = [
    {
        "title": "How to Identify Anonymous Website Visitors (2026 Guide)",
        "excerpt": "Most of your traffic leaves no name. Here's how visitor identification turns anonymous sessions into real people you can reach.",
        "tags": ["visitor-identification", "lead-generation", "guide"],
        "body_markdown": (
            "# How to Identify Anonymous Website Visitors\n\n"
            "Roughly 98% of website visitors never fill out a form. They browse, "
            "evaluate, and leave — anonymous. Visitor identification closes that gap "
            "by matching session signals to real profiles.\n\n"
            "## How it works\n\n"
            "A lightweight tracking pixel records page views and engagement. When a "
            "visitor shows intent, an identity-resolution step matches them against "
            "people and company data providers, returning a name, role, and company.\n\n"
            "## Why intent scoring matters\n\n"
            "Resolving every visitor is wasteful and often impossible. Scoring intent "
            "first — pages viewed, time on site, return visits — means you only spend "
            "lookups on visitors worth reaching.\n\n"
            "## Staying compliant\n\n"
            "Identify business contacts, honor opt-outs, and never email without a "
            "clear unsubscribe path. Compliance is a feature, not an afterthought."
        ),
    },
    {
        "title": "Website Visitor Retargeting: The Complete Playbook",
        "excerpt": "Turn identified visitors into pipeline with a retargeting playbook spanning email, social, and paid ads.",
        "tags": ["retargeting", "playbook", "marketing"],
        "body_markdown": (
            "# Website Visitor Retargeting: The Complete Playbook\n\n"
            "Identifying a visitor is step one. The value comes from what you do next: "
            "a coordinated retargeting motion across channels.\n\n"
            "## Segment by intent\n\n"
            "Group identified visitors by behavior — pricing-page viewers, repeat "
            "readers, demo abandoners. Each segment gets a different message.\n\n"
            "## Sequence the channels\n\n"
            "Lead with a personalized email, reinforce with social touches, and keep "
            "presence with paid retargeting. Never send without human approval.\n\n"
            "## Measure what closes\n\n"
            "Attribute replies and meetings back to segments so you double down on "
            "what works."
        ),
    },
    {
        "title": "Clay vs Retention.com vs Beam: Choosing a Visitor Identification Tool",
        "excerpt": "A practical comparison of visitor identification and enrichment tools for indie makers and DTC founders.",
        "tags": ["comparison", "tools", "visitor-identification"],
        "body_markdown": (
            "# Clay vs Retention.com vs Beam\n\n"
            "The visitor-identification market splits between enterprise-priced "
            "platforms and tools built for smaller teams. Here's how to choose.\n\n"
            "## What to compare\n\n"
            "- Match rate and data freshness\n"
            "- Per-resolution cost and daily caps\n"
            "- Built-in outreach vs export-only\n"
            "- Compliance posture\n\n"
            "## Built for indie makers\n\n"
            "If you want identification, enrichment, and AI-generated retargeting in "
            "one place — without enterprise pricing — that's the Beam thesis."
        ),
    },
    {
        "title": "What Is Intent Scoring and Why It Matters for B2B Sales",
        "excerpt": "Intent scoring ranks visitors by how likely they are to buy. Here's how to build a score that actually predicts pipeline.",
        "tags": ["intent-scoring", "b2b", "sales"],
        "body_markdown": (
            "# What Is Intent Scoring?\n\n"
            "Intent scoring assigns a number to each visitor based on behavior that "
            "correlates with buying: pages viewed, recency, frequency, and depth.\n\n"
            "## Signals that matter\n\n"
            "Pricing and product pages weigh heavily. So do return visits within a "
            "short window. A single bounce does not.\n\n"
            "## Acting on the score\n\n"
            "Set a threshold for identity resolution and outreach. Below it, keep "
            "watching. Above it, engage while intent is hot."
        ),
    },
    {
        "title": "GDPR-Safe Visitor Identification: What You Need to Know",
        "excerpt": "Visitor identification and privacy law can coexist. Here are the guardrails that keep your outreach compliant.",
        "tags": ["gdpr", "compliance", "privacy"],
        "body_markdown": (
            "# GDPR-Safe Visitor Identification\n\n"
            "Identification done right respects privacy law. Done wrong, it's a "
            "liability. The difference is in the guardrails.\n\n"
            "## Core principles\n\n"
            "- Focus on business contacts and legitimate interest\n"
            "- Provide a clear unsubscribe in every message\n"
            "- Suppress contacts who opt out or hard-bounce\n"
            "- Never store personal data in logs\n\n"
            "## Build trust\n\n"
            "Transparency converts. Tell people how you reach them and make leaving "
            "effortless."
        ),
    },
]


async def seed_blog() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    created = 0
    async with async_session() as db:
        for spec in _SEED_POSTS:
            base = blog_service.slugify(spec["title"])
            existing = (
                await db.execute(select(BlogPost.id).where(BlogPost.slug == base))
            ).scalar_one_or_none()
            if existing is not None:
                continue

            post = BlogPost(
                slug=base,
                title=spec["title"],
                excerpt=spec["excerpt"],
                body_markdown=spec["body_markdown"],
                tags=spec["tags"],
                author_name="Beam",
                status="published",
                published_at=blog_service.now_utc(),
            )
            post.reading_time_minutes = blog_service.reading_time_minutes(
                post.body_markdown
            )
            post.meta_title, post.meta_description, post.og_image_url = (
                blog_service.resolve_seo_meta(
                    title=post.title,
                    excerpt=post.excerpt,
                    body_markdown=post.body_markdown,
                    meta_title=None,
                    meta_description=None,
                    og_image_url=None,
                    cover_image_url=None,
                )
            )
            db.add(post)
            created += 1
        await db.commit()

    print(f"Seeded {created} blog post(s) ({len(_SEED_POSTS) - created} already existed).")


if __name__ == "__main__":
    asyncio.run(seed_blog())
