"""Measure ip-org lookup precision against the derived-label corpus (WS-B / B4).

Runs against the LOCAL ``localhost:5433`` corpus (Q13) — ``ip_org_prefixes`` is
EMPTY on prod, so a prod-side lookup would return ``None`` for every row (a
vacuity trap). A non-local DSN is refused.

What this measures (Q14/R1 — the v1-vs-v2 McNemar framing is withdrawn as
degenerate by construction; both arms select the SAME row):

  (a) SINGLE-ARM precision = correct / rows-with-a-non-None-prediction (P1-3),
      with coverage = non-None / headline-rows reported SEPARATELY. match_method
      is a numerator DECOMPOSITION (share of correct by exact vs token_subset),
      never a per-method precision.
  (b) Per-REACHABLE-VALUE confidence calibration over the 7 reachable v2 values
      {0.20,0.25,0.40,0.45,0.55,0.60,0.65} (P1-1) — NOT equal-width buckets.
  (b2) Accuracy by v2_classification over all FOUR reachable values incl.
      ``unclassified`` (P2-9/C-34).
  (c) A ``v1_pred == v2_pred`` INVARIANT (not a comparison): any divergence is a
      BUG, asserted ONLY when the duplicate-prefix probe returns zero (E19/C-28 —
      the invariant runs through untouched production SQL, KG-9).

Coverage / None-rate reported per arm (R6, KG-7 forward baseline). NO precision
threshold is asserted (AC4.12 precedent). ``domain`` is NEVER scored (R2 — NULL
by construction; the domain leg was split out of Phase 3).
"""

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.config import settings  # noqa: E402
from apps.api.services.ip_org_ingest import normalize_org_name  # noqa: E402

_REACHABLE_CONFIDENCES = [0.20, 0.25, 0.40, 0.45, 0.55, 0.60, 0.65]
_CLASSIFICATIONS = [
    "registered_operator",
    "likely_operational_customer",
    "disputed_origin",
    "unclassified",
]

# Unfiltered stratum query (Q14): NO org_kind filter, longest-prefix first, with
# the ``, id`` deterministic tie-break (P2-8) so the script's own row choice is
# stable run-to-run. This is the ONLY correct source of stratum — a lookup-derived
# stratum can only ever be 'org' or nothing (FAIL-4).
_STRATUM_SQL = (
    "SELECT org_kind FROM ip_org_prefixes "
    "WHERE prefix >>= CAST(:ip AS inet) AND relationship_type = 'route_origin' "
    "ORDER BY masklen(prefix) DESC, id LIMIT 1"
)

# Duplicate-prefix probe (E19/C-28): the v1==v2 invariant runs through the
# UNTOUCHED production SQL, whose ORDER BY is non-total; a duplicate equal-masklen
# prefix could manufacture a FALSE divergence. Zero result → invariant meaningful.
_DUP_PROBE_SQL = (
    "SELECT count(*) FROM ("
    "  SELECT prefix, masklen(prefix) FROM ip_org_prefixes "
    "  WHERE relationship_type='route_origin' AND org_kind='org' "
    "  GROUP BY prefix, masklen(prefix) HAVING count(*) > 1"
    ") d"
)


def match_org(expected: str, predicted: str | None) -> tuple[bool, str | None]:
    """Q5 matcher: exact-first, bounded token-subset fallback, per-method label.

    Both sides go through ``normalize_org_name``. (1) exact equality → ``exact``;
    (2) the smaller token set is a subset of the larger AND has >=1 token of
    length >=4 → ``token_subset``; (3) otherwise no match. No Levenshtein, no
    embeddings, no new dependency.
    """
    if not predicted:
        return (False, None)
    e = normalize_org_name(expected)
    p = normalize_org_name(predicted)
    if not e or not p:
        return (False, None)
    if e == p:
        return (True, "exact")
    et, pt = set(e.split()), set(p.split())
    smaller, larger = (et, pt) if len(et) <= len(pt) else (pt, et)
    if smaller and smaller <= larger and any(len(t) >= 4 for t in smaller):
        return (True, "token_subset")
    return (False, None)


