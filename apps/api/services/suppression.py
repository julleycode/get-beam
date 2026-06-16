"""Privacy suppression list service (GDPR/CCPA).

A suppression entry records that a person asked us to stop processing / selling /
emailing them. Lookups and storage use a blind index (HMAC of the email) so we
never keep a second plaintext copy of the address.

When an entry is added we also CASCADE to existing data: matching identified
visitors get ``do_not_email`` and their visitor rows get ``do_not_resolve`` —
so the opt-out takes effect immediately, not just on future activity. The
identity resolver and the CSV exporter consult this list as a live gate.
"""

import structlog
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.suppression import SuppressionEntry
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.models.visitor_email import VisitorEmail
from apps.api.services.pii_crypto import email_hash, normalize_email

logger = structlog.get_logger()

VALID_SCOPES = {"all", "do_not_sell", "do_not_process", "do_not_email"}


async def is_email_suppressed(db: AsyncSession, email: str, scope: str) -> bool:
    """True if this email is suppressed for the given scope (or "all")."""
    if not email:
        return False
    result = await db.execute(
        select(SuppressionEntry.id)
        .where(
            SuppressionEntry.email_hash == email_hash(email),
            SuppressionEntry.scope.in_([scope, "all"]),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _cascade_suppress(db: AsyncSession, email: str, scope: str) -> dict:
    """Apply the opt-out to data we already hold for this email.

    - do_not_email on matching IdentifiedVisitor rows (blocks sending + export)
    - do_not_resolve on the corresponding Visitor rows (blocks resolution)

    Matched case-insensitively by plaintext email (the suppression row itself
    stores only the hash). Does NOT decrypt anything — Phase 05 will revisit
    once PII is encrypted.
    """
    norm = normalize_email(email)
    blocks_resolve = scope in ("all", "do_not_process")
    blocks_email = scope in ("all", "do_not_email", "do_not_sell")

    pairs: set[tuple[str, str]] = set()
    id_rows = (
        await db.execute(
            select(IdentifiedVisitor.site_id, IdentifiedVisitor.visitor_id).where(
                func.lower(IdentifiedVisitor.email) == norm
            )
        )
    ).all()
    pairs.update((r[0], r[1]) for r in id_rows)
    ve_rows = (
        await db.execute(
            select(VisitorEmail.site_id, VisitorEmail.visitor_id).where(
                VisitorEmail.email == norm
            )
        )
    ).all()
    pairs.update((r[0], r[1]) for r in ve_rows)

    n_email = 0
    if blocks_email:
        r = await db.execute(
            update(IdentifiedVisitor)
            .where(func.lower(IdentifiedVisitor.email) == norm)
            .values(do_not_email=True)
        )
        n_email = r.rowcount or 0

    n_resolve = 0
    if blocks_resolve:
        for site_id, visitor_id in pairs:
            r = await db.execute(
                update(Visitor)
                .where(Visitor.site_id == site_id, Visitor.visitor_id == visitor_id)
                .values(do_not_resolve=True)
            )
            n_resolve += r.rowcount or 0

    return {"identified_suppressed": n_email, "visitors_blocked": n_resolve}


async def add_suppression(
    db: AsyncSession,
    email: str,
    scope: str = "all",
    reason: str | None = None,
    requested_by: str | None = None,
) -> dict:
    """Add an email to the suppression list and cascade to existing data."""
    stmt = (
        pg_insert(SuppressionEntry)
        .values(
            email_hash=email_hash(email),
            scope=scope,
            reason=reason,
            requested_by=requested_by,
        )
        .on_conflict_do_nothing(index_elements=["email_hash", "scope"])
    )
    await db.execute(stmt)
    cascaded = await _cascade_suppress(db, email, scope)
    await db.commit()
    logger.info("suppression_added", scope=scope, **cascaded)
    return {"scope": scope, **cascaded}


async def remove_suppression(db: AsyncSession, email: str, scope: str) -> int:
    """Remove a suppression entry. Does NOT reverse the cascade — already-set
    do_not_email / do_not_resolve flags stay, so un-suppressing can never
    silently re-enable processing of someone who once opted out."""
    r = await db.execute(
        delete(SuppressionEntry).where(
            SuppressionEntry.email_hash == email_hash(email),
            SuppressionEntry.scope == scope,
        )
    )
    await db.commit()
    return r.rowcount or 0


async def list_suppressions(db: AsyncSession, limit: int = 500) -> list[SuppressionEntry]:
    result = await db.execute(
        select(SuppressionEntry)
        .order_by(SuppressionEntry.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
