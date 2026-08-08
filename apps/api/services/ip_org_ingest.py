"""Build the self-hosted IP prefix → organization table from public snapshots.

Data: "Routeviews Prefix to AS mappings Dataset" and "The CAIDA AS Organizations
Dataset" (DOI 10.21986/CAIDA.DATA.AS-TO-ORG-MAPPING), https://www.caida.org/ —
used under CAIDA public AUA (attribution required, license non-transferable).

Pipeline, once per refresh:

    pfx2as (gzip, TSV)     prefix → ASN
    as2org (gzip, JSONL)   ASN → org_id → org name
    join on ASN            → prefix → org
    normalize + classify   → org_name (join key), org_kind
    staging load + swap    → ip_org_prefixes

Shape copied from ``proxy_ptr_sweep``: trigger-agnostic core, its own session, a
Postgres advisory lock so replicas do not duplicate the work, ``dry_run``
support, and a status dict return (never an exception into the caller).

**Fail-open is the whole safety story.** A refresh that cannot improve the data
must never destroy it: any fetch error, bad status, truncated gzip or unparseable
line aborts BEFORE the swap, so the previously loaded table keeps serving. The
swap itself is one transaction, so a lookup never observes a half-loaded table.

IPv4 only. The IPv6 pfx2as variant is a follow-up — an IPv6 prefix parsed into
the same ``cidr`` column would work, but the dataset is published separately and
carries different coverage caveats, so it is out of scope here.
"""

import gzip
import io
import json
import re
import uuid
from datetime import date, datetime, timezone
from urllib.parse import urljoin

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.database import async_session
from apps.api.models.ip_org_prefix import (
    IP_ORG_STAGING_TABLE,
    IP_ORG_TABLE,
    IP_ORG_WRITE_LOCK_KEY,
)
from apps.api.services.apnic_eyeball_refresh import load_eyeball_asns
from apps.api.services.company_resolver import classify_org_kind

logger = structlog.get_logger()

_FETCH_TIMEOUT_SECONDS = 120.0  # multi-MB gzip files over a slow link
_INSERT_CHUNK = 5_000

_PFX2AS_FILE_RE = re.compile(r"\S+?routeviews-[\w.\-]*?\.pfx2as\.gz")
_AS2ORG_FILE_RE = re.compile(r"(\d{8})\.as-org2info\.jsonl\.gz")
_DATE_IN_NAME_RE = re.compile(r"(\d{8})")

# Legal-form suffixes stripped when normalizing an organization name. Order
# matters only in that longer forms are listed before the token they contain.
_LEGAL_SUFFIXES: tuple[str, ...] = (
    "incorporated", "corporation", "company", "limited",
    "co ltd", "pty ltd", "pvt ltd", "sdn bhd",
    "inc", "corp", "llc", "llp", "lllp", "ltd", "ltda", "plc",
    "gmbh", "mbh", "ag", "kg", "kgaa", "ug",
    "sarl", "sas", "sa", "sl", "srl", "spa", "spr", "nv", "bv", "cv",
    "ab", "as", "oy", "oyj", "aps", "kft", "zrt", "doo", "dooel",
    "pty", "pte", "kk", "gk", "yk",
)
_LEGAL_SUFFIX_SET = frozenset(_LEGAL_SUFFIXES)
# Punctuation that carries no identity, collapsed to a space before tokenizing.
_PUNCT_RE = re.compile(r"[^a-z0-9]+")

# Organization-name tokens that mark a consumer/access network (an "eyeball"
# ISP) rather than a company whose employees we would want to identify. These
# are the rows the lookup filters OUT: a hit on "Comcast Cable" tells us nothing
# about who the visitor works for, and treating it as a company is exactly the
# fabrication bug the CDN bucket exists to prevent.
_EYEBALL_ORG_TOKENS: tuple[str, ...] = (
    # WS-E / follow-ups item 7: bare "telekom" slipped through as org — no
    # existing token substring-matches it ("telkom"/"telecom"/"deutsche telekom"
    # all differ). Added. Everything else in item 7's ambit is already present
    # (telecom, telkom, telefon, mobile, wireless, cellular, deutsche telekom).
    "telekom",
    "telecom", "telecommunication", "telefon", "telkom", "telenor", "telia",
    "broadband", "cable", "cablevision", "wireless", "mobile", "cellular",
    "internet service", "isp", "communications", "comunicaciones",
    "dsl", "fiber", "fibre", "ftth", "network solutions provider",
    "chinanet", "unicom", "vodafone", "orange", "comcast", "charter",
    "verizon", "at&t", "t-mobile", "sprint", "spectrum", "cox communications",
    "deutsche telekom", "bt group", "sky broadband", "virgin media",
)


