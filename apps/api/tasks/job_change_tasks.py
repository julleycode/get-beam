"""Celery tasks for job-change detection (v1, same-tenant) — the two triggers.

TRIGGER A — ``recheck_returning_visitor``: event-driven. Dispatched
fire-and-forget from the ingest path when an already-identified visitor comes
back, so a re-check never adds latency to (or a hard dependency on) the ingest
request.

TRIGGER B — ``sweep_stale_profiles``: scheduled. Catches the people who do NOT
come back — precisely the population Trigger A structurally cannot see, and the
one most likely to have changed employer.

Both are thin wrappers: all detection logic (flag, budget, 4 safety gates,
comparison, corroboration, recording) lives in
``services/job_change_detector.py`` and runs identically from either entry
point, so neither trigger can drift into a weaker rule set than the other.

Both are inert while ``job_change_detection_enabled`` is False.
"""

import asyncio

import structlog
from sqlalchemy import select

from apps.api.config import settings
from apps.api.models.database import async_session
from apps.api.models.site import Site
from apps.api.models.visitor import Visitor
from apps.api.services.celery_app import celery_app
from apps.api.services.job_change_detector import (
    run_recheck,
    select_stale_visitors_query,
)

logger = structlog.get_logger()


@celery_app.task(name="apps.api.tasks.job_change_tasks.recheck_returning_visitor")
def recheck_returning_visitor(visitor_id: str, site_id: str) -> dict:
    """Trigger A entry point (sync Celery shim)."""
    return asyncio.run(_recheck_one(visitor_id, site_id))


async def _recheck_one(visitor_id: str, site_id: str) -> dict:
    if not settings.job_change_detection_enabled:
        return {"detected": 0, "skipped": "flag_off"}

    async with async_session() as db:
        visitor = (
            await db.execute(
                select(Visitor).where(
                    Visitor.site_id == site_id, Visitor.visitor_id == visitor_id
                )
            )
        ).scalar_one_or_none()
        if visitor is None:
            return {"detected": 0, "skipped": "no_visitor"}

        # The identity check lives HERE rather than at the ingest call site: the
        # ingest handler holds no Visitor ORM row (visitor rows are built by the
        # aggregator), so checking there would mean an extra DB round-trip on the
        # hot ingest path for a check this task has to do anyway.
        if visitor.identity_status == "anonymous":
            return {"detected": 0, "skipped": "not_identified"}

        site = (
            await db.execute(select(Site).where(Site.site_id == site_id))
        ).scalar_one_or_none()
        if site is None:
            return {"detected": 0, "skipped": "no_site"}

        event = await run_recheck(db, visitor, site)
        return {"detected": 1 if event else 0}


@celery_app.task(name="apps.api.tasks.job_change_tasks.sweep_stale_profiles")
def sweep_stale_profiles(limit: int | None = None) -> dict:
    """Trigger B entry point (sync Celery shim)."""
    return asyncio.run(_sweep(limit))


async def _sweep(limit: int | None = None) -> dict:
    if not settings.job_change_detection_enabled:
        return {"checked": 0, "detected": 0, "skipped": "flag_off"}

    # Bounded by the same number as the daily spend cap: the sweep can never
    # queue more work than a site is allowed to pay for in a day, so a large
    # backlog drains across days instead of burning a whole budget in one run.
    bound = limit or settings.job_change_recheck_daily_cap

    async with async_session() as db:
        rows = (await db.execute(select_stale_visitors_query(limit=bound))).all()

    checked = 0
    detected = 0
    for visitor_row, _profile in rows:
        # One session + one commit PER VISITOR, deliberately not one giant
        # transaction: a single bad row must not roll back or block the rest of
        # the sweep.
        async with async_session() as db:
            visitor = (
                await db.execute(
                    select(Visitor).where(
                        Visitor.site_id == visitor_row.site_id,
                        Visitor.visitor_id == visitor_row.visitor_id,
                    )
                )
            ).scalar_one_or_none()
            if visitor is None:
                continue
            site = (
                await db.execute(
                    select(Site).where(Site.site_id == visitor_row.site_id)
                )
            ).scalar_one_or_none()
            if site is None:
                continue
            checked += 1
            try:
                if await run_recheck(db, visitor, site):
                    detected += 1
            except Exception as exc:
                logger.warning(
                    "job_change_sweep_visitor_failed",
                    visitor_id=visitor_row.visitor_id[:8],
                    error=str(exc),
                )

    logger.info("job_change_sweep_complete", checked=checked, detected=detected)
    return {"checked": checked, "detected": detected}
