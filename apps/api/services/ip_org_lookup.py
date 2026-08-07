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
from apps.api.models.rpki_roa import RPKI_ROA_TABLE
from apps.api.services.ip_org_fusion import (
    OrgHypothesis,
    fuse_org_hypothesis,
    get_cached_rir_corpus_present,
    set_cached_rir_corpus_present,
)
from apps.api.services.rpki_validate import Roa, validate_origin

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


# ── v2: multi-source evidence lookup ─────────────────────────────────────────
#
# v1 above is preserved VERBATIM as the flag-off path. Everything below runs only
# when ``ip_org_fusion_enabled`` is on.

_V2_ROUTE_ORIGIN_SQL = text(
    f"SELECT org_name, org_name_raw, asn, org_kind, prefix::text "
    f'FROM "{IP_ORG_TABLE}" '
    "WHERE prefix >>= CAST(:ip AS inet) AND org_kind = 'org' "
    "AND relationship_type = 'route_origin' "
    "ORDER BY masklen(prefix) DESC LIMIT 1"
)

_V2_REGISTERED_HOLDER_SQL = text(
    f"SELECT prefix::text, org_name, org_name_raw "
    f'FROM "{IP_ORG_TABLE}" '
    "WHERE prefix >>= CAST(:ip AS inet) "
    "AND relationship_type = 'registered_holder' "
    "ORDER BY masklen(prefix) DESC LIMIT 1"
)

_V2_RPKI_SQL = text(
    f'SELECT prefix::text, asn, max_length FROM "{RPKI_ROA_TABLE}" '
    "WHERE prefix >>= CAST(:ip AS inet)"
)

_CORPUS_EXISTS_SQL = text(
    f'SELECT EXISTS(SELECT 1 FROM "{IP_ORG_TABLE}" '
    "WHERE relationship_type = 'registered_holder')"
)


async def _rir_corpus_present(db: AsyncSession) -> bool:
    """Does ANY registered_holder row exist? Memoized with a 300s TTL.

    Asking per lookup would put a fourth query on the live resolver path for an
    answer that only changes when an ingest swap runs.
    """
    cached = get_cached_rir_corpus_present()
    if cached is not None:
        return cached
    present = bool((await db.execute(_CORPUS_EXISTS_SQL)).scalar())
    set_cached_rir_corpus_present(present)
    return present


async def lookup_ip_org_v2(db: AsyncSession, ip: str | None) -> OrgHypothesis | None:
    """Fused, multi-source organization hypothesis for ``ip``, else ``None``.

    Three queries on a warm corpus-probe cache (route_origin, covering
    registered_holder, covering ROAs), four on a cold one — where v1 issued one.
    All three are GiST/btree index lookups on tables indexed for exactly this
    access pattern, and the budget for the full round trip is **under 15ms warm**.

    **The ``org_kind = 'org'`` filter on the route_origin query is
    non-negotiable.** A datacenter, CDN, eyeball or registry prefix yields
    ``None`` here — no hypothesis, no company_graph write, at any confidence.
    Eyeball prefixes alone are ~27% of the loaded corpus, and resolving a
    consumer-ISP prefix to "Comcast" as a visitor's employer is the exact
    fabrication class this filter exists to prevent. A gate asserts it precisely
    so a future refactor cannot quietly relax it.

    Fail-open like v1: any error rolls back and returns ``None``.
    """
    if not settings.ip_org_lookup_enabled or not ip:
        return None
    try:
        route = (await db.execute(_V2_ROUTE_ORIGIN_SQL, {"ip": ip})).first()
        if route is None:
            return None
        route_row = {
            "org_name": route[0],
            "org_name_raw": route[1],
            "asn": route[2],
            "org_kind": route[3],
            "prefix": route[4],
        }

        holders = (await db.execute(_V2_REGISTERED_HOLDER_SQL, {"ip": ip})).fetchall()
        rir_rows = [
            {"prefix": h[0], "org_name": h[1], "org_name_raw": h[2]} for h in holders
        ]

        roa_rows = (await db.execute(_V2_RPKI_SQL, {"ip": ip})).fetchall()
        roas = [
            Roa(prefix=r[0], asn=r[1], max_length=r[2]) for r in roa_rows
        ]
        corpus_present = await _rir_corpus_present(db)
    except Exception as exc:
        try:
            await db.rollback()
        except Exception:
            pass
        logger.debug("ip_org_lookup_v2_failed", error=str(exc))
        return None

    rpki_state = validate_origin(route_row["prefix"], route_row["asn"], roas)
    return fuse_org_hypothesis(route_row, rir_rows, rpki_state, corpus_present)