def normalize_org_name(raw: str | None) -> str:
    """Normalize an organization name into a stable join/dedup key.

    Lowercase, strip punctuation, drop trailing legal-form suffixes, collapse
    whitespace. Pure and total — never raises, returns ``""`` for empty input.

    ``MICROSOFT-CORP``, ``Microsoft Corporation`` and ``Microsoft, Inc.`` all
    normalize to ``microsoft``. Suffix stripping is TRAILING-ONLY and iterative
    (``Foo Corp Ltd`` → ``foo``); an interior match is left alone so
    ``Ltd Commodities`` does not become ``commodities``.
    """
    if not raw:
        return ""
    tokens = [t for t in _PUNCT_RE.sub(" ", raw.lower()).split() if t]
    while tokens and tokens[-1] in _LEGAL_SUFFIX_SET:
        tokens.pop()
    return " ".join(tokens)


def classify_ip_org_kind(asn: int, org_raw: str | None) -> str:
    """Bucket a prefix's owner: ``'org' | 'eyeball' | 'datacenter' | 'cdn'``.

    Datacenter and CDN come from the resolver's existing ``classify_org_kind``
    (same ASN sets and org tokens, so both paths stay in lockstep — it is fed the
    ``"AS<num> <Org>"`` shape it parses). Everything ``classify_org_kind`` calls
    ``eyeball`` is then split again here: a consumer ISP stays ``eyeball``, and
    anything left is a real organization (``org``) — the only bucket the lookup
    serves.
    """
    kind = classify_org_kind(f"AS{asn} {org_raw or ''}".strip())
    if kind in ("datacenter", "cdn"):
        return kind
    # APNIC numeric pre-check (WS-E / Q8): a large estimated user population is a
    # data-driven eyeball signal. Direction guard — this can only produce
    # 'eyeball', never move a prefix TO 'org' (infra 'datacenter'/'cdn' already
    # returned above). Absent from the set → fall through to the token path.
    if asn and asn in load_eyeball_asns():
        return "eyeball"
    low = (org_raw or "").lower()
    if any(tok in low for tok in _EYEBALL_ORG_TOKENS):
        return "eyeball"
    return "org"


# Family-fold precedence (WS-C / Q6): any non-``org`` member makes the family
# non-``org``; when two different non-``org`` kinds appear the leftmost here wins.
# CDN has the strongest keep-but-never-resolve semantics, so it leads.
_FAMILY_KIND_PRECEDENCE: tuple[str, ...] = ("cdn", "datacenter", "eyeball", "org")


def build_org_family_kinds(
    asn_orgs: dict[int, tuple[str, str]],
) -> dict[str, str]:
    """Fold each as2org organization family to a single kind (WS-C / Q6).

    For every ``organizationId`` group the family kind is the highest-precedence
    per-ASN kind among its members (``cdn > datacenter > eyeball > org``). Used to
    let a sibling ASN's non-``org`` classification propagate to an ``org`` sibling
    — one-directional only; the caller applies the ``own == 'org'`` guard so a
    non-``org`` classification is NEVER overwritten (no lateral moves, R9; never
    promoted TO ``org``, Q6).
    """
    family: dict[str, str] = {}
    for asn, (org_raw, org_id) in asn_orgs.items():
        own = classify_ip_org_kind(asn, org_raw)
        current = family.get(org_id)
        if current is None:
            family[org_id] = own
            continue
        # Keep whichever has the stronger (lower-index) precedence.
        if _FAMILY_KIND_PRECEDENCE.index(own) < _FAMILY_KIND_PRECEDENCE.index(
            current
        ):
            family[org_id] = own
    return family


