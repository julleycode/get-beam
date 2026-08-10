"""Third evidence source: validated RPKI ROAs from a public validator dump.

Cloudflare publishes the output of a running RPKI validator as one JSON
document::

    {"roas": [{"asn": 13335, "prefix": "1.0.0.0/24", "maxLength": 24, …}, …]}

RIPE's validated-ROA JSON is the documented fallback if that endpoint is
unavailable; both carry the same ``roas`` array shape.

**The size guard is not optional.** The live file measured 98 MB with 987,997
ROAs — materially bigger than the gzipped CAIDA files this pipeline was built
for — and ``json.loads`` roughly doubles peak RSS over the raw bytes. Reading the
whole body and checking its length afterwards would defeat the purpose entirely:
by then the memory is already spent. So the body is STREAMED and the fetch is
aborted the moment the accumulated byte count passes the cap. Exceeding it is a
normal fail-open outcome — a status dict, never an exception — and the
previously loaded ROAs keep serving.

``asn`` spelling: the live dump uses a plain integer, but ``"AS13335"`` appears
in some validator outputs and in the format's documentation, so the parser
accepts both. IPv6 entries are skipped by an explicit guard, matching the rest
of the pipeline.

This writes ``rpki_roas`` and NEVER ``ip_org_prefixes``, so it holds its own
advisory lock (D10/D5): serializing it against the two prefix ingests would cost
throughput for no safety gain.
"""

import json
import uuid
from datetime import datetime, timezone

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.database import async_session
from apps.api.models.rpki_roa import (
    RPKI_ROA_STAGING_TABLE,
    RPKI_ROA_TABLE,
    RPKI_WRITE_LOCK_KEY,
)
from apps.api.services.rpki_validate import Roa

logger = structlog.get_logger()

_FETCH_TIMEOUT_SECONDS = 300.0  # ~100 MB of JSON over a slow link
_INSERT_CHUNK = 5_000


class PayloadTooLarge(Exception):
    """Raised internally when the streamed body passes the configured cap."""


def parse_rpki_json(payload: bytes) -> list[Roa]:
    """Parse a validator dump into ROAs. Pure and total — never raises.

    Tolerates both ``"AS13335"`` and ``13335`` ASN spellings. Skips IPv6 and any
    entry missing a field it needs, because one malformed record must not cost
    the other million.
    """
    try:
        doc = json.loads(payload)
    except (ValueError, TypeError):
        return []
    if not isinstance(doc, dict):
        return []
    entries = doc.get("roas")
    if not isinstance(entries, list):
        return []

    out: list[Roa] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        prefix = entry.get("prefix")
        if not isinstance(prefix, str) or ":" in prefix:
            continue  # IPv6, or not a prefix at all
        raw_asn = entry.get("asn")
        if isinstance(raw_asn, str):
            raw_asn = raw_asn.strip().upper().removeprefix("AS")
        try:
            asn = int(raw_asn)
            max_length = int(entry["maxLength"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append(Roa(prefix=prefix, asn=asn, max_length=max_length))
    return out


async def _fetch_capped(client: httpx.AsyncClient, url: str, max_bytes: int) -> bytes:
    """Stream ``url``, aborting as soon as the body passes ``max_bytes``.

    The abort is the whole point: the check happens WHILE reading, so an oversize
    or hostile response costs at most ``max_bytes`` of memory rather than however
    much the server felt like sending.
    """
    chunks: list[bytes] = []
    total = 0
    async with client.stream("GET", url, follow_redirects=True) as resp:
        resp.raise_for_status()
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise PayloadTooLarge(
                    f"rpki payload exceeded max bytes ({max_bytes})"
                )
            chunks.append(chunk)
    return b"".join(chunks)


async def _load_roas_and_swap(db: AsyncSession, roas: list[Roa]) -> None:
    """Bulk-load ROAs into a staging twin and swap it in atomically.

    One source owns this whole table, so unlike the ip_org swap there is no
    carry-over to do — the simple whole-table form is correct here.
    """
    await db.execute(text(f'DROP TABLE IF EXISTS "{RPKI_ROA_STAGING_TABLE}"'))
    await db.execute(
        text(
            f'CREATE TABLE "{RPKI_ROA_STAGING_TABLE}" '
            f'(LIKE "{RPKI_ROA_TABLE}" INCLUDING ALL)'
        )
    )
    insert_sql = text(
        f'INSERT INTO "{RPKI_ROA_STAGING_TABLE}" (id, prefix, asn, max_length) '
        "VALUES (:id, CAST(:prefix AS cidr), :asn, :max_length)"
    )
    for start in range(0, len(roas), _INSERT_CHUNK):
        chunk = [
            {**roa, "id": uuid.uuid4()} for roa in roas[start : start + _INSERT_CHUNK]
        ]
        await db.execute(insert_sql, chunk)

    await db.execute(text(f'DROP TABLE "{RPKI_ROA_TABLE}"'))
    await db.execute(
        text(f'ALTER TABLE "{RPKI_ROA_STAGING_TABLE}" RENAME TO "{RPKI_ROA_TABLE}"')
    )
    # Same reason as the ip_org swap: ``LIKE … INCLUDING ALL`` names the copied
    # indexes after the STAGING table, which is harmless now and fatal to the
    # NEXT swap when those names collide.
    rows = (
        await db.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = :t AND schemaname = current_schema()"
            ),
            {"t": RPKI_ROA_TABLE},
        )
    ).fetchall()
    for indexname, indexdef in rows:
        target = (
            "idx_rpki_roas_prefix_gist"
            if "gist" in (indexdef or "").lower()
            else f"{RPKI_ROA_TABLE}_pkey"
        )
        if indexname != target:
            await db.execute(text(f'ALTER INDEX "{indexname}" RENAME TO "{target}"'))
    await db.commit()


