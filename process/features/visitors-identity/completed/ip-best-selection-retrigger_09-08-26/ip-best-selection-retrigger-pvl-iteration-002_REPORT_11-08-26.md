---
name: report:ip-best-selection-retrigger-pvl-iteration-002
description: PVL cycle 2 — re-validate (BLOCKED, 2 new FAILs) + supplement applying 10 gaps incl. outage-defer restore, tracking_enabled gate, ND-3/ND-4 verifier defects
date: 11-08-26
feature: visitors-identity
metadata:
  node_type: memory
  type: report
  phase: pvl-iteration-002
---

# PVL iteration 002 — ip-best-selection-retrigger (11-08-26)

## Cycle shape

- Re-validate from V1 (vc-validate-agent, sequential — no Agent tool) + INDEPENDENT external adversarial verifier in parallel, per the two-leg pattern that found the top defect in the 2 prior cycles of this repo.
- Verdict: **Gate: BLOCKED** — all 4 cycle-1 FAILs verified CLOSED against live source; 2 NEW FAILs + 8 CONCERNs (validate) + 3 additional defects (verifier only: ND-3, ND-4, ND-5≡C8).
- Both legs independently found the same 2 headline FAILs (F5≡ND-1 outage-defer permanent stranding; F6≡ND-2 missing `Site.tracking_enabled` gate vs commit `b2a7eef`'s auto-pause spend-stop) — high-confidence findings.

## Supplement (same day)

10 gaps applied by vc-plan-agent (supplement mode), validator 0 fail / 0 warn, plan now 1637 lines:

- F5/ND-1: sweep restores `resolution_defer_count=0` + `deferred_until=None` on the outage branch (fix shape (a), orchestrator-decided); `expire_on_commit=False` after-read pinned; E6 pairing instruction; gate `::deferred_visitor_re_enters_sweep_after_outage_clears`; R7 for the pre-existing stranded population.
- F6/ND-2: `Site.tracking_enabled IS true` in AD-6 + gate `::paused_site_never_swept` + AC-10b, citing `resolution_runner.py:252-261` (commit `b2a7eef` — contract's `b2aa7ef` was a typo).
- ND-3: D-C manual-retry predicate narrowed to current-IP-non-relay; full override_ip manual leg stubbed at `backlog/manual-retry-override-ip_NOTE_11-08-26.md`; R8.
- ND-4: T21 `schemas/sites.py` + T22 `routers/sites.py` touchpoints (blast radius 22→24 files) with do-not-touch-`auto_paused_at` warning.
- C7 scheduler arithmetic re-derive (live 24/21/3 → target 25/22/3); C8 four-columns reconciled at all 5 sites; C9 ORDER BY reconciled to **NULLS FIRST** per AD-1; C10 2-params restated ×3; C12 new E5 (~13 wrong-IP log sites); C13 reserve check moved per-visitor (true 70% ceiling, gate seeds at 69%).

## Next

Re-validate cycle 3 from V1 (+ external verifier). EXECUTE remains NOT authorised until a terminal verdict.
