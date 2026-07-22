"""Seed changelog entries for recent shipped work.

This repo commits straight to `main` (no PRs), so the GitHub→Gemini
auto-sync in `changelog_generator.sync_from_github` never sees this work.
This one-off backfills the customer-facing commits by hand, applying the
same editorial brief the auto-sync uses (plain, benefit-led, no jargon,
internal/backend work dropped).

Idempotent: skips an entry whose `source_ref` already exists, so re-running
is safe. `source_ref` uses the `commit-<shorthash>` namespace — distinct from
the sync's `pr-<number>`, so the two paths never collide.

Run:
    python scripts/seed_changelog.py
"""

import asyncio
from datetime import datetime

from sqlalchemy import select

from apps.api.models.changelog_entry import ChangelogEntry
from apps.api.models.database import Base, async_session, engine

# Recent customer-facing commits, newest first. Each stamps `published_at`
# with the commit date so the landing-page timeline orders correctly.
# Internal work (PII backfill, SSRF pin, AI JSON-repair/tool-loop plumbing,
# harness install, marketing restructure) is intentionally omitted.
_SEED_ENTRIES = [
    {
        "source_ref": "commit-fb78ac9",
        "category": "fixed",
        "title": "No more duplicate campaign sends",
        "body": "A campaign can no longer send twice if it's triggered at the "
        "same moment from two places — each send is claimed once.",
        "published_at": "2026-07-22T11:12:39+07:00",
    },
    {
        "source_ref": "commit-7b70529",
        "category": "improved",
        "title": "Pick your platform when we can't detect it",
        "body": "Onboarding now lets you choose your site platform by hand if "
        "auto-detection comes up empty, so pixel setup never stalls.",
        "published_at": "2026-07-21T07:21:32+07:00",
    },
    {
        "source_ref": "commit-80fa3da",
        "category": "improved",
        "title": "Auto-detects Next.js and Framer sites",
        "body": "We now recognise Next.js and Framer sites automatically and "
        "give you the right install snippet without guesswork.",
        "published_at": "2026-07-21T07:21:26+07:00",
    },
    {
        "source_ref": "commit-dd385c9",
        "category": "improved",
        "title": "Cleaner visitor data, less bot noise",
        "body": "Traffic from proxies and VPNs is now dropped before it reaches "
        "your visitor list, so what you see is closer to real people.",
        "published_at": "2026-07-21T07:21:19+07:00",
    },
    {
        "source_ref": "commit-263c06e",
        "category": "new",
        "title": "Ask Beam now uses your workspace data",
        "body": "The Ask feature can pull from your own visitors and campaigns to "
        "answer questions, falling back to a direct reply when it can't.",
        "published_at": "2026-07-21T07:03:17+07:00",
    },
]


async def seed_changelog() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    created = 0
    async with async_session() as db:
        for spec in _SEED_ENTRIES:
            existing = (
                await db.execute(
                    select(ChangelogEntry.id).where(
                        ChangelogEntry.source_ref == spec["source_ref"]
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue

            db.add(
                ChangelogEntry(
                    title=spec["title"],
                    body=spec["body"],
                    category=spec["category"],
                    status="published",
                    published_at=datetime.fromisoformat(spec["published_at"]),
                    source_ref=spec["source_ref"],
                )
            )
            created += 1
        await db.commit()

    print(
        f"Seeded {created} changelog entry(ies) "
        f"({len(_SEED_ENTRIES) - created} already existed)."
    )


if __name__ == "__main__":
    asyncio.run(seed_changelog())