async def _try_acquire_lock(db: AsyncSession) -> bool | None:
    try:
        result = await db.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"),
            {"key": RPKI_WRITE_LOCK_KEY},
        )
        return bool(result.scalar())
    except Exception as exc:
        logger.warning("rpki_ingest_lock_unavailable", error=str(exc))
        return None


async def _release_lock(db: AsyncSession) -> None:
    try:
        await db.execute(
            text("SELECT pg_advisory_unlock(hashtext(:key))"),
            {"key": RPKI_WRITE_LOCK_KEY},
        )
    except Exception:
        pass


async def refresh_rpki_roas(dry_run: bool = True) -> dict:
    """Fetch and load the validated ROA set. Fail-open; never raises."""
    started = datetime.now(timezone.utc)
    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS) as client:
            payload = await _fetch_capped(
                client, settings.ip_org_rpki_json_url, settings.ip_org_rpki_max_bytes
            )
    except PayloadTooLarge as exc:
        logger.warning("rpki_ingest_payload_too_large", error=str(exc))
        return {"status": "error", "error": "rpki payload exceeded max bytes"}
    except Exception as exc:
        logger.warning("rpki_ingest_fetch_failed", error=str(exc))
        return {"status": "error", "error": str(exc)}

    roas = parse_rpki_json(payload)
    summary = {"roas": len(roas), "bytes": len(payload)}
    logger.info("rpki_ingest_parsed", **summary)

    if dry_run:
        return {"status": "dry_run", **summary}
    if not roas:
        return {"status": "error", "error": "parsed zero ROAs", **summary}

    async with async_session() as lock_db:
        acquired = await _try_acquire_lock(lock_db)
        if acquired is False:
            logger.info("rpki_ingest_lock_busy")
            return {"status": "locked"}
        try:
            async with async_session() as db:
                try:
                    await _load_roas_and_swap(db, roas)
                except Exception as exc:
                    try:
                        await db.rollback()
                    except Exception:
                        pass
                    logger.warning("rpki_ingest_load_failed", error=str(exc))
                    return {"status": "error", "error": str(exc), **summary}
        finally:
            if acquired:
                await _release_lock(lock_db)

    duration = (datetime.now(timezone.utc) - started).total_seconds()
    logger.info("rpki_ingest_complete", roas=len(roas), duration_s=duration)
    return {"status": "ok", "duration_s": duration, **summary}
