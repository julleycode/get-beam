---
name: report:repo-audit-14-11-26
description: "Repo audit 14-11-26 — git/deploy state, prod verification (alembic head, flags, PII, origin bypass, CI), PR verdicts, plans archived, open operator/legal steps, and large programs not started"
date: 14-11-26
metadata:
  node_type: memory
  type: report
  feature: general-plans
  phase: update-process
---

# Repo audit — 14-11-26

**Bottom line:** `main` is what runs in prod, and most "planned" work in `process/` had already
shipped. The audit archived 14 finished task folders, corrected the context doc, and found four
real problems, each now with a fix PR in progress: a forgeable client IP via the direct Railway
origin, PII keys not checked at startup, CI red for three months, and GDPR erasure gaps. One piece
of work (roster-precision) is lost for good.

Evidence labels used below: **[verified]** = checked on prod / in git today by the orchestrator or
this pass; **[in progress]** = work opened today, not yet merged.

## 1. Git and deploy state

| Item | State |
|---|---|
| Prod runs | `main`. The `Dockerfile` `CMD` runs `alembic upgrade head` before uvicorn on every Railway boot, so "merged to main" == "applied on prod". **[verified]** |
| Remote branches left | `main`, `dev_nhantc2`, `feat/ws1-ai-evaluation-timeline` (PR 90), `feat/ws3-agent-concierge` (PR 92) **[verified via `git ls-remote`]** |
| Remote branches deleted | 54 stale branches. SHAs: `deleted-branches-backup_NOTE_14-11-26.md` (same folder) |
| Backup tags pushed | `backup/agentic-commerce-2026-10-25`, plus `backup/*-2026-11-14` for the 5 branches with unique work |
| `dev_nhantc2` | Holds commits not on main; partial cherry-pick only. Held commits are tracked in a backlog note written by another PR today |
| Agentic commerce | Web-side MPP/x402 reverted from main on 25-10-26 (`1df9a80`). Redo = Python InFlow x402 seller under `/api/v1/paid` (`cb3cf31`), flag OFF |
| This branch | `chore/repo-audit-cleanup` = origin/main `6ef19f7` + 3 cherry-picked agent-native-revenue docs commits + this process-only reconciliation |

## 2. Prod verification results

| Check | Result |
|---|---|
| Alembic head | `d3f8a2c61b47` (`add_paid_requests`) **[verified on prod]** |
| Co-op expiry index `uq_coop_ledger_expire_per_lot` | Present on prod — finding F-B closed **[verified]** |
| Flags ON | `AGENT_DETECTION_ENABLED`, `AGENT_FETCH_BEACON_ENABLED`, `AGENT_GATEWAY_ENABLED`, `AGENT_MARKER_ENABLED`, `COMPANY_GRAPH_ENABLED`, `CONNECTION_NUDGE_ENABLED`, `LOCATION_REVEAL_ENABLED`, `REFERRALS_ENABLED`, `REQUEST_LOG_ENABLED`, `TINYFISH_ENRICHMENT_ENABLED` **[verified in Railway env]** |
| Flags OFF | Everything else, incl. `inflow_x402`, `engage_outcome_capture`, `identity_signals`, co-op flags, ip-org flags |
| PII at rest | All 11 `*_ciphertext` columns: 0 non-Fernet rows (no plaintext) **[verified]** |
| PII key config | `PII_ENCRYPTION_KEY` is EMPTY on prod; `pii_crypto` falls back to `ENCRYPTION_KEY` (valid Fernet). `validate_production` did not check PII keys |
| Origin exposure | `retarget-agent-production.up.railway.app` is reachable directly, bypassing Cloudflare, so `CF-Connecting-IP` can be forged |
| CI | `.github/workflows/test.yml` red on main since ~13-08-26; last green 22-07-26 |

**Warning:** never set `PII_ENCRYPTION_KEY` to a new value without a rotation step. Existing
ciphertext was written with `ENCRYPTION_KEY`; a new key makes it unreadable.

## 3. Pull requests

| PR / branch | Verdict |
|---|---|
| PR 90 — WS1 AI evaluation timeline | Keep. Rebase + fix **[in progress]** |
| PR 91 — WS2 agent-session classifier | CLOSED 14-11-26 — superseded by `457e3c1` on main **[verified]** |
| PR 92 — WS3 agent concierge | Keep. Rebase + fix **[in progress]** |
| `dev_nhantc2` | Partial cherry-pick; rest held |
| `fix/live-security-hardening` | New today **[in progress — not visible in `gh pr list` at time of writing]**. Origin-bypass IP trust (shadow, then enforce) + PII key startup check |
| `fix/gdpr-erasure-gaps` | New today **[in progress — not visible yet]** |
| `fix/tinyfish-x402-hardening` | New today **[in progress — not visible yet]** |
| `fix/ci-green` | New today **[in progress — not visible yet]** |
| `feat/aggregation-watermark-bootstrap` | New today **[in progress — not visible yet]** |
| `feat/seed-verified-prod-demo` | New today **[in progress — not visible yet]** |

At the time this report was written, `gh pr list` showed only PR 90 and PR 92 open.

## 4. What this pass changed in `process/`

**Archived to `completed/` (14 task folders, each with a closeout line at the top of its main file):**

