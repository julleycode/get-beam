"""Shared ad-audience push logic — used by the router (sync) and the Celery
task (async).

The contact-resolution and safety-filter chain is NOT reimplemented here: it is
imported verbatim from services/csv_exporter.py (``_get_segment_visitors`` for
the suppression/do-not-email/agent-derived/do-not-sell filter chain, ``_sha256``
for hashing), so a CSV export and an API push always target the exact same
people. csv_exporter.py itself is never modified.

Only SHA256 digests leave this module — the payload builder emits
``HashedContact`` rows and no plaintext identifier ever reaches a provider.
"""

import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.ad_audience_link import AdAudienceLink
from apps.api.models.ad_connection import AdConnection
from apps.api.models.segment import SegmentMember
from apps.api.services.ads.base import HashedContact, sanitize_error
from apps.api.services.ads.factory import get_provider
from apps.api.services.csv_exporter import _get_segment_visitors, _sha256

logger = structlog.get_logger()

# SPEC OQ5: real per-platform minimum audience sizes are a Phase 2/3 docs-fetch
# item. Until then this placeholder drives the small-segment warning only — it
# never blocks a push.
MIN_AUDIENCE_SIZE = 1000


@dataclass
class PushSegmentOutcome:
    found: bool
    pushed: int = 0
    failed: int = 0
    skipped: int = 0
    queued: bool = False
    platform_audience_id: str = ""
    warning: str = ""
    errors: list[str] = field(default_factory=list)


def build_hashed_contacts(rows: list[dict]) -> list[HashedContact]:
    """Turn visitor rows into hash-only audience members.

    Every field is SHA256(lowercased, stripped) via csv_exporter._sha256 — the
    same digest the Meta CSV export writes. Empty inputs stay empty (never a
    hash of "") so a provider can't match on a constant.
    """
    contacts: list[HashedContact] = []
    for row in rows:
        email = (row.get("email") or "").strip()
        if not email:
            continue

        def h(key: str) -> str:
            value = (row.get(key) or "").strip()
            return _sha256(value) if value else ""

        contacts.append(
            HashedContact(
                email_sha256=_sha256(email),
                phone_sha256=h("phone"),
                first_name_sha256=h("first_name"),
                last_name_sha256=h("last_name"),
                city_sha256=h("city"),
                region_sha256=h("region"),
                country_sha256=h("country"),
            )
        )
    return contacts


async def get_connection(
    db: AsyncSession, site_id: str, provider: str
) -> AdConnection | None:
    result = await db.execute(
        select(AdConnection).where(
            AdConnection.site_id == site_id, AdConnection.provider == provider
        )
    )
    return result.scalar_one_or_none()


async def _get_link(
    db: AsyncSession, connection_id, segment_id: str
) -> AdAudienceLink | None:
    result = await db.execute(
        select(AdAudienceLink).where(
            AdAudienceLink.connection_id == connection_id,
            AdAudienceLink.segment_id == segment_id,
        )
    )
    return result.scalar_one_or_none()


async def push_segment_to_ads(
    db: AsyncSession, site_id: str, provider: str, segment_id: str
) -> PushSegmentOutcome:
    """Push one segment's safety-cleared, hashed contacts to one ad connection.

    No rate-limit check here — callers reserve a slot before invoking (so the
    Celery task and the request path don't double-count), matching crm_push.
    """
    conn = await get_connection(db, site_id, provider)
    if conn is None:
        return PushSegmentOutcome(found=False)

    member_count = (
        await db.scalar(
            select(func.count())
            .select_from(SegmentMember)
            .where(SegmentMember.segment_id == segment_id)
        )
        or 0
    )

    # Offload big segments to a worker when enabled (and one is running).
    if settings.ads_async_push and member_count > settings.ads_async_push_threshold:
        from apps.api.tasks.ads_tasks import push_segment_to_ads_task

        push_segment_to_ads_task.delay(site_id, provider, segment_id)
        logger.info(
            "ads_push_queued", site_id=site_id, provider=provider, members=member_count
        )
        return PushSegmentOutcome(found=True, queued=True)

    # Identical safety-filter chain to the CSV export and the CRM push:
    # do_not_email, non-emailable identity (incl. agent-derived), do_not_sell.
    rows = await _get_segment_visitors(db, segment_id, exclude_known=False)
    contacts = build_hashed_contacts(rows)
    skipped = max(0, member_count - len(contacts))

    link = await _get_link(db, conn.id, segment_id)

    provider_impl = get_provider(provider)
    try:
        result = await provider_impl.create_or_update_audience(conn, link, contacts)
    except NotImplementedError:
        raise
    except Exception as exc:  # noqa: BLE001 — persist a sanitized, PII-free error
        conn.status = "error"
        conn.is_valid = False
        conn.last_error = sanitize_error(exc, "Audience push failed")[:500]
        await db.commit()
        logger.warning("ads_push_failed", site_id=site_id, provider=provider)
        return PushSegmentOutcome(
            found=True, failed=len(contacts), skipped=skipped, errors=[conn.last_error]
        )

    now = datetime.now(timezone.utc)
    # Upsert the (connection_id, segment_id) link so a repeat push reuses the
    # same platform audience instead of creating a second one. ON CONFLICT keeps
    # two simultaneous pushes race-safe.
    stmt = (
        pg_insert(AdAudienceLink)
        .values(
            id=_uuid.uuid4(),
            connection_id=conn.id,
            segment_id=segment_id,
            platform_audience_id=result.platform_audience_id,
            last_pushed_at=now,
            last_push_count=result.pushed,
        )
        .on_conflict_do_update(
            constraint="uq_ad_audience_link",
            set_={
                "platform_audience_id": result.platform_audience_id,
                "last_pushed_at": now,
                "last_push_count": result.pushed,
            },
        )
    )
    await db.execute(stmt)

    conn.last_pushed_at = now
    if result.failed and not result.pushed:
        conn.status = "error"
        conn.is_valid = False
        conn.last_error = "; ".join(result.errors)[:500] or "Push failed"
    else:
        conn.status = "connected"
        conn.last_error = None
    await db.commit()

    warning = ""
    if len(contacts) < MIN_AUDIENCE_SIZE:
        warning = (
            f"This audience has {len(contacts)} matched contacts — ad platforms "
            f"typically need around {MIN_AUDIENCE_SIZE} before an audience becomes "
            "usable for targeting."
        )

    logger.info(
        "ads_push_completed",
        site_id=site_id,
        provider=provider,
        segment_id=segment_id,
        pushed=result.pushed,
        failed=result.failed,
        skipped=skipped,
    )
    return PushSegmentOutcome(
        found=True,
        pushed=result.pushed,
        failed=result.failed,
        skipped=skipped,
        platform_audience_id=result.platform_audience_id,
        warning=warning,
        errors=result.errors,
    )
