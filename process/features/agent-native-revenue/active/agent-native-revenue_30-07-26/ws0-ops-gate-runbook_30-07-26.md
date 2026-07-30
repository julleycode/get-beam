---
name: runbook:ws0-ops-gate
description: "WS0 ops-gate runbook — take dev_nhantc2 marker + resolution-priority code live and prove it with wild traffic"
date: 30-07-26
metadata:
  node_type: runbook
  type: reference
  feature: agent-native-revenue
  phase: WS0
---

# WS0 Ops-Gate Runbook

**Goal:** get the `dev_nhantc2` marker + AI-attribution resolution-priority code live in prod and prove, with WILD traffic, that it produces at least one real identified company from an AI-agent handoff.

**Audience:** the human operator (you). Most steps here are HARD STOPs Claude cannot do (billing, merge, prod env, wild traffic). Claude can only prepare/verify read-only.

**Authoring caveat:** written from this session's verified findings (R2 code re-verify, 6/6 TRUE) + established deploy memory. Items marked `⚠ re-verify` were NOT re-read live at authoring time (a subagent hit the account monthly spend limit mid-run) — confirm them yourself before acting.

---

## Step ladder (each maps to an AC)

| Step | What | Class | AC |
|---|---|---|---|
| a | Fix GitHub Actions billing | HARD STOP (you) | — (unblocks WS0-1) |
| 1 | Pre-merge review of dev_nhantc2 | read-only | WS0-1 |
| b | PR dev_nhantc2 → main, merge | HARD STOP (you) | WS0-1 |
| c | Prod env: keys + marker flag | HARD STOP (you) | WS0-2 |
| d | Wild marker survival test / vendor | HARD STOP (you) | WS0-3, WS0-4 |
| e | Exit metric: ≥1 identified visitor | read-only verify | WS0-5 |

---

## Step (a) — Unblock CI  [HARD STOP: you]

**The CI red is a billing failure, not code.** The `Tests` workflow (`.github/workflows/test.yml`) triggers only on `main` (`push`/`pull_request`). It never ran on `dev_nhantc2` — `gh run list --branch dev_nhantc2` is empty. Every recent `Tests` run on `main` failed with: *"The job was not started because recent account payments have failed or your spending limit needs to be increased."*

Do:
1. GitHub → `julleycode/get-beam` → Settings → **Billing & plans** → fix payment method / raise spending limit.
2. Re-run a failed run:
   ```bash
   gh run rerun 30349742431
   ```
**Verify:** the job actually *starts* (status leaves `queued`, runs the checkout step). If it starts, billing is fixed.

> Note: this is the SAME class of problem as the Claude monthly spend limit that just halted the runbook subagent — two separate accounts, both spend-limited. Raising the GitHub limit does not touch the Claude one.

---

## Step 1 — Pre-merge review  [read-only]

The marker + resolution code on `origin/dev_nhantc2` was re-verified this session — **6/6 claims TRUE** (see the research findings / phase context). Summary of what merges:
- `apps/api/services/agent_marker.py` — Fernet marker, TTL 7 days, reuses **`ENCRYPTION_KEY`** (via `link_decorator._get_fernet()`), fail-safe typed decode.
- `apps/api/routers/events.py` — decodes `_bam`, gated by **`settings.agent_marker_enabled`**, writes `agent_handoff_links` (tenant-checked).
- `apps/api/services/resolution_eligibility.py` + `resolution_runner.py` — AI-attributable visitors (`ai_source` set OR handoff-linked) bypass the intent floor and sort first.
- Emailability separation intact (`test_agent_origin_exclusion.py`).

Before merging, confirm the migration chain is a single head and review the FULL pending chain (Railway will auto-apply ALL of it on deploy — see Step b warning):
```bash
cd /Users/apple/getbeam
git fetch origin
git checkout origin/dev_nhantc2 -- apps/api   # or check out the branch in a scratch worktree
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads   # MUST be a single head
```
`all-context.md` lists 12+ pending migrations (the ai_source marker migration `b3f9a1d2c7e5`, handoff `e2a4c7f81b93`, etc.). ⚠ re-verify the live head immediately before merge — concurrent work advances it (WS2 added `f4c1a9e2d3b8` on a separate unmerged branch; other programs have advanced it repeatedly).

**Backfill:** NOT needed (verified this session — resolution eligibility is computed fresh from current DB state every sweep; pre-existing `ai_source`/handoff visitors get picked up on the next sweep automatically).

---

## Step (b) — Merge dev_nhantc2 → main  [HARD STOP: you]

⚠ **Highest-risk step. Merging to `main` is a PROD DDL event.** Railway's api Dockerfile CMD runs `alembic upgrade head` on **every boot**, so the moment `main` deploys, **all pending migrations auto-apply to prod Postgres**. There is no separate "apply migration" gate — the merge IS the apply.

