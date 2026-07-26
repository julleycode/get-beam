"""Re-run enrichment for identified visitors that have no profile.

Why a dedicated job: the resolution sweep only looks at visitors whose
``identity_status`` is still ``anonymous``, so a visitor that was identified and
then failed enrichment is NEVER revisited. Flipping ``enrichment_status`` back
to ``pending`` would not help — nothing reads it for already-identified rows.
This job calls ``Enricher.enrich_tier1`` directly for exactly that population.

Existing ``failed`` rows are the target: before the Apollo + domain fallback
chain existed, any PDL 404 ended the waterfall and stamped ``failed``.

COSTS REAL CREDITS. PDL misses stay negative-cached for 7 days (so they're free
and instant), but each Apollo person-match may consume ~1 Apollo credit when it
finds someone. Dry-run is the default; pass --apply to actually enrich.

    python -m apps.api.jobs.backfill_enrichment                 # dry run
    python -m apps.api.jobs.backfill_enrichment --apply         # enrich
    python -m apps.api.jobs.backfill_enrichment --apply --limit 20
    python -m apps.api.jobs.backfill_enrichment --apply --site site_f44740b94cea
"""

import argparse
import asyncio
import importlib
import pkgutil

import structlog

import apps.api.models as _models_pkg

for _m in pkgutil.iter_modules(_models_pkg.__path__):
    importlib.import_module(f"apps.api.models.{_m.name}")

from sqlalchemy import select  # noqa: E402

from apps.api.models.database import async_session  # noqa: E402
from apps.api.models.enrichment import EnrichmentProfile  # noqa: E402
from apps.api.models.visitor import IdentifiedVisitor, Visitor  # noqa: E402
from apps.api.services.enricher import Enricher  # noqa: E402

logger = structlog.get_logger()


async def backfill(*, apply: bool, limit: int, site_id: str | None) -> dict:
    """Re-enrich identified-with-email visitors that have no profile row."""
    counters = {"candidates": 0, "enriched": 0, "still_empty": 0, "errors": 0}

    async with async_session() as db:
        q = (
            select(Visitor, IdentifiedVisitor)
            .join(
                IdentifiedVisitor,
                (IdentifiedVisitor.site_id == Visitor.site_id)
                & (IdentifiedVisitor.visitor_id == Visitor.visitor_id),
            )
            .outerjoin(
                EnrichmentProfile,
                (EnrichmentProfile.site_id == Visitor.site_id)
                & (EnrichmentProfile.visitor_id == Visitor.visitor_id),
            )
            .where(
                IdentifiedVisitor.email.is_not(None),
                EnrichmentProfile.id.is_(None),
                # Agent-origin identities are never a real person.
                IdentifiedVisitor.source_agent_visit_id.is_(None),
            )
            .order_by(Visitor.intent_score.desc())
            .limit(limit)
        )
        if site_id:
            q = q.where(Visitor.site_id == site_id)

        rows = (await db.execute(q)).all()
        counters["candidates"] = len(rows)
        print(f"candidates: {len(rows)}" + (f" (site {site_id})" if site_id else ""))

        if not apply:
            for visitor, identified in rows:
                domain = (identified.email or "").rsplit("@", 1)[-1]
                print(
                    f"  would enrich {visitor.visitor_id[:8]} "
                    f"site={visitor.site_id} status={visitor.enrichment_status} "
                    f"domain={domain}"
                )
            print("\nDRY RUN — nothing called, nothing written. Re-run with --apply.")
            return counters

        enricher = Enricher(db)
        for visitor, identified in rows:
            try:
                profile = await enricher.enrich_tier1(visitor, identified)
                if profile:
                    counters["enriched"] += 1
                    print(
                        f"  enriched {visitor.visitor_id[:8]}: "
                        f"title={profile.job_title!r} company={profile.company_name!r}"
                    )
                else:
                    counters["still_empty"] += 1
                    print(f"  no match {visitor.visitor_id[:8]}")
            except Exception as exc:
                counters["errors"] += 1
                logger.exception(
                    "backfill_enrich_failed", visitor_id=visitor.visitor_id[:8]
                )
                print(f"  ERROR {visitor.visitor_id[:8]}: {type(exc).__name__} {exc}")
                await db.rollback()

    print(f"\n{counters}")
    return counters


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--apply",
        action="store_true",
        help="actually call providers and write profiles (costs credits)",
    )
    p.add_argument("--limit", type=int, default=50, help="max visitors (default 50)")
    p.add_argument("--site", default=None, help="restrict to one site_id")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(backfill(apply=args.apply, limit=args.limit, site_id=args.site))