def _is_local(dsn: str) -> bool:
    host = (urlparse(dsn).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1", ""}


def _read_corpus(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        header = fh.readline()  # ip\temail_domain\texpected_org\tstratum
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            rows.append({"ip": parts[0], "email_domain": parts[1], "expected": parts[2]})
    return rows


async def _score(dsn: str, corpus: list[dict]) -> dict:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from apps.api.services.ip_org_lookup import lookup_ip_org, lookup_ip_org_v2

    engine = create_async_engine(dsn)
    results: list[dict] = []
    async with engine.connect() as raw:
        # Non-vacuity precondition (fatal, checked FIRST).
        assert settings.ip_org_lookup_enabled is True, "flag not enabled in-process"
        n_prefixes = (
            await raw.execute(text("SELECT count(*) FROM ip_org_prefixes"))
        ).scalar()
        if not n_prefixes:
            raise SystemExit(
                "FAILED-INVALID: ip_org_prefixes is empty — cannot produce a "
                "non-None prediction"
            )
        dup_count = int(
            (await raw.execute(text(_DUP_PROBE_SQL))).scalar() or 0
        )

    async with AsyncSession(engine) as db:
        for row in corpus:
            ip = row["ip"]
            stratum_row = (
                await db.execute(text(_STRATUM_SQL), {"ip": ip})
            ).first()
            stratum = stratum_row[0] if stratum_row else "none"

            v1 = await lookup_ip_org(db, ip)
            v2 = await lookup_ip_org_v2(db, ip)
            v1_pred = v1.org_name if v1 else None
            v2_pred = v2["organization"] if v2 else None
            v1_ok, v1_method = match_org(row["expected"], v1_pred)
            v2_ok, v2_method = match_org(row["expected"], v2_pred)
            results.append({
                "ip": ip,
                "expected": row["expected"],
                "stratum": stratum,
                "v1_pred": v1_pred,
                "v1_ok": v1_ok,
                "v1_method": v1_method,
                "v2_pred": v2_pred,
                "v2_ok": v2_ok,
                "v2_method": v2_method,
                "v2_conf": round(v2["confidence"], 4) if v2 else None,
                "v2_class": v2["classification"] if v2 else None,
            })
    await engine.dispose()
    return {"results": results, "dup_count": dup_count}


def _aggregate(results: list[dict], dup_count: int) -> str:
    total = len(results)
    # Headline set excludes datacenter/cdn strata (the ONE non-SQL rule).
    headline = [r for r in results if r["stratum"] not in ("datacenter", "cdn")]
    predicted = [r for r in headline if r["v2_pred"] is not None]
    correct = [r for r in predicted if r["v2_ok"]]

    lines: list[str] = []
    lines.append("# ip-org precision measurement (WS-B)")
    lines.append("")
    lines.append(f"- Date: {date.today().isoformat()}")
    lines.append(f"- Corpus rows scored: {total}")
    lines.append(f"- Headline rows (excl. datacenter/cdn strata): {len(headline)}")
    lines.append(f"- Predicted rows (non-None v2 prediction): {len(predicted)}")
    lines.append("")
    lines.append("## (a) Single-arm precision")
    prec = (len(correct) / len(predicted)) if predicted else 0.0
    cov = (len(predicted) / len(headline)) if headline else 0.0
    lines.append(f"- precision = correct / predicted = {len(correct)}/{len(predicted)} = {prec:.4f}")
    lines.append(f"- coverage  = predicted / headline  = {len(predicted)}/{len(headline)} = {cov:.4f}")
    lines.append("- NOTE: NO precision threshold is asserted (AC4.12 precedent); this is the forward baseline.")
    lines.append("")
    lines.append("### match_method numerator decomposition (share of CORRECT by method)")
    mm = Counter(r["v2_method"] for r in correct)
    for method in ("exact", "token_subset"):
        lines.append(f"- {method}: {mm.get(method, 0)}")
    lines.append("")
    lines.append("### per-stratum (with each stratum's predicted count)")
    strata = defaultdict(lambda: {"n": 0, "pred": 0, "correct": 0})
    for r in results:
        s = strata[r["stratum"]]
        s["n"] += 1
        if r["v2_pred"] is not None:
            s["pred"] += 1
            if r["v2_ok"]:
                s["correct"] += 1
    for st in sorted(strata):
        s = strata[st]
        lines.append(f"- {st}: rows={s['n']} predicted={s['pred']} correct={s['correct']}")
    lines.append("")
    lines.append("## (b) Per-reachable-value confidence calibration (7 values)")
    lines.append("| v2 confidence | n | correct | accuracy |")
    lines.append("|---|---|---|---|")
    by_conf = defaultdict(lambda: {"n": 0, "correct": 0})
    for r in predicted:
        c = r["v2_conf"]
        by_conf[c]["n"] += 1
        if r["v2_ok"]:
            by_conf[c]["correct"] += 1
    for c in _REACHABLE_CONFIDENCES:
        b = by_conf.get(c, {"n": 0, "correct": 0})
        acc = (b["correct"] / b["n"]) if b["n"] else 0.0
        lines.append(f"| {c} | {b['n']} | {b['correct']} | {acc:.4f} |")
    off = sorted(set(by_conf) - set(_REACHABLE_CONFIDENCES))
    lines.append(f"- values observed OUTSIDE the reachable 7 (a finding if non-empty): {off}")
    lines.append("- NOTE: 0.20 and 0.25 are reachable ONLY via rpki=invalid; expected near-empty at small N and carry no signal.")
    lines.append("")
    lines.append("## (b2) Accuracy by v2_classification (all FOUR reachable values)")
    by_cls = defaultdict(lambda: {"n": 0, "correct": 0})
    for r in predicted:
        by_cls[r["v2_class"]]["n"] += 1
        if r["v2_ok"]:
            by_cls[r["v2_class"]]["correct"] += 1
    for cls in _CLASSIFICATIONS:
        b = by_cls.get(cls, {"n": 0, "correct": 0})
        acc = (b["correct"] / b["n"]) if b["n"] else 0.0
        lines.append(f"- {cls}: n={b['n']} correct={b['correct']} accuracy={acc:.4f}")
    lines.append("")
    lines.append("## Coverage / None-rate per arm (R6 / KG-7 forward baseline)")
    v1_none = sum(1 for r in results if r["v1_pred"] is None)
    v2_none = sum(1 for r in results if r["v2_pred"] is None)
    lines.append(f"- v1 None-rate = {v1_none}/{total} over corpus IPs")
    lines.append(f"- v2 None-rate = {v2_none}/{total} over corpus IPs")
    lines.append(f"- coverage (predicted/headline) = {cov:.4f} — denominator is HEADLINE rows, not corpus IPs")
    lines.append("- No pre-C/E baseline exists (WS-B runs last); this is a forward baseline, not a delta (KG-7).")
    lines.append("")
    lines.append("## (c) v1_pred == v2_pred invariant")
    lines.append(f"- duplicate-prefix probe count: {dup_count}")
    if dup_count == 0:
        divergences = [r for r in results if r["v1_pred"] != r["v2_pred"]]
        lines.append(f"- probe zero → invariant ASSERTED. Divergences (BUGS): {len(divergences)}")
        for r in divergences[:50]:
            lines.append(f"  - ip stratum={r['stratum']} v1={r['v1_pred']!r} v2={r['v2_pred']!r}")
    else:
        lines.append("- probe NON-ZERO → invariant SKIPPED (not-run). A divergence here is a data")
        lines.append("  property of the untouched production ORDER BY (KG-9), not a defect.")
    lines.append("")
    lines.append("## Limitations")
    lines.append("- Derived labels, not ground truth (KG-3): a corporate email domain is strong but")
    lines.append("  imperfect evidence of the employer behind an IP. Free-mail exclusion is a judgment")
    lines.append("  list; residual leakage biases the headline number DOWNWARD.")
    lines.append("- The datacenter/CDN headline exclusion is produced BY THE SYSTEM UNDER TEST — a row")
    lines.append("  leaves the headline set because this pipeline called its prefix datacenter/cdn,")
    lines.append("  which systematically removes a class of the pipeline's own misclassifications (KG-3).")
    lines.append("- IPv6-only visitors are excluded by the IPv4 regex (parse_pfx2as drops IPv6).")
    lines.append("- No precision threshold asserted; baseline for the NEXT phase.")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure ip-org precision (LOCAL corpus).")
    ap.add_argument("--database-url", required=True, help="LOCAL localhost:5433 DSN (non-local refused).")
    ap.add_argument(
        "--corpus",
        default=str(Path(__file__).resolve().parent.parent
                    / "process/features/visitors-identity/active"
                    / "ip-org-quality-pack_08-08-26/benchmark-corpus.tsv"),
    )
    ap.add_argument(
        "--report",
        default=str(Path(__file__).resolve().parent.parent
                    / "process/features/visitors-identity/active"
                    / "ip-org-quality-pack_08-08-26/ip-org-precision_REPORT_08-08-26.md"),
    )
    args = ap.parse_args()

    if not _is_local(args.database_url):
        print("ERROR: --database-url must be LOCAL (localhost:5433). prod ip_org_prefixes is empty.", file=sys.stderr)
        return 2

    # In-process flag override (Q12) — local measurement process only, never a
    # deploy-level flip. lookup_ip_org_v2 does NOT read ip_org_fusion_enabled, so
    # it is deliberately NOT touched.
    settings.ip_org_lookup_enabled = True
    print("in-process override: settings.ip_org_lookup_enabled = True")

    corpus = _read_corpus(Path(args.corpus))
    if not corpus:
        print("FAILED-INVALID: empty corpus", file=sys.stderr)
        return 3

    scored = asyncio.run(_score(args.database_url, corpus))
    results = scored["results"]
    predicted_n = sum(
        1 for r in results
        if r["stratum"] not in ("datacenter", "cdn") and r["v2_pred"] is not None
    )
    if predicted_n == 0:
        print("FAILED-INVALID: zero non-None predictions — not a passing tie", file=sys.stderr)
        return 4

    report = _aggregate(results, scored["dup_count"])
    Path(args.report).write_text(report, encoding="utf-8")
    print(f"Wrote report to {args.report}")
    print(f"Predicted (stratum org) rows: {predicted_n} (floor for go/no-go is >=80)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
