"""Second evidence source: RIR delegated-extended allocations.

The five Regional Internet Registries each publish a "delegated-extended" file
recording every address range they have handed out. Unlike CAIDA's BGP-derived
data — which says who is ANNOUNCING a prefix, frequently a transit provider on a
customer's behalf — this says who the range was ALLOCATED to. Comparing the two
is the whole point of the evidence graph: a prefix announced at exactly its
allocation boundary is very likely the holder announcing its own space, while a
/24 carved out of a /16 allocation is likely a customer of whoever announces it.

Format is pipe-delimited::

    registry|cc|type|start|value|date|status|opaque-id[|extensions]

Two traps in that line, and they are the entire parsing risk:

1. **For ``type=ipv4``, ``value`` is a COUNT OF ADDRESSES, not a prefix length,
   and it is not necessarily a power of two.** ``62.122.208.0|1280`` is a real
   RIPE record. A range like that is not one CIDR block — it decomposes into
   several, which is what ``ipaddress.summarize_address_range`` is for. Reading
   ``value`` as a masklen would silently produce wildly wrong prefixes.

2. **Header, summary and non-delegated lines must be skipped.** The first line
   is a version record; ``registry|*|ipv4|*|N|summary`` lines carry totals; and
   ``reserved`` / ``available`` ranges are not delegated to anybody, so treating
   them as evidence would attribute unallocated space to a registry handle.

**Names are deliberately absent (D8).** The ``opaque-id`` is a handle, not an
organization name — resolving it needs RDAP, one rate-limited request per handle
across ~100k handles. So these rows carry registry/cc/handle and no name, and
fusion uses them ONLY for the allocation-specificity signal, which needs no name.
They are written with ``org_kind='registry'``, which the v1 and v2 lookups both
filter out, so they can never themselves become a "company" for a visitor.

Shape, fail-open contract and status dict all mirror ``ip_org_ingest``. The
advisory lock is IMPORTED from the model module and never redefined here: both
this job and the CAIDA job end in DROP + RENAME of the same table, and two
different keys would let them interleave and destroy each other's rows.

IPv4 only. ``ipv6`` and ``asn`` lines are skipped by an explicit guard.
"""

import ipaddress
from datetime import date, datetime, timezone
from typing import TypedDict

import httpx
import structlog

from apps.api.config import settings
from apps.api.models.database import async_session
from apps.api.models.ip_org_prefix import IP_ORG_WRITE_LOCK_KEY
from apps.api.services.ip_org_ingest import (
    _load_staging_and_swap,
    _release_lock,
    _try_acquire_lock,
)

logger = structlog.get_logger()

_FETCH_TIMEOUT_SECONDS = 180.0  # the files are 10-30 MB of plain text
#: Below this many successful RIRs a swap is refused — see the module contract.
_MIN_SUCCESSFUL_RIRS = 3

#: Statuses that represent a real delegation to a holder. ``reserved`` and
#: ``available`` are registry bookkeeping, not allocations to anyone.
_DELEGATED_STATUSES = frozenset({"allocated", "assigned"})


class RirAllocation(TypedDict):
    """One delegated IPv4 CIDR block and who it was delegated to."""

    prefix: str
    registry: str
    cc: str
    opaque_id: str
    allocated_on: date | None


def _parse_allocation_date(raw: str) -> date | None:
    """``YYYYMMDD`` → date; ``00000000``, empty and garbage → ``None``.

    This is a KEEP rule, not a skip rule, and the distinction matters. Legacy and
    ERX records publish ``00000000`` (108 such lines in the live ARIN file), and
    reserved-range records publish an empty date field. A strict parse would push
    those lines down the "malformed → skip" path, silently DROPPING legitimate
    allocations and inflating the skip ratio. ``valid_from`` is nullable
    precisely so an unknown date can be recorded as unknown.
    """
    raw = (raw or "").strip()
    if not raw or raw == "00000000":
        return None
    try:
        return datetime.strptime(raw, "%Y%m%d").date()
    except ValueError:
        return None


