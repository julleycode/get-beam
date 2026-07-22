"""Persist a recognized AI-agent visit as an upserted ``agent_visits`` rollup row.

Consumed by the ingest hot path (``routers/events.py``) once
``agent_classifier.classify_agent`` returns a non-``None`` classification. This
module is deliberately **fail-open**: a persistence failure (missing table,
transient DB error) must NEVER break the human ingest response — the caller
treats it as fire-and-forget, exactly like the existing best-effort GeoIP path.

Structurally separate from Visitor/Event (SPEC D1) — agent traffic never touches
human visitor data.
"""

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.agent_visit import AgentVisit
from apps.api.services.agent_classifier import AgentClassification

logger = structlog.get_logger()


def _append_capped_path(paths: list[str], new_path: str | None, cap: int = 50) -> list[str]:
    """Append ``new_path`` to ``paths``, keeping it distinct and capped.

    - A ``None`` or empty ``new_path`` is a no-op (returns ``paths`` unchanged).
    - If ``new_path`` is already present, it is moved to the end (most-recently-
      seen ordering) rather than duplicated.
    - The result is truncated to the last ``cap`` entries (oldest-first,
      most-recent-last), so an already-over-``cap`` input is defensively trimmed.
    """
    if not new_path:
        return paths
    result = [p for p in paths if p != new_path]
    result.append(new_path)
    if len(result) > cap:
        result = result[-cap:]
    return result


async def persist_agent_visit(
    db: AsyncSession,
    site_id: str,
    classification: AgentClassification,
    ip_address: str,
    path: str | None,
) -> None:
    """Upsert the ``agent_visits`` rollup row for one agent visit. Fail-open.

    Counters and timestamps are race-free: ``visit_count`` uses a SQL-level
    ``visit_count + 1`` expression and ``last_seen_at`` is set unconditionally in
    the ``ON CONFLICT DO UPDATE`` clause, so concurrent visits increment
    correctly regardless of read staleness (same reasoning as the existing
    ``Visitor`` upsert's ``GREATEST(...)`` expression).

    ``page_paths`` is computed from a Python-side read taken before the atomic
    upsert. This tolerates a narrow, accepted cosmetic race: two *first-ever*
    visits for the same brand-new ``(site_id, vendor, product_or_ua_token)`` tuple
    landing together can cause one request's single path to be overwritten rather
    than merged. ``visit_count`` stays correct (SQL ``+1``). This is a
    data-completeness edge case only — it never affects the 204 response,
    multi-tenancy, or human data.
    """
    try:
        now = datetime.now(timezone.utc)

        existing = await db.execute(
            select(AgentVisit.page_paths).where(
                AgentVisit.site_id == site_id,
                AgentVisit.vendor == classification.vendor,
                AgentVisit.product_or_ua_token == classification.product_or_ua_token,
            )
        )
        existing_paths = existing.scalar_one_or_none()
        if existing_paths is None:
            new_paths = [path] if path else []
        else:
            new_paths = _append_capped_path(list(existing_paths), path)

        stmt = pg_insert(AgentVisit).values(
            site_id=site_id,
            vendor=classification.vendor,
            product_or_ua_token=classification.product_or_ua_token,
            verification_method=classification.verification_method,
            ip_address=ip_address or None,
            first_seen_at=now,
            last_seen_at=now,
            visit_count=1,
            page_paths=new_paths,
            resolved_company_id=None,
        ).on_conflict_do_update(
            index_elements=["site_id", "vendor", "product_or_ua_token"],
            set_={
                "page_paths": new_paths,
                "visit_count": AgentVisit.__table__.c.visit_count + 1,
                "last_seen_at": now,
                "ip_address": ip_address or None,
            },
        )
        await db.execute(stmt)
        await db.commit()
    except Exception as exc:
        # Fail-open: log keys/vendor/site_id only (NO raw UA, NO IP — PII/GDPR
        # guardrail), roll back, and swallow. Never raise into the ingest path.
        logger.warning(
            "agent_visit_persist_failed",
            site_id=site_id,
            vendor=classification.vendor,
            error=str(exc),
        )
        await db.rollback()
        return None
