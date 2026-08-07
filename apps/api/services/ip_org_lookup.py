"""Longest-prefix IP → organization lookup against the self-hosted table.

The free, zero-cost rung of the company-resolution ladder. Reads
``ip_org_prefixes`` (built by ``ip_org_ingest``) and returns the owner of the
MOST SPECIFIC announced prefix containing the address.

Two rules the query cannot be written without:

1. ``prefix >>= :ip`` returns EVERY containing prefix — a /8 and a /24 both
   match. ``ORDER BY masklen(prefix) DESC LIMIT 1`` picks the specific one; the
   naive query without it returns an arbitrary row and would attribute a
   customer's /24 to whoever holds the covering /8.
2. ``org_kind = 'org'`` is applied at READ time, not at ingest. Eyeball/datacenter
   /CDN prefixes are stored on purpose (other consumers want them), but resolving
   a consumer-ISP prefix to a "company" fabricates an employer — the same class
   of bug that produced ``cdurham@fastly.com`` from a Fastly edge IP.

Fail-open at every level: a missing table, a malformed address, or any database
error returns ``None``. This runs inside the resolver, and a lookup hiccup must
never break identification.
"""

from typing import TypedDict

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.ip_org_prefix import IP_ORG_TABLE

logger = structlog.get_logger()


class IpOrgMatch(TypedDict):
    """The owner of the most specific prefix containing a queried address."""

    org_name: str
    domain: str | None
    asn: int
    org_kind: str


_LOOKUP_SQL = text(
    f"SELECT org_name, domain, asn, org_kind FROM \"{IP_ORG_TABLE}\" "
    "WHERE prefix >>= CAST(:ip AS inet) AND org_kind = 'org' "
    "ORDER BY masklen(prefix) DESC LIMIT 1"
)


async def lookup_ip_org(db: AsyncSession, ip: str | None) -> IpOrgMatch | None:
    """Most specific organization prefix containing ``ip``, else ``None``.

    Returns ``None`` immediately when ``ip_org_lookup_enabled`` is off, so the
    flag makes this inert rather than merely unused — no query is issued at all,
    which also means the table may legitimately not exist yet.
    """
    if not settings.ip_org_lookup_enabled or not ip:
        return None
    try:
        row = (await db.execute(_LOOKUP_SQL, {"ip": ip})).first()
    except Exception as exc:
        # Includes the "table does not exist" case (flag on before the migration
        # is applied) and any malformed-address cast error.
        try:
            await db.rollback()
        except Exception:
            pass
        logger.debug("ip_org_lookup_failed", error=str(exc))
        return None
    if row is None:
        return None
    return IpOrgMatch(
        org_name=row[0],
        domain=row[1],
        asn=row[2],
        org_kind=row[3],
    )
