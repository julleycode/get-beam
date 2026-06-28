"""Shared CRM push logic — used by the router (sync), the Celery task (async),
and the auto-push-on-segmentation hook.

Keeping the connection lookup, token refresh, contact shaping, and the push
itself in one place means all three callers get the same suppression guards
(via csv_exporter._get_segment_visitors) and the same connection-status
bookkeeping.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.crm_connection import CrmConnection
from apps.api.models.segment import SegmentMember
from apps.api.services.crm import get_crm_connector
from apps.api.services.crm.contact_mapper import rows_to_contacts
from apps.api.services.crm_rate_limiter import check_and_reserve_push
from apps.api.services.csv_exporter import _get_segment_visitors
from apps.api.services.encryption import decrypt_token, encrypt_token
from apps.api.services.key_vault import decrypt_key

logger = structlog.get_logger()


@dataclass
class PushOutcome:
    found: bool
    pushed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


async def get_connection(
    db: AsyncSession, site_id: str, provider: str
) -> CrmConnection | None:
    result = await db.execute(
        select(CrmConnection).where(
            CrmConnection.site_id == site_id, CrmConnection.provider == provider
        )
    )
    return result.scalar_one_or_none()


async def fresh_access_token(db: AsyncSession, conn: CrmConnection) -> str:
    """Return a usable access token, refreshing first if expired."""
    token = decrypt_token(conn.access_token) if conn.access_token else ""
    expires = conn.token_expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if not (expires and expires <= datetime.now(timezone.utc)):
        return token
    if not conn.refresh_token:
        return token
    connector = get_crm_connector(conn.provider)
    tokens = await connector.refresh_tokens(decrypt_token(conn.refresh_token))
    conn.access_token = encrypt_token(tokens.access_token)
    if tokens.refresh_token:
        conn.refresh_token = encrypt_token(tokens.refresh_token)
    conn.token_expires_at = tokens.expires_at
    if tokens.external_account_id:
        conn.external_account_id = tokens.external_account_id
    await db.commit()
    return tokens.access_token


async def push_segment(
    db: AsyncSession, site_id: str, provider: str, segment_id: str
) -> PushOutcome:
    """Push one segment's emailable contacts to one connection. No rate-limit
    check here — callers reserve a slot before invoking (so the Celery task and
    the request path don't double-count)."""
    conn = await get_connection(db, site_id, provider)
    if conn is None:
        return PushOutcome(found=False)

    member_count = await db.scalar(
        select(func.count())
        .select_from(SegmentMember)
        .where(SegmentMember.segment_id == segment_id)
    )
    rows = await _get_segment_visitors(db, segment_id)  # suppression-filtered
    contacts = rows_to_contacts(rows, conn.field_mapping)
    skipped = max(0, (member_count or 0) - len(contacts))

    connector = get_crm_connector(provider)
    if conn.auth_type == "oauth":
        access_token = await fresh_access_token(db, conn)
        result = await connector.upsert_contacts(
            contacts, access_token=access_token, instance_url=conn.external_account_id or ""
        )
    else:
        secret = decrypt_key(conn.encrypted_secret) if conn.encrypted_secret else ""
        result = await connector.upsert_contacts(
            contacts, webhook_url=conn.webhook_url or "", secret=secret
        )

    conn.last_pushed_at = datetime.now(timezone.utc)
    if result.failed and not result.pushed:
        conn.status = "error"
        conn.is_valid = False
        conn.last_error = "; ".join(result.errors)[:500] or "Push failed"
    else:
        conn.status = "connected"
        conn.last_error = None
    await db.commit()

    logger.info(
        "crm_push_completed",
        site_id=site_id,
        provider=provider,
        segment_id=segment_id,
        pushed=result.pushed,
        failed=result.failed,
        skipped=skipped,
    )
    return PushOutcome(
        found=True,
        pushed=result.pushed,
        failed=result.failed,
        skipped=skipped,
        errors=result.errors,
    )


async def auto_push_segments(
    db: AsyncSession, site_id: str, segment_ids: list[str]
) -> None:
    """Best-effort: push each new segment to every connected CRM for a site.

    Gated behind settings.crm_auto_push (off by default). Never raises — a CRM
    hiccup must not break segmentation. Respects the per-site hourly push cap.
    """
    if not settings.crm_auto_push or not segment_ids:
        return
    result = await db.execute(
        select(CrmConnection).where(
            CrmConnection.site_id == site_id, CrmConnection.status == "connected"
        )
    )
    connections = list(result.scalars().all())
    for conn in connections:
        for segment_id in segment_ids:
            if not await check_and_reserve_push(site_id):
                logger.info("crm_auto_push_rate_limited", site_id=site_id)
                return
            try:
                await push_segment(db, site_id, conn.provider, segment_id)
            except Exception as exc:  # noqa: BLE001 — auto-push is best-effort
                logger.warning(
                    "crm_auto_push_failed",
                    site_id=site_id,
                    provider=conn.provider,
                    error=str(exc),
                )
