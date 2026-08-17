---
name: report:ip-best-selection-retrigger-pvl-iteration-003
description: PVL cycle 7 — fresh VALIDATE V1 plus parallel external adversarial verifier; Gate BLOCKED, 16 merged gaps
date: 2026-08-13
metadata:
  node_type: report
  type: pvl-iteration
  iteration: 3
  cycle: 7
  gate: BLOCKED
---

# PVL Iteration 003 — cycle 7

**Plan:** `ip-best-selection-retrigger_PLAN_09-08-26.md`
**Date:** 2026-08-13
**Verdict:** `Gate: BLOCKED`
**Merged gap count:** 16 (validate 5 + verifier 11 net-new)
**Cycle:** 7 of 10 — 3 remain

## Strategy

Two agents in parallel, both opus:

1. `vc-validate-agent` — fresh V1–V7 pass, wrote the validate-contract.
2. External adversarial verifier (general-purpose, default-REFUTED) — compensates for
   `vc-validate-agent` having no Agent tool in this environment, so its designed Layer 1 /
   Layer 2 fan-out cannot run internally. Precedent: the same pairing found the top defect at
   cycles 2 and 6.

Both agents ran under a hardened enumerated STOP block (read-only git; no `results.tsv` write;
no iteration-report write; no self-acceptance of a CONDITIONAL; no self-spawn). No violation
observed in either transcript.

## What cycle 7 CLOSED

Verified against live source on `main` @ `3e2ddb5`, not inherited from prior cycles:

| Claim | Evidence |
|---|---|
| S8's last open gap (agent-company monthly-plan parity) | census run live — zero `check_usage_allowed` / `increment_usage` hits in `agent_company_resolution.py`; donor anchors exact at `resolution_runner.py:161→172→178` |
| Synthetic `agent:{AgentVisit.id}` + `is_agent_derived` — agent lane cannot same-key contend | `agent_company_resolution.py:69`, `:76-81` |
| Cross-AgentVisit reservation correctly disclaimed, not overclaimed | `billing.py:94/140` |
| `force_retry` bypasses exactly one line | `identity_resolver.py:625`; six other gates on separate statements (`:590 :600 :631 :635 :644 :653`) |
| `tracking_enabled` gate vs `b2a7eef` | `resolution_runner.py:260` |
| Defer filter exclusive to automated selection | `resolution_not_deferred_filter()` at `resolution_runner.py:142` / `resolution_tasks.py:91` only |
| `.resolve()` caller census exhaustive | 5 production callers; `demo.py` uses private `_call_*`, `leadpipe_webhook.py:288` uses `_save_identified` |
| Composite FK to plain UNIQUE INDEX + ON DELETE CASCADE viable | **empirically probed** on disposable `postgres:16-alpine`: FK created, parent delete cascaded 1→0, duplicate claim rejected. Container removed. Closes the largest structural risk in S5-2 |
| `uq_visitors_site_visitor` non-partial, valid FK target | `models/visitor.py:18` |

Baselines re-measured: unit **1762 passed / 2 skipped / 0 failed**; scoped Hybrid **11 passed / 0
failed**. Docker + PG 5433 + Redis 6379 all live — **no gate in this plan is environment-blocked.**

## Gaps OPEN after cycle 7

### From `vc-validate-agent` (5)

Root cause F-S4X: **PVL Supplement 4's resolver decision never propagated into the plan body.**
S4-2 (`:2096-2120`) requires the outage branch to never fall through to the terminal reset; live
`identity_resolver.py:762-795` does the opposite. The instruction exists only in supplement prose.

| # | Section | Severity | Gap |
|---|---|---|---|
| G1 | implementation-checklist | FAIL | Phase-03 (`:910-930`) has no step implementing S4-2. Steps 3.1–3.4 cover only auto_retry/override_ip/selected_ip_activity_at/mixins. Hybrid gate `::test_provider_unavailable_defers_through_ramp_and_repeats_cap` asserts it ⇒ guaranteed EXECUTE failure |
| G2 | touchpoints | FAIL | T13 omits S4-4 item 1's required replacement of `test_resolution_deferral_watermark.py::test_past_the_last_step_writes_off_and_resets` (live at `:340`) |
| G3 | public-contracts | FAIL | Outage terminal-state change (write-off → capped 24h re-defer) undisclosed; alters behavior for 4 callers |
| G4 | acceptance-criteria | FAIL | **AC-1 unsatisfiable** — S4-2 is nowhere flag-gated, yet AC-1 promises flag-OFF byte-identical behavior. Rollback row "No code revert needed" (`:1466`) also falsified. **Needs a human either/or decision** |
| G5 | verification-evidence | CONCERN | `tests/integration/test_agent_company_resolution.py` does not exist on disk yet owns two Hybrid gates (S7-4, S8-3); T37 mislabeled, T15 inventory omits it |

