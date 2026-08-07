---
name: report:ip-org-prod-enable-runbook
description: "Operator runbook: 3 steps to enable ip-org lookup in prod after the 2026-08-07 schema deploy (head c4a8f13e07b6 live, tables empty, flags OFF) — prod ingest, flag flips, source-mix monitoring"
date: 07-08-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
  phase: ip-org-database-phase3-closeout
---

# ip-org prod-enable runbook (post Phase 3 deploy, 07-08-26)

**Starting state (verified 2026-08-07):** prod alembic head `c4a8f13e07b6`; `ip_org_prefixes` +
`rpki_roas` exist on prod and are EMPTY; all 4 ip-org flags OFF; `/health` + `/health/ready` 200.
Zero runtime behavior change until step 2.

**Standing safety rule:** `.env` in this repo points at Supabase PROD. Every command below that
touches prod does so DELIBERATELY via an explicit DSN — never rely on ambient `.env`. For any
NON-prod work, pin `DATABASE_URL` to `localhost:5433` first (memory note
`getbeam-env-points-to-supabase-prod`).

## Step 1 — Prod ingest (~13 min, one-off)

`scripts/refresh_ip_org.py --apply` has a fail-closed local-host guard: it REFUSES a non-local
DSN unless `--allow-remote` is passed explicitly. That is the deliberate double-key for this
step.

```bash
# From repo root, venv active. Substitute the real prod DSN — do NOT let it come from .env implicitly.
DATABASE_URL='<prod-supabase-dsn>' \
  .venv/bin/python3.11 scripts/refresh_ip_org.py --apply --allow-remote
```

- Expected duration: ~13 min (local dev reference: 341s cold / 158s re-run for the CAIDA leg
  alone; Phase 3 adds RIR + RPKI legs).
- Load is staging-swap + advisory-lock protected (`IP_ORG_WRITE_LOCK_KEY`); a crash mid-load
  leaks 0 rows (proven accidentally in Phase 1-2 EVL).
- Post-check (read-only): row counts should land near local reference — `ip_org_prefixes`
  ~967k CAIDA + ~262k RIR evidence rows, `rpki_roas` ~755k. Also note followups item 5: the
  freshly swapped table has no planner statistics until autovacuum ANALYZE (~15.7ms lookups in
  the window); optionally run a manual `ANALYZE ip_org_prefixes;` right after the swap.

## Step 2 — Flag flips (Railway dashboard, api service env)

Set on Railway (service `retarget-agent` api), then let the service restart:

```
IP_ORG_LOOKUP_ENABLED=true
COMPANY_GRAPH_ENABLED=true
```

- Order matters conceptually: `COMPANY_GRAPH_ENABLED` is the write-through target
  (`company_resolver.py` writes `company_graph` `source="rir_asn"` conf 0.45); flipping lookup
  without the graph flag discards the durable half of the value.
- Do NOT flip the 3 Phase-3 flags (`ip_org_fusion_enabled`, `ip_org_rir_ingest_enabled`,
  `ip_org_rpki_ingest_enabled`) in the same change unless the fused lookup-v2 path is the
  explicit goal — flip incrementally so a regression is attributable.
- Verify: `/health` 200 after restart; `railway logs` shows no ip-org startup errors.

## Step 3 — Monitor `company_graph.source` distribution

For the first days after enable, watch the source mix (read-only, via
`railway run -s retarget-agent` + psql per the memory-note recipe):

```sql
SELECT source, count(*), avg(confidence)
FROM company_graph_nodes
GROUP BY source ORDER BY count(*) DESC;
```

- Expect `rir_asn` rows to appear and grow; confidence pinned at 0.45.
- Red flags: `rir_asn` dominating over rDNS/paid sources on IPs those sources previously
  resolved (ladder-order bug), or eyeball-carrier names (e.g. bare `telekom` — known Phase-1
  token gap, followups item 7) appearing as org-kind company names.
- Also watch lookup latency vs the 15ms warm budget (followups items 5–6: tail was 14.85ms on
  dev; prod adds network distance to Supabase).

## Rollback

Flags OFF (step 2 reversed) restores pre-enable behavior instantly — the tables are additive
and inert when flags are off. No schema rollback needed.
