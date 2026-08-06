---
name: pii-backfill-run-evidence
description: Evidence record — Phase-1 PII ciphertext/bidx backfill executed + verified against prod, 07-08-26
date: 2026-08-07
metadata:
  type: report
  plan: pii-at-rest_PLAN_22-07-26.md
---

# Phase-1 Backfill RUN Evidence — 07-08-26

**Operator-run against prod** (Railway env, `railway run -s retarget-agent`, script committed at `be39585`, invoked as module `-m apps.api.scripts.backfill_pii_ciphertext` — file-path invocation fails with `ModuleNotFoundError: apps`, worth a docstring fix).

| Step | Time (+07) | Result |
|---|---|---|
| `--dry-run` (pre) | 06:19 | pending: visitor_emails **4**, identified_visitors **12**, beam_identity_graph **0**, enrichment_profiles **6** |
| Real run | 06:22 | updated **22/22** (4+12+0+6), one batch per table, zero failures, zero no-update stalls |
| `--dry-run` (verify) | 06:25 | **0 pending across all 4 tables** |

**Findings:**
- `beam_identity_graph` had ZERO un-backfilled rows — graph writes used the ciphertext+bidx pattern since inception. The NULL-bidx GDPR-erasure-miss exposure (`graph_erasure.py` `email_bidx == ANY(...)` never matching NULL) had no actually-affected rows; exposure closed with margin.
- Prod schema at head `d1a6c4e93f27` at run time (deployed earlier same day, main @ `f0c95e6`).
- Run Disposition prereq **(a) ✅ satisfied**. Remaining before EXECUTE: (b) Docker Hybrid gates, (c) high-risk evidence pack, (d) PVL refresh from V1 closing READ-census G1.