Flag-OFF fallout of G4 if left ungated: `revive_returning_unresolvable`
(`visitor_aggregator.py:366`, `:423`) never sees these visitors; manual Retry's `is_retry` branch
(`visitors.py:912`) never fires and silently degrades to `force_retry=False`; a permanently-deferred
population becomes a new steady state.

### From the adversarial verifier (11 net-new)

| # | Sev | Gap |
|---|---|---|
| V1 | **P0** | **New sweep has no monthly-plan gate and no metering.** Every other provider-capable lane calls `check_usage_allowed` + `increment_usage` (`resolution_runner.py:161/176`, `resolution_tasks.py:118`, `visitors.py:953/963`). `check_resolution_attempt_budget` is a per-site DAILY distinct-visitor count — unrelated to `User.monthly_identified_count` vs plan limit. Free tier at 10/10: main sweep and manual both refuse; new sweep dispatches full paid waterfall. On success `increment_usage` is never called ⇒ counter frozen ⇒ silently raises the effective cap for every other lane. **S8 exists to add this exact gate to the lane the plan AUDITED; it was never added to the lane the plan CREATES** |
| V2 | **P0** | **`override_ip` never reaches 3 of 5 mixins.** Plan's "exhaustive" consumption list stops at `_resolve_ip_company_parallel` (`:973`). There are two orchestrators: `_resolve_identity_graphs_parallel` (`:801`, dispatch `:841` `call_fn(visitor)`) carries leadpipe/capturify/rb2b. They default to `visitor.ip_address` — the newest IP, the exact value this plan exists to stop using. Silent (param is defaulted). Visitor burns 4 attempts on one IP at the FIRST waterfall tier — the only tier that resolves residential IPs — while the ledger reports 4 distinct IPs |
| V3 | P1 | **AD-7 ↔ S3-1 unreconciled.** AD-7 (`:549-552`): bypasses "exactly the same line as `force_retry` and nothing else." S3-1 (`:1922-1925`): "skips `_check_prior_signals` completely." Two structurally different edits; `_check_prior_signals` is a separate statement at `:608-612`. Neither marked superseded. Following AD-7 re-runs the cross-tenant graph guess + fingerprint copy on every cycle, violating §Non-Goals |
| V4 | P1 | **`provider_unavailable` consumes budget but stamps nothing ⇒ unbounded.** `:762` ORs across two independent tiers, so a dead person tier flips the whole call even though PDL/IPinfo ran and wrote ledger rows at `:1046`/`:1058`. `usage_limits.py:75-82` counts DISTINCT visitor_id ⇒ budget slot consumed. **This is the current live config** (Leadpipe 403, RB2B 402): ~365 paid dispatches/visitor/year with `auto_reidentify_count` frozen at 0. Both the 4-attempt cap and the `skip_count < 8` bound are structurally unreachable |
| V5 | P1 | **Redis negative cache is cross-tenant.** Key is `resolution:{ip}` (`identity_providers/base.py:16`) — no `site_id`. Site A writes `__none__` for 24h; site B's sweep ranks the same IP (shared NAT/CGNAT), gets served from cache, contacts zero providers, writes zero ledger rows — yet the attempt is counted and the IP blacklisted. Verbatim re-entry of the self-annihilation path AD-6/G2b was written to close |
| V6 | P1 | **D-C `vpn_filtered` Retry button still dead.** `is_privacy_relay_ip` matches only `2a09:bac3:` (iCloud **IPv6**). `events.py:346` already drops proxy/VPN/Tor/hosting at ingest (`is_proxy_or_vpn` deliberately excludes `relay`), so the surviving `vpn_filtered` population is relay-dominated and heavily IPv4 (WARP). AD-11's kill chain stops at `:644` and never reaches the dominant guard at `:653-664`. Click ⇒ same badge + one paid IPinfo call. AD-4 item 2 already discloses the v4 gap; it never propagated 370 lines forward |
| V7 | P1 | **Public Contracts `:175` ↔ S3-1 `:1919` contradict on relay/VPN accounting.** One says attempt counted + `tried_ips` appended; the other says `provider_work_started` is false. AD-8 has no row for this exit; 4.3d pre-checks omit the guard. Under S3-1 the ranker re-picks the same IP every tick |
| V8 | P2 | `auto_reidentify_skip_count` is never reset. A visitor with one IP for 56 days retires at `skip_count = 8` with `count = 0`, then is permanently excluded even when 3 new org-tier IPs appear — exactly the population Goal 2 names |
| V9 | P2 | AD-15 (`:798-799`, orphan preflight "not permitted") ↔ S3-2 (`:1944-1945`, "must preflight"). Neither superseded |
| V10 | P2 | Redis key string written as `beam:resolution:{ip}` at `:629` and `:1606`; live prefix is `resolution:` with no client-side key prefix (`redis_client.py:23-25`). Also: true head on `main` is `f4b9d2a71c68`; AD-13 names only `c4a8f13e07b6` (prod) and a non-conclusive `d3f9a1c25e84`. AD-13's "DERIVE IT LIVE" instruction contains this risk |
| V11 | P2 | Manual retry flips terminal → `anonymous` before `resolve()` (`visitors.py:911-914`). If `check_daily_budget` then refuses, the row is left permanently `anonymous`, silently removed from the new sweep's `identity_status IN ('unresolvable','vpn_filtered')` population with `auto_reidentify_count` frozen. T17 reorders the claim but never addresses the leftover case |

