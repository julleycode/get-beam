"""Known-contact matching: is a resolved email already in the customer's own CRM?

The customer uploads their contact list; we store only the HMAC blind index
(known_hash.email_hash), never plaintext. This centralizes the hash-vs-hash
lookup that was duplicated across the visitors list, CSV export, and (new)
enrichment, so "known" means the same thing everywhere and routing decisions
(skip paid enrichment, net-new vs existing) share one source of truth.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.known_contact import KnownContact
from apps.api.services.known_hash import email_hash


async def is_known_contact(
    db: AsyncSession, site_id: str, email: str | None
) -> tuple[bool, str | None]:
    """Return (is_known, source) for a single email against the site's CRM list.

    Best-effort: any lookup error returns (False, None) so a hiccup never blocks
    resolution/enrichment."""
    if not email:
        return (False, None)
    try:
        source = (
            await db.execute(
                select(KnownContact.source)
                .where(
                    KnownContact.site_id == site_id,
                    KnownContact.email_hash == email_hash(email),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return (source is not None, source)
    except Exception:
        return (False, None)


async def known_source_map(
    db: AsyncSession, site_id: str, email_hashes: set[str]
) -> dict[str, str]:
    """Map {email_hash: source} for the subset of `email_hashes` that are known.

    Callers that already hashed a page of emails pass the hashes directly; a
    single query returns the known ones. Empty input → empty map."""
    if not email_hashes:
        return {}
    rows = await db.execute(
        select(KnownContact.email_hash, KnownContact.source).where(
            KnownContact.site_id == site_id,
            KnownContact.email_hash.in_(list(email_hashes)),
        )
    )
    return {h: src for h, src in rows}
