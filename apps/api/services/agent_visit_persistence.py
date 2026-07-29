"""Persist a recognized AI-agent visit as an upserted ``agent_visits`` rollup row.

Consumed by the ingest hot path (``routers/events.py``) once
``agent_classifier.classify_agent`` returns a non-``None`` classification. This
module is deliberately **fail-open**: a persistence failure (missing table,
transient DB error) must NEVER break the human ingest response — the caller
treats it as fire-and-forget, exactly like the existing best-effort GeoIP path.

Structurally separate from Visitor/Event (SPEC D1) — agent traffic never touches
human visitor data.
"""

import hashlib
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.agent_fetch_event import AgentFetchEvent
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


def build_dedup_key(
    *,
    site_id: str,
    vendor: str,
    raw_ua_token: str,
    page_path: str | None,
    natural_key: str | None,
) -> str | None:
    """Digest identifying one agent fetch for replay suppression, or ``None``.

    ``natural_key`` is the calling path's own retry-stable token — the pixel
    batch's client-minted ``event_id``, the edge beacon's mint token. Absent it
    (the gateway surfaces, and older pixel builds that predate ``event_id``)
    there is nothing that distinguishes a retry from a second genuine fetch, so
    this returns ``None`` and the row is stored unconditionally. Guessing a key
    would silently discard real fetches, which is the worse failure for a
    dashboard whose whole job is counting agent traffic.

    The digest deliberately covers more than the natural key:

    - ``site_id`` keeps the key space per-tenant, so a client-supplied
      ``event_id`` replayed against another site cannot occupy that site's key.
    - ``vendor`` + ``raw_ua_token`` keep two DIFFERENT agents distinct even when
      they share one natural key. The beacon's token is minted by the page
      render, and a cached render hands the same token to every fetcher that
      receives it — without the agent identity in the digest, ClaudeBot's fetch
      would be swallowed as a replay of GPTBot's.
    - ``page_path`` separates one agent's fetches of different pages.

    Hashing (rather than storing the tuple) bounds the key at 64 chars however
    long ``page_path`` runs, keeping it indexable.
    """
    if not natural_key:
        return None
    material = "|".join(
        (site_id, vendor, raw_ua_token, page_path or "", natural_key)
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


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


async def persist_agent_fetch_event(
    db: AsyncSession,
    site_id: str,
    classification: AgentClassification,
    tier: str,
    ip_address: str | None,
    page_path: str | None,
    event_time: datetime | None = None,
    dedup_key: str | None = None,
) -> None:
    """Insert one append-only ``agent_fetch_events`` row. Fail-open.

    Isolated from the ``persist_agent_visit`` rollup call — this insert has its
    own try/except and its own commit, so its failure never affects (and is
    never affected by) the rollup upsert.

    Append-only, with one narrow exception: when the caller supplies a
    ``dedup_key`` (see ``build_dedup_key``) the insert is a no-op if that exact
    key was already stored, so a retried or replayed write does not become a
    second fetch row. The conflict target is the PARTIAL unique index, so a
    ``None`` key cannot conflict with anything — including another ``None`` —
    and those rows keep their unconditional-insert behavior.

    ``event_time`` (H5 E1) — when provided (e.g. a mint-time decoded from a
    ``/pricing-overview/{token}`` beacon), it is written explicitly to
    ``created_at``; when ``None`` (the default, and every pre-H5 caller), the
    column keeps its ``Base.server_default=func.now()`` server-receive behavior.
    ``created_at`` is a ``server_default`` column, so setting mint-time is
    IMPOSSIBLE without this explicit override.
    """
    try:
        values = {
            "site_id": site_id,
            "vendor": classification.vendor,
            "raw_ua_token": classification.product_or_ua_token,
            "tier": tier,
            "page_path": page_path,
            "ip_address": ip_address or None,
            "verification_method": classification.verification_method,
            "dedup_key": dedup_key,
        }
        if event_time is not None:
            values["created_at"] = event_time
        await db.execute(
            pg_insert(AgentFetchEvent)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=["dedup_key"],
                # Must mirror the partial index's predicate exactly, or Postgres
                # cannot infer that index as the arbiter.
                index_where=text("dedup_key IS NOT NULL"),
            )
        )
        await db.commit()
    except Exception as exc:
        # Fail-open: log keys/vendor/site_id only (NO raw UA, NO IP — PII/GDPR
        # guardrail), roll back, and swallow. Never raise into the ingest path.
        logger.warning(
            "agent_fetch_event_persist_failed",
            site_id=site_id,
            vendor=classification.vendor,
            error=str(exc),
        )
        await db.rollback()
        return None


async def set_verification_method(db: AsyncSession, id, method: str) -> None:
    """Record one ``agent_visits`` row's ``verification_method`` by primary key.

    Called by the verification sweep (``agent_verification`` service) once it
    reaches a conclusion about the row's IP, never on the ingest hot path. Not
    only an upgrade: ``ip-mismatch`` is also written here, and it is a different
    conclusion rather than a higher one. Fail-open: on any error, roll back, log
    keys-only (``id``/``method`` — NEVER ip/UA/PII), and swallow; the caller
    treats the write as best-effort.
    """
    try:
        await db.execute(
            update(AgentVisit)
            .where(AgentVisit.id == id)
            .values(verification_method=method)
        )
        await db.commit()
    except Exception:
        logger.exception(
            "agent_visit_verification_upgrade_failed",
            id=str(id),
            method=method,
        )
        await db.rollback()
        return None
