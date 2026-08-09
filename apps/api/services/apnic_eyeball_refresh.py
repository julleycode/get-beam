"""Refresh the APNIC per-AS user-population dataset used as an eyeball signal (WS-E).

APNIC publishes an estimate of the end-user population behind each ASN. A large
population is a strong, numeric signal that an ASN is a consumer/access network
("eyeball") rather than an employer — exactly the class ``classify_ip_org_kind``
must keep OUT of the ``org`` bucket the lookup serves. This is a data-driven
PRE-check in front of the existing org-name token heuristic, never a replacement
for it: the token list still covers CAIDA ASNs absent from the APNIC dataset.

Modeled on ``agent_ip_range_refresh``: a vendored file ships in the repo and a
runtime override is written by the (flag-guarded, default-OFF) refresh job.
``load_eyeball_asns`` prefers the runtime file and falls back to the vendored one.

**Fail-open at every level** — a failed fetch, a bad status, an oversize body,
unparseable JSON or an unrecognized shape leaves the existing file untouched. A
refresh that cannot improve the data must never destroy it.

**Streamed size cap (CONCERN-9):** the body is read in chunks and aborted once
``ip_org_apnic_max_bytes`` is exceeded, mirroring the ``rpki.json`` precedent, so
a hostile or corrupt response cannot exhaust memory.

Observed live shape (G18, 2026-08-08, ``stats.labs.apnic.net/cgi-bin/aspop?f=j``):
a top-level object ``{"copyright", "description", "Date", "Window", "Data": [...]}``
where each ``Data`` record carries ``"AS"`` (int ASN) and ``"Users"`` (int
estimated population), among ``rank``/``Description``/``CC``/``Percent …``/``Samples``.
The parser also tolerates a bare list-of-objects shape and skips junk records.
"""

import json
from functools import lru_cache
from pathlib import Path

import httpx
import structlog

from apps.api.config import settings

logger = structlog.get_logger()

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "apnic_eyeball"
_RUNTIME_DIR = _DATA_DIR / "runtime"
_VENDORED_FILE = _DATA_DIR / "eyeball_asns.json"
_RUNTIME_FILE = _RUNTIME_DIR / "eyeball_asns.json"

_FETCH_TIMEOUT_SECONDS = 60.0


def parse_aspop(payload: object) -> dict[int, int]:
    """Pull ``{asn: estimated_users}`` out of an aspop document.

    Accepts BOTH the observed keyed-object shape (``{"Data": [ {...} ]}``) and a
    bare list-of-objects. Each record must carry ``"AS"`` and ``"Users"`` as
    ints (string digits are coerced). Unparseable records are skipped, never
    fatal — the same discipline that would have caught the as2org camelCase
    defect. An unknown top-level shape yields an empty map (learned nothing).
    """
    if isinstance(payload, dict):
        records = payload.get("Data")
    elif isinstance(payload, list):
        records = payload
    else:
        records = None
    if not isinstance(records, list):
        return {}

    out: dict[int, int] = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        raw_asn = rec.get("AS")
        raw_users = rec.get("Users")
        try:
            asn = int(raw_asn)
            users = int(raw_users)
        except (TypeError, ValueError):
            continue
        if asn <= 0 or users < 0:
            continue
        # Keep the largest estimate if an ASN appears more than once.
        if users > out.get(asn, -1):
            out[asn] = users
    return out


async def _fetch_capped(client: httpx.AsyncClient, url: str, max_bytes: int) -> bytes:
    """Stream ``url`` into memory, aborting once ``max_bytes`` is exceeded."""
    chunks: list[bytes] = []
    total = 0
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(
                    f"aspop response exceeded {max_bytes} bytes"
                )
            chunks.append(chunk)
    return b"".join(chunks)


def _write_dataset(asn_users: dict[int, int]) -> None:
    _RUNTIME_FILE.parent.mkdir(parents=True, exist_ok=True)
    _RUNTIME_FILE.write_text(
        json.dumps({"asns": {str(k): v for k, v in asn_users.items()}}, indent=0)
        + "\n",
        encoding="utf-8",
    )


async def refresh_apnic_eyeball_asns() -> dict[str, int]:
    """Re-fetch the aspop dataset and write the runtime override.

    Returns ``{"asns": N}`` on success (N = ASNs stored, unfiltered — the
    user-count threshold is applied at LOAD time so it can change without a
    re-fetch). Mock mode short-circuits with a deterministic fake and makes no
    network call. Any failure logs and keeps the existing file (fail-open).
    """
    if settings.mock_external_apis:
        logger.info("apnic_eyeball_refresh_skipped_mock_mode")
        return {"asns": 0}

    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS) as client:
            blob = await _fetch_capped(
                client, settings.ip_org_apnic_url, settings.ip_org_apnic_max_bytes
            )
            asn_users = parse_aspop(json.loads(blob.decode("utf-8", errors="replace")))
    except Exception as exc:
        logger.warning("apnic_eyeball_fetch_failed", error=type(exc).__name__)
        return {"asns": 0}

    if not asn_users:
        logger.warning("apnic_eyeball_empty_payload")
        return {"asns": 0}

    try:
        _write_dataset(asn_users)
    except Exception as exc:
        logger.warning("apnic_eyeball_write_failed", error=type(exc).__name__)
        return {"asns": 0}

    load_eyeball_asns.cache_clear()
    logger.info("apnic_eyeball_refresh_done", asns=len(asn_users))
    return {"asns": len(asn_users)}


@lru_cache(maxsize=1)
def load_eyeball_asns() -> frozenset[int]:
    """ASNs whose estimated user population is >= ``ip_org_eyeball_min_users``.

    Reads the runtime file if present, else the vendored one. Fail-open: a
    missing or corrupt file yields an empty set (no eyeball pre-check, token path
    still runs). Cached — every test that varies the underlying file MUST call
    ``load_eyeball_asns.cache_clear()`` first (E6a).
    """
    path = _RUNTIME_FILE if _RUNTIME_FILE.exists() else _VENDORED_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    asns = data.get("asns") if isinstance(data, dict) else None
    if not isinstance(asns, dict):
        return frozenset()
    threshold = settings.ip_org_eyeball_min_users
    out: set[int] = set()
    for raw_asn, raw_users in asns.items():
        try:
            asn = int(raw_asn)
            users = int(raw_users)
        except (TypeError, ValueError):
            continue
        if users >= threshold:
            out.add(asn)
    return frozenset(out)
