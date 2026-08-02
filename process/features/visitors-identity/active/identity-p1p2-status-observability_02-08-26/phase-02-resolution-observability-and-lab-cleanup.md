---
phase: 2
title: Resolution observability and Lab cleanup
status: completed
priority: P2
dependencies:
  - 1
---

# Phase 2: Resolution observability and Lab cleanup

## Overview

Fix paid-graph path that logs `resolution_logs.success=True` before `_save_identified` can reject (name/email). Add a small ops helper/SQL note to demote known Lab false-positives (Janet case) to `provider_candidate` or clear identity.

## Requirements

- Functional: graph waterfall logs success only when IdentifiedVisitor persisted; reject → success=False cost 0 (or skip success log)
- Ops: documented one-shot SQL / script to fix Lab visitor `407a701d-…` (optional run locally)
- Non-functional: no full `identity_observations` table (YAGNI — defer to phase 3 backlog)

## Related Code Files

- Modify: `apps/api/services/identity_resolver.py` — `_resolve_identity_graphs_parallel`
- Create (optional): `scripts/demote_false_positive_identities.py` or NOTE with SQL
- Test: unit covering save-reject → no success ledger / graphs continue

## Implementation Steps

1. In `_resolve_identity_graphs_parallel`: after picking `best_data`, call `_save_identified` first; log success=True only if row returned; on None log success=False cost 0.
2. Avoid double-logging: remove pre-save success log for the winning provider (or rewrite).
3. Add NOTE or script for Lab cleanup: delete IdentifiedVisitor + set visitor anonymous/vpn_filtered for known bad id OR demote status.
4. Unit test: mock save None → log called with success False.

## Success Criteria

- [ ] Name/email reject does not leave success=True resolution_log for that provider
- [ ] Lab cleanup path documented (script or SQL in phase report)
- [ ] Phase 1 tests still green

## Risk Assessment

- Changing log order may affect cost dashboards slightly (correctness > vanity metrics)