Do:
1. Open PR `dev_nhantc2` → `main`. **Never push to `dev_nhantc2`** (someone else's active branch).
2. Confirm CI is green on the PR (needs Step a done first).
3. Review, then merge.

**What can go wrong:** a broken/duplicate migration head → Railway boot fails `alembic upgrade head` → api down. Mitigation: Step 1's single-head check + review the chain before merging. Have the Railway rollback ready.

**Verify:** after Railway redeploys, `railway logs` shows a clean `alembic upgrade head` and the api boots.

---

## Step (c) — Prod env  [HARD STOP: you]

All api-side env goes on **Railway** (api.getbeam.fyi). Web is on **Vercel** (project `retarget-agent`) — not relevant here except the pixel/beacon. Cloudflare only proxies DNS/WAF.

Set / confirm on Railway (api service):
1. **`ENCRYPTION_KEY`** — must already be present (marker reuses it; prod startup `validate_production` fails without it). If present, do nothing.
2. **`AGENT_MARKER_ENABLED=true`** — the flag `events.py` reads (`settings.agent_marker_enabled`). ⚠ re-verify exact env var name from `config.py` on the merged code. Default is OFF.
3. **Provider keys for resolution** — `PEOPLE_DATA_LABS_API_KEY` (PDL) and `PROXYCURL_API_KEY`. Without these, handoff visitors qualify for resolution but resolve to nothing (`identified_visitors=0` — exactly the gap the journal flagged). ⚠ confirm exact names in `config.py` env groups.
4. ⚠ Confirm CF-Connecting-IP trust is on (`ingest_trust_cf_connecting_ip` / `trusted_proxy_hops`) so resolution sees real client IPs, not CF edge IPs (172.68/71.x etc.) — otherwise every resolve is a blanket no-match.

**Order matters:** set `ENCRYPTION_KEY` + provider keys BEFORE flipping `AGENT_MARKER_ENABLED`. Flipping the marker flag with no `ENCRYPTION_KEY` → decode returns `no_key` and silently no-ops (marker never links anything).

**Verify (read-only, no mutation):**
```bash
railway run -s retarget-agent -- printenv | grep -E 'AGENT_MARKER_ENABLED|ENCRYPTION_KEY|DATA_LABS|PROXYCURL' | sed 's/=.*/=<set>/'
```
(mask values; just confirm presence). ⚠ adjust service name if not `retarget-agent`.

---

## Step (d) — Wild marker survival test, per vendor  [HARD STOP: you]

**Cannot be spoofed or done by Claude.** CF WAF treats named AI fetchers as verified bots; you cannot fake a vendor UA past it. You must drive the real product.

Per vendor (ChatGPT, Perplexity, Claude — at minimum):
1. Have a real page live with an offers feed carrying the marker (`?_bam=` on same-host links — offers.json, `private, no-store`).
2. Ask the real assistant about that page/product so its fetcher reads it.
3. Click the link in the assistant's answer (this is the "handoff" click).
4. Grep prod logs for the marker write:
   ```bash
   railway logs -s retarget-agent | grep -iE 'marker|_bam|handoff|record_marker_handoff'
   ```
   Look for a handoff-link write tied to `method=marker` with `?_bam=` surviving.
5. Record **YES/NO per vendor** in a dated journal (`docs/journals/`).

**If a vendor STRIPS the query param (NO):** before declaring that vendor dead, try the **`/r/<token>` 302 path-token fallback** (SEO-safe conditions: token URLs never in nav/sitemap/internal links, `rel=nofollow`/`X-Robots noindex`, single fast hop, watch 302→301 drift). The **temporal correlation sweep** (`agent_handoff_correlation.py`, already live) is the backstop net regardless — a probabilistic vendor+page+30-min match, lower confidence but marker-independent.

---

## Step (e) — Exit metric  [read-only verify]

The gate that unlocks WS3's wild kill-test window: **≥1 `identified_visitors` row on prod attributable to a handoff or `ai_source` visitor.**

```bash
railway run -s retarget-agent -- psql "$DATABASE_URL" -c \
"SELECT COUNT(*) FROM identified_visitors iv
 JOIN visitors v ON v.id = iv.visitor_id
 WHERE v.ai_source IS NOT NULL
    OR EXISTS (SELECT 1 FROM agent_handoff_links l WHERE l.visitor_id = v.id);"
```
⚠ column/table names re-verify against the merged schema. Count ≥ 1 = WS0 exit metric met, WS0 DONE.

> Note: the Postgres Railway service may not expose DB vars directly — you may need `railway run -s <api-service>` (which has `DATABASE_URL`) rather than the Postgres service. Per the deploy memory, use the api service context for psql.

---

## HARD STOP summary (Claude cannot do these)

- (a) GitHub billing fix
- (b) PR merge to main (= prod DDL via Railway auto-migrate)
- (c) prod env flips (marker flag, keys) + any provider spend beyond free tier
- (d) wild traffic test (real ChatGPT/Claude/Perplexity)
- Also blocking right now: **Claude account monthly spend limit** — raise at claude.ai/settings/usage before Claude can run more subagents for WS1/WS3.

## What Claude CAN do next (once Claude spend limit is raised)
- WS1 INNOVATE/PLAN (per-visitor AgentFetchEvent timeline endpoint + dashboard section) — buildable pre-merge.
- WS3 INNOVATE (param-gated MCP tools + conversion tool + Developer-Mode discovery) — design pre-merge; wild kill-test needs Step (e) met.