| Feature | Folder | Code on main |
|---|---|---|
| visitors-identity | `coop-disposable-e2e_17-08-26` | `7eec0a9` |
| visitors-identity | `coop-expiry-index-guard_17-08-26` | `2a0fe3b` (F-B closed) |
| visitors-identity | `graph-erasure-compliance_07-08-26` | `784aba2`, `2136219` (KG-4 counsel review stays open) |
| visitors-identity | `identity-program_03-08-26` | all 6 phases reported |
| visitors-identity | `identity-vocab-reconcile_07-08-26` | on main |
| visitors-identity | `job-change-detection_07-08-26` | `13d6901` (flag OFF) |
| visitors-identity | `ip-best-selection-retrigger_09-08-26` | none — superseded by `ip-best-selection-phase1_13-08-26` |
| visitors-identity | `identity-coverage-pixel-fppro_02-08-26` | Ph3/Ph4 remainders moved to backlog |
| onboarding-canary | `reveal-display-policy_17-08-26` | `9b8dc23` |
| onboarding-canary | `site-analysis-onboarding_13-08-26` | `7081402` |
| pixel | `ws2-agent-session-activation_07-08-26` | `457e3c1` |
| campaigns-outreach | `linkedin-extension-onboarding_26-07-26` | `ecedc2e` |
| general-plans | `group3-autopilot-run_07-08-26` | report only |
| general-plans | `e2e-local-smoke_10-08-26` | report only; concerns moved to backlog |

**New backlog notes:** `roster-precision-lost_NOTE_14-11-26.md` and
`identity-coverage-ph3-ph4-remainders_NOTE_14-11-26.md` (visitors-identity);
`e2e-local-smoke-concerns_NOTE_14-11-26.md` (general).

**Status lines corrected** on 19 plans that stay active, **9 backlog notes** confirmed
resolved/superseded, and `process/context/all-context.md` gained a `## Production State` section
plus fixes to every stale "flag OFF" / "head `c4a8f13e07b6`" / "devjulley" claim.

**Archived without re-running gates.** These folders were archived because the code is on main and
running in prod, on the orchestrator's audit verdict — not because each plan's validate-contract
gates were re-executed today. CI is red, so there is no fresh automated proof. Treat "archived" as
"shipped", not "re-verified".

## 5. Lost work

roster-precision (07-08-26): Part A scorer + 44 tests, its plan/SPEC/contract, and the Part B plan
were never committed. No ref, no disk copy. Details and restart rules:
`process/features/visitors-identity/backlog/roster-precision-lost_NOTE_14-11-26.md`.

## 6. Open operator and legal steps

| # | Step | Owner |
|---|---|---|
| 1 | Remove the public `up.railway.app` domain from the Railway service (after `fix/live-security-hardening` is in enforce mode) | operator |
| 2 | Rotate/remove any leftover agentic-commerce env vars from the reverted web integration, if present | operator |
| 3 | Ads: Meta sandbox smoke + Google sandbox smoke before any `ad_audiences_enabled` flip | operator |
| 4 | Leadpipe: revive org + pixel | operator |
| 5 | 5-session US smoke for identity coverage | operator |
| 6 | ip-org: prod ingest + flag flips per the runbook in `ip-org-database_07-08-26/` | operator |
| 7 | Identity co-op K-3: legal re-pin of `coop_terms_version` | legal |
| 8 | Counsel review of public privacy copy (graph-erasure KG-4) | legal |
| 9 | Luật 91/2025 identity-consent review | legal |
| 10 | Social-resolution Phase 4: go / no-go decision | product |

## 7. Large programs not started (or only partly)

| Program | State |
|---|---|
| Browser-capture trust tier | SPEC only, no plan |
| Engage learning agent | Phase 1 shipped (`45b6da0`, flag OFF); Phases 2, 3a, 3b not started |
| Private-beta apply form | Model + migration `d7e2b4c81f93` only; no endpoint, no UI |
| Public canary funnel | `POST /demo/canary` already shipped (`a621edd`); plan not validated and needs reconciling |
| pii-at-rest | Phases 1–2 done; Phase 3+ not started |
| Cross-tenant erasure phase 2 | Not executed; KG-6 / KG-7 open |
| ip-best-selection phase 1 | Not started; contract BLOCKED |
| Identity co-op | 2a shipped; 2b planned; 3 not started |
| Roster ranking | Needs a full redesign (work lost) |
| Privacy-hook `APPROVED:` bypass | Open item in `plans/260811-1632` (outside `process/`) |
| Clerk Playwright auth harness | Not built; blocks e2e legs in privacy-hold-clear, site-id-lifecycle, cadence-bot-flag, ads-audiences |

## 8. Not done in this pass

- `docs/identity-us-current-handoff.md` and `docs/visitor-identity-flow-architecture.md` still
  point at old `active/` paths for archived folders (docs are outside `process/`).
- `browser-capture-trust-tier` has only a SPEC, and SPECs are frozen — no status line was added
  to it; its state is recorded here and in `all-context.md`.
- Phase-level plan files inside multi-phase folders (ads, evallayer, handoff, engage, co-op) keep
  their old per-phase status lines; only the umbrella/main plan of each got the reconciliation
  line.
- Not touched, by instruction (other open PRs are editing them): `seed-verified-tinyfish_25-10-26`,
  `agent-gateway_26-07-26`, the InFlow x402 plan, and the backlog notes on `identity_feedback`
  erasure, social-context purge, graph-erasure cumulative cap, visitor-emails erasure gap, and
  social-context wholesale overwrite.

TL;DR: prod = main at alembic `d3f8a2c61b47` with 10 flags ON; 14 finished folders archived; four
live issues have fix PRs in progress; ten operator/legal steps and eleven larger programs remain.
