"""Backfill avatar_url for already-enriched visitors.

One-off companion to the social-avatar feature (plan/20260702_social_avatar):
existing EnrichmentProfile rows predate the avatar capture, so their
avatar_url is NULL until re-enriched. This fills it in place:

1. FREE — extract an avatar from OSINT profiles already stored in
   social_context (social_resolution.profiles[].extra.avatar/profile_pic).
2. API — for rows with a twitter_handle, fetch the profile image via
   Enricher._enrich_twitter (Redis-cached 7 days; official X API first,
   TwitterAPI.io fallback; cost-logged like normal enrichment).

Never overwrites an existing avatar_url. Refuses the Twitter path when
MOCK_EXTERNAL_APIS=true so mock URLs can't leak into real rows.

USAGE (from repo root; uses settings.database_url — root .env = prod!)
----------------------------------------------------------------------
    python -m scripts.backfill_avatars --dry-run              # count only, no writes
    python -m scripts.backfill_avatars                        # osint + twitter
    python -m scripts.backfill_avatars --no-twitter           # osint only (zero API calls)
    python -m scripts.backfill_avatars --site-id beam_getbeam_fyi
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

import apps.api.main  # noqa: F401  — registers every model on Base.metadata
from apps.api.config import settings
from apps.api.models.database import async_session, engine
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.services.enricher import Enricher, _avatar_from_social_context


async def run(site_id: str | None, dry_run: bool, use_twitter: bool) -> None:
    if use_twitter and settings.mock_external_apis:
        print("MOCK_EXTERNAL_APIS=true — refusing Twitter fetches (mock URLs must not land in real rows).")
        print("Re-run with --no-twitter for the free OSINT pass, or unset the mock flag.")
        use_twitter = False

    async with async_session() as db:
        q = select(EnrichmentProfile).where(EnrichmentProfile.avatar_url.is_(None))
        if site_id:
            q = q.where(EnrichmentProfile.site_id == site_id)
        profiles = list((await db.execute(q)).scalars().all())

        with_handle = sum(1 for p in profiles if p.twitter_handle)
        print(f"Profiles missing avatar_url: {len(profiles)}"
              + (f" (site {site_id})" if site_id else " (all sites)")
              + f" — {with_handle} have a twitter_handle (fetchable)")

        enricher = Enricher(db)
        bearer = settings.twitter_bearer_token or None
        twitter_possible = bool(bearer or settings.twitterapi_io_api_key)
        if use_twitter and not twitter_possible:
            print("No TWITTER_BEARER_TOKEN / TWITTERAPI_IO_API_KEY configured — Twitter pass will be skipped.")

        filled_osint = 0
        filled_twitter = 0
        skipped = 0

        for p in profiles:
            # 1) FREE: avatar already sitting in OSINT social_context
            url = _avatar_from_social_context(p.social_context)
            source = "osint"

            # 2) API: Twitter/X profile image (cached, cost-logged)
            if not url and use_twitter and twitter_possible and p.twitter_handle:
                data = await enricher._enrich_twitter(p.twitter_handle, api_key=bearer)
                url = data.get("avatar_url")
                source = "twitter"
                # Twitter's default-egg placeholder is worse than our initials
                # fallback — leave avatar_url NULL for those accounts.
                if url and "default_profile" in url:
                    url = None

            if not url:
                skipped += 1
                continue

            print(f"  {'[dry] ' if dry_run else ''}{p.site_id} {p.visitor_id[:8]}"
                  f"  {source:7s}  {url[:80]}")
            if not dry_run:
                p.avatar_url = url
            if source == "osint":
                filled_osint += 1
            else:
                filled_twitter += 1

        if not dry_run:
            await db.commit()

    await engine.dispose()
    action = "Would fill" if dry_run else "Filled"
    print(f"\n{action}: {filled_osint} from OSINT + {filled_twitter} from Twitter; "
          f"{skipped} left without avatar (no source).")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site-id", default=None, help="only this site")
    ap.add_argument("--dry-run", action="store_true", help="report only, no writes")
    ap.add_argument("--no-twitter", action="store_true", help="skip Twitter API pass (OSINT only)")
    args = ap.parse_args()

    asyncio.run(run(args.site_id, args.dry_run, use_twitter=not args.no_twitter))


if __name__ == "__main__":
    sys.exit(main())