def parse_delegated_extended(payload: bytes) -> list[RirAllocation]:
    """Parse a delegated-extended body into IPv4 allocations. Pure and total.

    Never raises: a malformed line is skipped, because one bad record must not
    abort a 200k-line load. Only a bad ``type``/``start``/``value`` makes a line
    malformed — a bad DATE does not (see ``_parse_allocation_date``).
    """
    out: list[RirAllocation] = []
    for raw in payload.decode("utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) < 7:
            continue  # version record and any truncated line
        registry, cc, rtype, start, value, datestr, status = parts[:7]
        if rtype.strip().lower() != "ipv4":
            continue  # ipv6 / asn records, and the summary lines' own type rows
        if status.strip().lower() not in _DELEGATED_STATUSES:
            continue  # summary, reserved, available
        try:
            first = ipaddress.IPv4Address(start.strip())
            count = int(value.strip())
        except (ValueError, ipaddress.AddressValueError):
            continue
        if count <= 0:
            continue
        try:
            last = ipaddress.IPv4Address(int(first) + count - 1)
            networks = ipaddress.summarize_address_range(first, last)
        except (ValueError, ipaddress.AddressValueError):
            continue

        opaque_id = (parts[7].strip() if len(parts) > 7 else "") or ""
        allocated_on = _parse_allocation_date(datestr)
        for net in networks:
            out.append(
                RirAllocation(
                    prefix=str(net),
                    registry=registry.strip().lower(),
                    cc=cc.strip().upper(),
                    opaque_id=opaque_id,
                    allocated_on=allocated_on,
                )
            )
    return out


def _allocation_to_row(alloc: RirAllocation) -> dict:
    """Map one allocation onto an ``ip_org_prefixes`` evidence row.

    ``asn`` is ``None`` and never ``0`` (D13): this evidence class carries no
    autonomous-system number at all, and a sentinel would be a fabricated fact
    that every future reader has to know to special-case.
    """
    handle = alloc["opaque_id"]
    return {
        "prefix": alloc["prefix"],
        "asn": None,
        "org_name": handle.lower()[:200],
        "org_name_raw": f"{alloc['registry']}:{alloc['cc']}:{handle}"[:200],
        # Filtered out by both lookups — registration evidence is never itself
        # the answer to "who is this visitor's employer".
        "org_kind": "registry",
        "relationship_type": "registered_holder",
        "valid_from": alloc["allocated_on"],
        "valid_to": None,
    }


async def _get(client: httpx.AsyncClient, url: str) -> bytes:
    """GET ``url``, raising on any non-2xx. Callers convert this to fail-open."""
    resp = await client.get(url, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def _rir_urls() -> list[str]:
    return [u.strip() for u in settings.ip_org_rir_delegated_urls.split(",") if u.strip()]


async def refresh_rir_allocations(dry_run: bool = True) -> dict:
    """Fetch all five RIR delegated-extended files and load them as evidence.

    Partial success is allowed — one RIR being down should not cost the other
    four — but the swap is REFUSED below ``_MIN_SUCCESSFUL_RIRS`` successes or on
    zero rows. Same contract as the CAIDA job: a refresh that cannot improve the
    data must never destroy it.

    Returns ``dry_run`` / ``ok`` / ``locked`` / ``error`` status dicts; never
    raises into the caller.
    """
    started = datetime.now(timezone.utc)
    urls = _rir_urls()
    allocations: list[RirAllocation] = []
    succeeded: list[str] = []
    failed: list[str] = []

    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS) as client:
        for url in urls:
            try:
                payload = await _get(client, url)
                parsed = parse_delegated_extended(payload)
            except Exception as exc:
                logger.warning("rir_ingest_source_failed", url=url, error=str(exc))
                failed.append(url)
                continue
            succeeded.append(url)
            allocations.extend(parsed)

    rows = [_allocation_to_row(a) for a in allocations]
    summary = {
        "sources_ok": len(succeeded),
        "sources_failed": len(failed),
        "allocations": len(allocations),
        "rows": len(rows),
    }
    logger.info("rir_ingest_parsed", **summary)

    if dry_run:
        return {"status": "dry_run", **summary}

    if len(succeeded) < _MIN_SUCCESSFUL_RIRS:
        return {
            "status": "error",
            "error": f"only {len(succeeded)} of {len(urls)} RIR sources succeeded",
            **summary,
        }
    if not rows:
        return {"status": "error", "error": "parsed zero allocations", **summary}

    async with async_session() as lock_db:
        acquired = await _try_acquire_lock(lock_db)
        if acquired is False:
            logger.info("rir_ingest_lock_busy", key=IP_ORG_WRITE_LOCK_KEY)
            return {"status": "locked"}
        try:
            async with async_session() as db:
                try:
                    await _load_staging_and_swap(
                        db, rows, "rir_delegated", None, carry_over=True
                    )
                except Exception as exc:
                    try:
                        await db.rollback()
                    except Exception:
                        pass
                    logger.warning("rir_ingest_load_failed", error=str(exc))
                    return {"status": "error", "error": str(exc), **summary}
        finally:
            if acquired:
                await _release_lock(lock_db)

    duration = (datetime.now(timezone.utc) - started).total_seconds()
    logger.info("rir_ingest_complete", rows=len(rows), duration_s=duration)
    return {"status": "ok", "duration_s": duration, **summary}
