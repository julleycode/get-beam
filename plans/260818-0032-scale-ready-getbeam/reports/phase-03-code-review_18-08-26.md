# Phase 3 code review — tenant ceilings, timeout, x20–x30 runbook

Date: 18-08-26
Reviewer: vc-code-reviewer
Verdict: **PASS_WITH_WARNINGS**
Status: **DONE_WITH_CONCERNS**
Harness: `plans/260818-0032-scale-ready-getbeam/reports/harness/phase-03/`

## TL;DR

Phase 3 blast radius meets acceptance (a)–(i). 429 is before Event INSERT. CF spoof is fail-closed. Defaults stay safe if Railway is forgotten. Phase 2 unique / required `event_id` was not changed. 429 body has no PII. Warnings: IPv6 CIDR `/32` vs live `/29`; ingest background agg and bootstrap lack `SET LOCAL 0`.

## Explicit questions

| # | Question | Answer |
|---|---|---|
| 1 | 429 before INSERT? | **Yes.** `site_ceiling_tripped` at `events.py:354`; INSERT at `:478`. Test: stored rows == number of 204s. |
| 2 | SET LOCAL after COMMIT still in a transaction? | **Yes for retention.** Next `apply_long_job_statement_timeout` autobegins a new txn. Sweep does **not** re-apply after aggregator `commit()` at `visitor_aggregator.py:529`. Heavy SELECT is still inside `SET LOCAL 0`. |
| 3 | CF CIDR stale / empty IPv6? | IPv6 **not empty**. IPv4 matches `ips-v4`. IPv6 slightly stale: `2a06:98c0::/32` vs published `/29`. Fail-closed. |
| 4 | Phase 2 unique / event_id required changed? | **No.** |
| 5 | PII in 429 body? | **No.** Generic retry string. Tests forbid `site_id`, `155`, `limit`. |

## Acceptance

| ID | Result |
|---|---|
| (a) ceiling ON → 429, 0 INSERT; not confused with IP 100/min | PASS |
| (b) origin spoof CF-Connecting-IP ignored unless peer in CF ranges | PASS_WITH_RESIDUAL |
| (c) over-budget killed; sweep 30s cannot kill full recompute | PASS_WITH_RESIDUAL |
| (d) pool comment 15→60; defaults 3/2 | PASS |
| (e) runbook in `docs/deployment-guide.md` | PASS |
| (f) defaults False / 0 if Railway forgotten | PASS |
| (g) no SET leak across pool checkout | PASS |
| (h) velocity P4 still flag-but-store | PASS |
| (i) 204 happy-path when ceiling OFF | PASS |

## High-risk pack

- `review-decision.json`: present (`approved-with-concerns`)
- `adversarial-validation.json`: present
- `risk-gate.json`: present
- `verification.json`: present (static review; pytest not re-run)
- P1/P2 harness: not overwritten