def resolve_row_kind(own_kind: str, family_kind: str | None) -> str:
    """Apply org-family inheritance to a single row's kind (WS-C / Q6 / R9).

    Inherits the family kind ONLY when the row's OWN kind is ``org`` and the
    family is non-``org`` — one-directional. A row already classified non-``org``
    is never changed (no lateral move, R9), and nothing is ever promoted TO
    ``org`` (Q6).
    """
    if own_kind == "org" and family_kind is not None and family_kind != "org":
        return family_kind
    return own_kind


def parse_pfx2as(payload: bytes) -> list[tuple[str, int]]:
    """Parse a decompressed pfx2as body into ``[(cidr, asn), …]``.

    Line format is ``prefix<TAB>prefix_len<TAB>asn``. The ASN field is not always
    a plain integer: multi-origin prefixes appear as ``1234,5678`` and AS-sets as
    ``1234_5678``. We take the FIRST origin — with no way to pick between
    co-announcers, the first is as good as any, and the alternative (dropping the
    row) loses real coverage. Anything still unparseable is skipped silently;
    a malformed line must never abort a million-line load.
    """
    out: list[tuple[str, int]] = []
    for raw in payload.decode("utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            parts = line.split()
        if len(parts) < 3:
            continue
        network, masklen, asn_field = parts[0], parts[1], parts[2]
        first = re.split(r"[,_]", asn_field.strip())[0]
        try:
            asn = int(first)
            prefix_len = int(masklen)
        except ValueError:
            continue
        if asn <= 0 or not 0 <= prefix_len <= 32 or ":" in network:
            continue
        out.append((f"{network}/{prefix_len}", asn))
    return out


def parse_as2org(payload: bytes) -> dict[int, tuple[str, str]]:
    """Parse a decompressed as2org JSONL body into ``{asn: (org_name_raw, org_id)}``.

    WS-C: the opaque CAIDA ``organizationId`` (e.g. ``LPL-141-ARIN``) used to be
    discarded in the final comprehension; it is now returned alongside the name so
    the caller can group ASNs by family and persist the handle.

    The file interleaves TWO record shapes, discriminated by an explicit
    ``type`` field:

        {"type":"ASN","asn":"1","name":"LVLT-1","organizationId":"LPL-141-ARIN",…}
        {"type":"Organization","name":"1-800 Contacts, Inc.","organizationId":"1800CO-2-ARIN",…}

    Both carry a ``name``, so the ``type`` field — not the presence of a key —
    is what decides which map a record belongs in. (An earlier version keyed off
    "does this record have an ``asn``?"; that heuristic survives only as a
    fallback for a file that omits ``type``.)

    **The live key is camelCase ``organizationId``.** A snake_case-only reader
    silently produced an empty org map, which joined to zero rows and skipped all
    1.1M prefixes without raising anything — the datasets downloaded fine and the
    parse "succeeded". ``organization_id``/``org_id`` are kept as fallbacks for
    older dumps, but they are NOT the live format.

    ASN records may appear before the org they reference, so both maps are
    collected in one pass and joined afterwards. A line that does not parse is
    skipped, never fatal.
    """
    asn_to_org_id: dict[int, str] = {}
    org_id_to_name: dict[str, str] = {}
    for raw in payload.decode("utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            rec = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(rec, dict):
            continue
        # camelCase FIRST — it is the live CAIDA format; the snake_case spellings
        # are legacy fallbacks only.
        org_id = (
            rec.get("organizationId")
            or rec.get("organization_id")
            or rec.get("org_id")
        )
        rec_type = str(rec.get("type") or "").strip().lower()
        if rec_type == "asn":
            is_asn_record = True
        elif rec_type in ("organization", "org"):
            is_asn_record = False
        else:
            # No ``type`` field (older dump): fall back to the key heuristic.
            is_asn_record = rec.get("asn") is not None

        if is_asn_record:
            try:
                asn = int(rec["asn"])
            except (KeyError, TypeError, ValueError):
                continue
            if org_id:
                asn_to_org_id[asn] = str(org_id)
            continue
        name = rec.get("name")
        if org_id and name:
            org_id_to_name[str(org_id)] = str(name)

    return {
        asn: (org_id_to_name[oid], oid)
        for asn, oid in asn_to_org_id.items()
        if oid in org_id_to_name
    }


def _dataset_date_from_name(name: str) -> date | None:
    """Best-effort ``YYYYMMDD`` publication date out of a snapshot filename."""
    m = _DATE_IN_NAME_RE.search(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        return None


async def _get(client: httpx.AsyncClient, url: str) -> bytes:
    """GET ``url``, raising on any non-2xx. Callers convert this to fail-open."""
    resp = await client.get(url, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def _gunzip(blob: bytes) -> bytes:
    with gzip.GzipFile(fileobj=io.BytesIO(blob)) as fh:
        return fh.read()


async def _discover_pfx2as_url(client: httpx.AsyncClient, base: str) -> str:
    """Newest pfx2as snapshot URL, from the directory's creation log.

    ``pfx2as-creation.log`` lists newly created files (relative to the dataset
    root) in publication order, so the LAST matching entry is the newest
    snapshot. Discovering it beats pinning a filename: the daily name embeds the
    date and a fixed URL 404s within a day.
    """
    log = (await _get(client, urljoin(base, "pfx2as-creation.log"))).decode(
        "utf-8", errors="replace"
    )
    matches = _PFX2AS_FILE_RE.findall(log)
    if not matches:
        raise ValueError("no pfx2as entry found in pfx2as-creation.log")
    return urljoin(base, matches[-1].lstrip("./"))


async def _discover_as2org_url(client: httpx.AsyncClient, base: str) -> str:
    """Newest as2org snapshot URL, from the directory index listing."""
    index = (await _get(client, base)).decode("utf-8", errors="replace")
    dates = sorted(set(_AS2ORG_FILE_RE.findall(index)))
    if not dates:
        raise ValueError("no as-org2info entry found in the dataset index")
    return urljoin(base, f"{dates[-1]}.as-org2info.jsonl.gz")


async def _try_acquire_lock(db: AsyncSession) -> bool | None:
    """True = acquired, False = held elsewhere, None = unsupported."""
    try:
        result = await db.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"),
            {"key": IP_ORG_WRITE_LOCK_KEY},
        )
        return bool(result.scalar())
    except Exception as exc:
        logger.warning("ip_org_ingest_lock_unavailable", error=str(exc))
        return None


async def _release_lock(db: AsyncSession) -> None:
    try:
        await db.execute(
            text("SELECT pg_advisory_unlock(hashtext(:key))"),
            {"key": IP_ORG_WRITE_LOCK_KEY},
        )
    except Exception:
        pass


# Canonical index names, restored after the staging table is renamed into place.
# ``LIKE … INCLUDING ALL`` copies the indexes but names the copies after the
# STAGING table, so without this the swapped-in table carries
# ``ip_org_prefixes_staging_*`` index names — harmless to queries, fatal to the
# NEXT swap (the following run's ``LIKE`` would try to create those same names
# again and collide).
_INDEX_TARGETS: tuple[tuple[str, str], ...] = (
    ("gist", "idx_ip_org_prefixes_prefix_gist"),
    ("(asn", "idx_ip_org_prefixes_asn"),
    ("(org_name", "idx_ip_org_prefixes_org_name"),
    # Added with the Phase 3 evidence columns. This entry is NOT optional: the
    # fallback below renames anything unmatched to ``ip_org_prefixes_pkey``, so
    # without a marker here the relationship_type index AND the real primary-key
    # index would both be renamed to the same name — ``relation already exists``,
    # aborting the swap transaction on EVERY refresh from then on.
    ("(relationship_type", "idx_ip_org_prefixes_relationship_type"),
)


async def _rename_indexes_to_canonical(db: AsyncSession) -> None:
    rows = (
        await db.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = :t AND schemaname = current_schema()"
            ),
            {"t": IP_ORG_TABLE},
        )
    ).fetchall()
    for indexname, indexdef in rows:
        low = (indexdef or "").lower()
        target = next((t for marker, t in _INDEX_TARGETS if marker in low), None)
        if target is None:
            # The primary key index — the only remaining case.
            target = f"{IP_ORG_TABLE}_pkey"
        if indexname != target:
            await db.execute(text(f'ALTER INDEX "{indexname}" RENAME TO "{target}"'))


async def _load_staging_and_swap(
    db: AsyncSession,
    rows: list[dict],
    source: str,
    dataset_date: date | None,
    carry_over: bool = True,
) -> None:
    """Bulk-load ``rows`` into a staging twin, then swap it in atomically.

    Loading into the LIVE table would leave lookups reading a partially-replaced
    dataset for minutes. Instead the new snapshot is built beside it and swapped
    in one transaction, so a reader sees either the whole old table or the whole
    new one.

    ``carry_over`` is what makes this multi-source (D1). The swap replaces the
    WHOLE table, so with three sources refreshing on independent cadences a naive
    swap would delete the other two sources' rows. Before loading, every live row
    belonging to a DIFFERENT source is copied server-side into staging, so the
    refresh replaces only its own evidence. The DROP/RENAME sequence is
    deliberately untouched: its crash-safety was proven the hard way when the
    Postgres container was killed mid-load and zero rows leaked.

    Callers MUST hold ``IP_ORG_WRITE_LOCK_KEY``. The carry-over reads a snapshot
    of the live table; if another writer's swap commits in between, this RENAME
    silently discards their freshly loaded rows.
    """
    await db.execute(text(f'DROP TABLE IF EXISTS "{IP_ORG_STAGING_TABLE}"'))
    await db.execute(
        text(
            f'CREATE TABLE "{IP_ORG_STAGING_TABLE}" '
            f'(LIKE "{IP_ORG_TABLE}" INCLUDING ALL)'
        )
    )

    if carry_over:
        # Server-side copy: never pulls the other sources' rows through Python.
        await db.execute(
            text(
                f'INSERT INTO "{IP_ORG_STAGING_TABLE}" '
                f'SELECT * FROM "{IP_ORG_TABLE}" WHERE source <> :source'
            ),
            {"source": source},
        )

    insert_sql = text(
        f'INSERT INTO "{IP_ORG_STAGING_TABLE}" '
        "(id, prefix, asn, org_name, org_name_raw, org_kind, source, dataset_date, "
        "relationship_type, valid_from, valid_to, as2org_org_id) "
        "VALUES (:id, CAST(:prefix AS cidr), :asn, :org_name, :org_name_raw, "
        ":org_kind, :source, :dataset_date, :relationship_type, :valid_from, "
        ":valid_to, :as2org_org_id)"
    )
    for start in range(0, len(rows), _INSERT_CHUNK):
        chunk = [
            {
                "relationship_type": "route_origin",
                "valid_from": dataset_date,
                "valid_to": None,
                # Default BEFORE the **row splat (C4a/E2): this function is SHARED
                # with refresh_rir_allocations, whose rows never carry the key, so
                # without this default the RIR job breaks on a missing bind param.
                # CAIDA rows override it via **row.
                "as2org_org_id": None,
                **row,
                "id": uuid.uuid4(),
                "source": source,
                "dataset_date": dataset_date,
            }
            for row in rows[start : start + _INSERT_CHUNK]
        ]
        await db.execute(insert_sql, chunk)

    await db.execute(text(f'DROP TABLE "{IP_ORG_TABLE}"'))
    await db.execute(
        text(
            f'ALTER TABLE "{IP_ORG_STAGING_TABLE}" RENAME TO "{IP_ORG_TABLE}"'
        )
    )
    await _rename_indexes_to_canonical(db)

    # Post-condition, logged rather than asserted: a carry-over regression that
    # silently drops another source shows up here as a missing row instead of as
    # nothing at all.
    try:
        counts = (
            await db.execute(
                text(
                    f'SELECT source, count(*) FROM "{IP_ORG_TABLE}" GROUP BY source'
                )
            )
        ).fetchall()
        logger.info(
            "ip_org_swap_source_counts",
            counts={str(s): int(n) for s, n in counts},
        )
    except Exception as exc:  # observability must never fail a good swap
        logger.warning("ip_org_swap_source_counts_failed", error=str(exc))

    await db.commit()

    # Refresh planner statistics on the freshly swapped-in table, in its OWN
    # transaction AFTER the swap commit (Q1/E1). Stats written inside the swap
    # transaction are invisible to other backends; the point is that the NEXT
    # lookup from a different connection has fresh stats and does not eat the
    # ~15.7 ms cold-planner window. A failed ANALYZE must never turn a good swap
    # into an error, so it is logged and swallowed.
    try:
        await db.execute(text(f'ANALYZE "{IP_ORG_TABLE}"'))
        await db.commit()
        logger.info("ip_org_post_swap_analyze_ok")
    except Exception as exc:
        logger.warning("ip_org_post_swap_analyze_failed", error=str(exc))

    # The RIR corpus may have just appeared or vanished; drop the memoized
    # EXISTS probe so this process does not keep answering from a stale value.
    # Cross-process readers are bounded by the cache's TTL, not by this call.
    try:
        from apps.api.services.ip_org_fusion import invalidate_rir_corpus_cache

        invalidate_rir_corpus_cache()
    except Exception:  # pragma: no cover - defensive only
        pass


async def refresh_ip_org_dataset(dry_run: bool = True) -> dict:
    """Fetch, join and load the public prefix→org snapshots.

    ``dry_run=True`` (default) downloads and parses but writes nothing, so the
    parse can be validated against the live datasets without touching the table.

    Returns one of:
    - ``{"status": "dry_run", "prefixes": N, "orgs": N, "rows": N, "skipped": N, …}``
    - ``{"status": "ok", "rows": N, "duration_s": F, …}``
    - ``{"status": "locked"}``   (another replica is already refreshing)
    - ``{"status": "error", "error": "…"}``  (fail-open: old data kept)
    """
    started = datetime.now(timezone.utc)

    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS) as client:
            pfx_url = await _discover_pfx2as_url(
                client, settings.ip_org_dataset_pfx2as_url
            )
            as2org_url = await _discover_as2org_url(
                client, settings.ip_org_dataset_as2org_url
            )
            pfx_blob = _gunzip(await _get(client, pfx_url))
            as2org_blob = _gunzip(await _get(client, as2org_url))
    except Exception as exc:
        logger.warning("ip_org_ingest_fetch_failed", error=str(exc))
        return {"status": "error", "error": str(exc)}

    try:
        prefixes = parse_pfx2as(pfx_blob)
        asn_orgs = parse_as2org(as2org_blob)
    except Exception as exc:  # defensive: parsers are total, but never abort here
        logger.warning("ip_org_ingest_parse_failed", error=str(exc))
        return {"status": "error", "error": str(exc)}

    dataset_date = _dataset_date_from_name(pfx_url)

    # Org-family classification pass (WS-C / Q6): fold ASNs sharing an
    # organizationId to one kind, so a carrier's second ASN slipping through as
    # 'org' inherits its family's 'eyeball'/'datacenter'/'cdn'. In-memory over the
    # parsed maps, before row-building — no extra DB pass.
    family_kinds = build_org_family_kinds(asn_orgs)
    family_sizes: dict[str, int] = {}
    for _asn, (_raw, _oid) in asn_orgs.items():
        family_sizes[_oid] = family_sizes.get(_oid, 0) + 1

    rows: list[dict] = []
    skipped = 0
    family_reclassified = 0
    for cidr, asn in prefixes:
        org_pair = asn_orgs.get(asn)
        org_raw = org_pair[0] if org_pair else None
        org_id = org_pair[1] if org_pair else None
        normalized = normalize_org_name(org_raw)
        if not normalized:
            skipped += 1  # ASN with no org record — nothing to resolve to
            continue
        own_kind = classify_ip_org_kind(asn, org_raw)
        family_kind = family_kinds.get(org_id) if org_id else None
        org_kind = resolve_row_kind(own_kind, family_kind)
        if org_kind != own_kind:
            family_reclassified += 1
        rows.append(
            {
                "prefix": cidr,
                "asn": asn,
                "org_name": normalized[:200],
                "org_name_raw": (org_raw or "")[:200] or None,
                "org_kind": org_kind,
                "as2org_org_id": org_id,
                # pfx2as IS BGP origin data — this is the relationship it
                # asserts, not a default standing in for an unknown one.
                "relationship_type": "route_origin",
                "valid_from": dataset_date,
                "valid_to": None,
            }
        )

    # Multi-ASN family sizing (WS-C / C5): the follow-ups item-4 question.
    multi_asn_families = sum(1 for n in family_sizes.values() if n >= 2)
    total_asns = sum(family_sizes.values())
    multi_asn_family_fraction = (
        round(
            sum(n for n in family_sizes.values() if n >= 2) / total_asns, 4
        )
        if total_asns
        else 0.0
    )

    # skip_ratio = share of source-offered prefixes that produced no row (WS-A).
    # Denominator is len(prefixes) — rows the source OFFERED — not len(rows), the
    # survivors: a survivor-count denominator is undefined at total collapse, which
    # is exactly the case the guard exists for. No prefixes at all => ratio 1.0.
    skip_ratio = round(skipped / len(prefixes), 4) if prefixes else 1.0

    logger.info(
        "ip_org_ingest_parsed",
        prefixes=len(prefixes),
        orgs=len(asn_orgs),
        rows=len(rows),
        skipped=skipped,
        skip_ratio=skip_ratio,
        multi_asn_families=multi_asn_families,
        multi_asn_family_fraction=multi_asn_family_fraction,
        family_reclassified=family_reclassified,
    )

    if skip_ratio > settings.ip_org_skip_warn_ratio:
        logger.warning("ip_org_ingest_skip_ratio_high", skip_ratio=skip_ratio)

    summary = {
        "prefixes": len(prefixes),
        "orgs": len(asn_orgs),
        "rows": len(rows),
        "skipped": skipped,
        "skip_ratio": skip_ratio,
        "multi_asn_families": multi_asn_families,
        "multi_asn_family_fraction": multi_asn_family_fraction,
        "family_reclassified": family_reclassified,
        "dataset_date": dataset_date.isoformat() if dataset_date else None,
        "pfx2as_url": pfx_url,
        "as2org_url": as2org_url,
    }

    if dry_run:
        # A dry run still REPORTS the ratio (that is how an operator diagnoses a
        # snapshot mismatch) but never aborts — it writes nothing anyway.
        return {"status": "dry_run", **summary}

    if skip_ratio > settings.ip_org_skip_abort_ratio:
        # A silent join collapse (the camelCase defect class). Abort BEFORE the
        # advisory lock so a bad snapshot never blocks a good concurrent refresh,
        # and never reaches _load_staging_and_swap so the existing data stands.
        logger.warning("ip_org_ingest_skip_ratio_abort", skip_ratio=skip_ratio)
        return {
            "status": "error",
            "error": f"skip ratio {skip_ratio:.3f} exceeds abort threshold",
            **summary,
        }

    if not rows:
        # An empty join would swap a populated table for an empty one — exactly
        # the "a refresh that cannot improve the data destroys it" failure.
        return {"status": "error", "error": "join produced zero rows", **summary}

    async with async_session() as lock_db:
        acquired = await _try_acquire_lock(lock_db)
        if acquired is False:
            logger.info("ip_org_ingest_lock_busy")
            return {"status": "locked"}
        try:
            async with async_session() as db:
                try:
                    await _load_staging_and_swap(
                        db, rows, "caida_pfx2as", dataset_date
                    )
                except Exception as exc:
                    try:
                        await db.rollback()
                        await db.execute(
                            text(f'DROP TABLE IF EXISTS "{IP_ORG_STAGING_TABLE}"')
                        )
                        await db.commit()
                    except Exception:
                        pass
                    logger.warning("ip_org_ingest_load_failed", error=str(exc))
                    return {"status": "error", "error": str(exc), **summary}
        finally:
            if acquired:
                await _release_lock(lock_db)

    duration = (datetime.now(timezone.utc) - started).total_seconds()
    logger.info("ip_org_ingest_complete", rows=len(rows), duration_s=duration)
    return {"status": "ok", "duration_s": duration, **summary}
