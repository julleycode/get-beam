"""Build the ip-org benchmark corpus from PROD identified visitors (WS-B / B3).

READ-ONLY, PROD-reading extraction. Emits a TSV of derived-label ground truth
rows ``(ip, email_domain, expected_org, stratum)`` for measuring ip-org lookup
precision. The corpus is PII-adjacent (a domain + an IP can re-identify a small
company), so:

- Email LOCAL-PARTS never leave the database — only ``split_part(email,'@',2)`` is
  selected (C-33/E15). The bare ``email`` column appears in NO select list.
- The session is server-side READ ONLY: any accidental write raises
  ``ReadOnlySQLTransactionError`` at the server (B3).
- An explicit DSN is REQUIRED (``--database-url`` or ``IP_ORG_BENCHMARK_DSN``);
  the script NEVER reads ``settings.database_url`` — that is the ``.env`` →
  Supabase-prod footgun. Remote DSNs ARE allowed here (read-only is the point),
  but must be explicit.
- ``stratum`` is written as the literal ``pending`` and filled by the measurement
  script from the LOCAL corpus (Q13): ``ip_org_prefixes`` is empty on prod.
- The output filename is gitignored and deleted after the measurement report is
  written (Q4 retention).

Two DSNs (Q13): THIS script reads PROD; ``measure_ip_org_precision.py`` reads the
LOCAL ``localhost:5433`` corpus.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import asyncpg

# WS-D dependency (P1-2): expected_org is derived via the vendored PSL parser.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.services.content_reader import _GENERIC_DOMAINS  # noqa: E402
from apps.api.services.ip_org_ingest import normalize_org_name  # noqa: E402
from apps.api.services.public_suffix import registrable_domain  # noqa: E402

# Strict octet-range IPv4 regex (B2b/P1-5): every value that survives it is
# guaranteed castable to ``inet`` (``999.1.2.3`` does NOT match). Postgres does
# NOT short-circuit AND, so this must fence the cast via a MATERIALIZED CTE, not
# merely precede it in WHERE order.
_STRICT_IPV4 = (
    r"^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}"
    r"(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
)

# Naive-UTC CF-fix cutoff (R13): resolved_at / events.created_at are timestamp
# WITHOUT time zone; this is commit e4c1db8's instant converted to UTC. Rows
# before it may carry Cloudflare edge IPs that would score the CDN, not the
# visitor.
_CF_FIX_CUTOFF = "2026-07-26 09:13:43"

# Benchmark-specific free-mail exclusion (B2a/C-26): reuse the ONE existing set,
# ADD consumer-mail domains it omits (which would otherwise carry a fabricated
# expected_org that can never match, DEPRESSING precision), and REMOVE two real
# employers it contains (their staff are correctly-labelled rows). The addendum is
# benchmark-local and is NEVER written back into content_reader.
_BENCHMARK_FREE_MAIL_ADDENDUM = {
    "live.com", "msn.com", "me.com", "googlemail.com", "mail.com", "gmx.com",
    "yandex.ru", "qq.com", "163.com", "naver.com", "zoho.com", "proton.me",
}
_BENCHMARK_REAL_EMPLOYERS = {"linkedin.com", "x.com"}
FREE_MAIL_EXCLUDE = (
    (set(_GENERIC_DOMAINS) | _BENCHMARK_FREE_MAIL_ADDENDUM)
    - _BENCHMARK_REAL_EMPLOYERS
)


def label_root(email_domain: str) -> str | None:
    """Leftmost label of the registrable domain (P1-2), e.g. ``deloitte.co.uk``
    → ``deloitte``. Returns ``None`` for a bare public suffix / unparseable host.

    A registrable domain is by construction ``public_suffix + one label``, so the
    leftmost label IS the root.
    """
    reg = registrable_domain(email_domain)
    if not reg:
        return None
    parts = reg.split(".", 1)
    if len(parts) < 2:
        return None
    suffix = parts[1]
    return reg[: -(len(suffix) + 1)] or None


def expected_org_for(email_domain: str) -> str | None:
    root = label_root(email_domain)
    if not root:
        return None
    return normalize_org_name(root) or None


# Explicit projection only (C-33): the CTE NEVER selects a bare ``email`` column;
# only ``split_part(email,'@',2)`` crosses the wire. ``AS MATERIALIZED`` fences
# the planner from hoisting the ``::inet`` cast above the strict-regex filter.
# The agent-origin / human-only predicates are hand-inlined (C-30/E17 option c):
# ``human_only_visitor_filter()`` is a SQLAlchemy Core predicate builder and
# cannot compose into a raw asyncpg SQL string; the canonical helper was
# deliberately NOT reused. Sync pointer: apps/api/services/agent_visitor_filters.py:19.
_EXTRACT_SQL = f"""
WITH candidates AS MATERIALIZED (
    SELECT iv.site_id,
           iv.visitor_id,
           iv.resolved_at,
           split_part(iv.email, '@', 2) AS email_domain,
           COALESCE(
               (
                   SELECT e.ip_address
                   FROM events e
                   WHERE e.site_id = iv.site_id
                     AND e.visitor_id = iv.visitor_id
                     AND e.created_at <= iv.resolved_at
                     AND e.created_at > '{_CF_FIX_CUTOFF}'
                     AND e.ip_address <> ''
                     AND e.ip_address ~ '{_STRICT_IPV4}'
                   ORDER BY e.created_at DESC
                   LIMIT 1
               ),
               v.ip_address
           ) AS ip_address
    FROM identified_visitors iv
    JOIN visitors v
      ON iv.site_id = v.site_id AND iv.visitor_id = v.visitor_id
    WHERE iv.email IS NOT NULL
      AND iv.resolved_at > '{_CF_FIX_CUTOFF}'
      AND iv.source_agent_visit_id IS NULL
      AND v.do_not_resolve = false
      AND v.is_abuse_flagged = false
      AND v.is_bot_suspect = false
      AND v.is_agent_operated = false
      AND v.is_internal_suspect = false
      AND split_part(iv.email, '@', 2) <> ALL($1::text[])
      AND v.ip_address IS NOT NULL
      AND v.ip_address ~ '{_STRICT_IPV4}'
)
SELECT DISTINCT ON (ip_address)
       ip_address, email_domain
