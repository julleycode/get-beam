"""Which sites get the loosened all-US resolution eligibility.

Sites whose url hostname matches ``settings.resolve_all_us_domains`` (default
the owner's own getbeam.fyi) resolve every US visitor regardless of intent
score. All other sites keep the intent >= RESOLUTION_MIN_INTENT gate so
customer provider budgets aren't burned on low-intent traffic.
"""

from urllib.parse import urlparse

from sqlalchemy import func, select

from apps.api.config import settings


def _hostname(url: str | None) -> str:
    if not url:
        return ""
    raw = url if "://" in url else f"https://{url}"
    host = (urlparse(raw).hostname or "").lower()
    return host.removeprefix("www.")


def site_resolves_all_us(site_url: str | None) -> bool:
    """True when the site's url hostname is in resolve_all_us_domains."""
    domains = {
        d.strip().lower().removeprefix("www.")
        for d in settings.resolve_all_us_domains.split(",")
        if d.strip()
    }
    return bool(domains) and _hostname(site_url) in domains


async def first_win_boost_site_ids(db, site_ids) -> list[str]:
    """Of the given site_ids, return those still inside the first-win boost
    window (fewer than settings.first_win_boost_count IdentifiedVisitor rows).
    Empty when the boost is disabled (count <= 0).
    """
    # Imported here: models must never import services, and this keeps the
    # module import-cycle-free either direction.
    from apps.api.models.visitor import IdentifiedVisitor

    limit = settings.first_win_boost_count
    ids = [s for s in (site_ids or ()) if s]
    if limit <= 0 or not ids:
        return []

    rows = (
        await db.execute(
            select(IdentifiedVisitor.site_id, func.count().label("n"))
            .where(IdentifiedVisitor.site_id.in_(ids))
            .group_by(IdentifiedVisitor.site_id)
        )
    ).all()
    counts = {row.site_id: (row.n or 0) for row in rows}
    # Sites absent from the grouped result have zero identified visitors — they
    # are inside the window too, so default to 0 rather than dropping them.
    return [sid for sid in ids if counts.get(sid, 0) < limit]