## Claims the verifier attempted and COULD NOT refute (14)

`force_retry` single-branch; 5-caller `.resolve()` census complete; synthetic agent key;
`uq_visitors_site_visitor` non-partial and FK-valid; T29 `main.py` import requirement real;
T16 `_AC2_FILES` tripwire real; T12 scheduler arithmetic 24/21/3 → 25/22/3; `_record_matches_visitor`
two call sites; `_write_through_company_graph` risk mapped and covered; `promotion_sweep_runner`
currently provider-capable and needs the `deterministic_only` barrier; AD-4's own v6-only
disclosure accurate; `is_abuse_flagged` reaches the new path with no new regression;
`RESOLUTION_DEFER_BACKOFF` finite (4 stages); D-B reserve helper signatures exist as cited.

## Convergence assessment

Gap trend across seven cycles: **13 → 14 → 12 → 10 → 4 → 3 → 1 → 16.**

The jump is not plan-quality regression — cycle 6's single S8 gap is genuinely closed and every
S7/S8 claim survived live re-verification. The jump is measurement: six consecutive delta passes
never inspected (a) whether supplement decisions reached the plan body, or (b) claim-vs-claim
consistency between supplements. A fresh V1 plus an adversarial pass inspected both and found
two P0s and four unreconciled internal contradictions.

**Three cycles remain against 16 gaps, including 2 P0 and 4 contradictions that each yield a
different implementation depending on which section an execute-agent reads.** The structural
pattern — a 228KB plan carrying eight supplements where supplement prose and plan body have
measurably diverged — is the risk, not any individual gap.

## Decision required before S9

**G4 is a human call.** Should S4-2's resolver outage change be:

- **(a) flag-gated** on `auto_reidentify_enabled` — preserves AC-1 as written and keeps
  zero-cost rollback; or
- **(b) shipped as a deliberate flag-independent bug fix** — requires AC-1 and the Rollback
  row (`:1466`) to be rewritten.

Both defensible. The plan currently asserts both. The other four validate gaps reference this
decision, so S9 cannot be written coherently until it is made.

## Recommended next action

Not a mechanical S9. See the orchestrator closeout: the options are (1) continue the loop with a
scoped S9, (2) split the plan, or (3) descope to a Phase-1 that excludes the outage/relay/cache
surfaces entirely.

## Coverage limitation

`vc-validate-agent` could not run its designed Layer 1 / Layer 2 parallel fan-out — no Agent tool
in this environment. All dimensions were covered sequentially with live source reads, and the
limitation is recorded in the validate-contract. The external adversarial verifier partially
compensates and is the sole source of all 11 net-new findings above.