FROM candidates
WHERE ip_address IS NOT NULL
  AND ip_address <> ''
  AND ip_address ~ '{_STRICT_IPV4}'
  AND NOT (ip_address::inet <<= ANY (ARRAY[
      '10.0.0.0/8','172.16.0.0/12','192.168.0.0/16',
      '127.0.0.0/8','169.254.0.0/16'
  ]::inet[]))
ORDER BY ip_address, resolved_at DESC
LIMIT $2
"""

_COUNT_SQL = f"""
SELECT count(*) FROM (
    SELECT DISTINCT v.ip_address
    FROM identified_visitors iv
    JOIN visitors v
      ON iv.site_id = v.site_id AND iv.visitor_id = v.visitor_id
    WHERE iv.email IS NOT NULL
      AND iv.resolved_at > '{_CF_FIX_CUTOFF}'
      AND iv.source_agent_visit_id IS NULL
      AND v.do_not_resolve = false
      AND v.is_abuse_flagged = false
      AND v.is_bot_suspect = false
      AND v.is_agent_operated = false
      AND v.is_internal_suspect = false
      AND split_part(iv.email, '@', 2) <> ALL($1::text[])
      AND v.ip_address IS NOT NULL
      AND v.ip_address ~ '{_STRICT_IPV4}'
) s
"""


async def _connect(dsn: str) -> asyncpg.Connection:
    conn = await asyncpg.connect(dsn)
    # Structural write-prevention (B3/G6): any accidental write raises at the
    # server, not at review time.
    await conn.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
    # Naive resolved_at comparison is unambiguous under an explicit UTC session
    # (R13).
    await conn.execute("SET TIME ZONE 'UTC'")
    return conn


async def run_count(dsn: str) -> int:
    conn = await _connect(dsn)
    try:
        return int(await conn.fetchval(_COUNT_SQL, list(FREE_MAIL_EXCLUDE)))
    finally:
        await conn.close()


async def run_extract(dsn: str, limit: int, out_path: Path) -> int:
    conn = await _connect(dsn)
    try:
        rows = await conn.fetch(_EXTRACT_SQL, list(FREE_MAIL_EXCLUDE), limit)
    finally:
        await conn.close()

    written = 0
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write("ip\temail_domain\texpected_org\tstratum\n")
        for r in rows:
            domain = (r["email_domain"] or "").strip().lower()
            expected = expected_org_for(domain)
            if not expected:
                continue  # bare public suffix / unparseable → no usable label
            fh.write(f"{r['ip_address']}\t{domain}\t{expected}\tpending\n")
            written += 1
    return written


def _resolve_dsn(args) -> str | None:
    return args.database_url or os.environ.get("IP_ORG_BENCHMARK_DSN")


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the ip-org benchmark corpus (PROD, read-only).")
    ap.add_argument("--database-url", help="Explicit PROD DSN (read-only). Required if IP_ORG_BENCHMARK_DSN unset.")
    ap.add_argument("--count-only", action="store_true", help="B1 go/no-go: print the SQL upper-bound count and exit.")
    ap.add_argument("--limit", type=int, default=600, help="Max rows to extract (C-31: ~500-600).")
    ap.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent.parent
                    / "process/features/visitors-identity/active"
                    / "ip-org-quality-pack_08-08-26/benchmark-corpus.tsv"),
        help="Output TSV path (gitignored).",
    )
    args = ap.parse_args()

    dsn = _resolve_dsn(args)
    if not dsn:
        print(
            "ERROR: no DSN. Pass --database-url or set IP_ORG_BENCHMARK_DSN. "
            "This script never reads settings.database_url (the .env→prod footgun).",
            file=sys.stderr,
        )
        return 2

    if args.count_only:
        n = asyncio.run(run_count(dsn))
        print(f"B1 SQL upper-bound (distinct usable IPs): {n}")
        return 0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = asyncio.run(run_extract(dsn, args.limit, out_path))
    print(f"Wrote {n} corpus rows to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
