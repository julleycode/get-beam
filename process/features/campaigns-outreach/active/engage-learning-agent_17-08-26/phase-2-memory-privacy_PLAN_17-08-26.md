---
name: plan:engage-learning-agent-phase-2-memory-privacy
description: "Engage Learning Agent — Phase 2: three-scope memory + privacy (erasable per-contact memory via enqueue-time blind index, computed track record + mounted router, third consent flag and k>=5 cross-tenant aggregates)"
date: 17-08-26
feature: campaigns-outreach
metadata:
  node_type: memory
  type: plan
  feature: campaigns-outreach
  phase: phase-2
---

# Phase 2 — Memory + Privacy

**Date**: 17-08-26
**Complexity**: COMPLEX
**Status**: ⏳ PLANNED
**Program:** engage-learning-agent
**Umbrella plan:** `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/engage-learning-agent-umbrella_PLAN_17-08-26.md`
**Report destination:** `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-2-memory-privacy_REPORT_17-08-26.md`
**Covers SPEC ACs:** AC-5, AC-6, AC-7, AC-8, AC-9, AC-10
**Supplement revision:** PVL cycle 3 supplement applied 17-08-26 — closes F3-1, F3-2, F3-3 (FAIL) and C3-1…C3-6 (CONCERN). Prior: cycle 2 supplement applied 17-08-26 — closes F2-1, F2-2 (FAIL) and C2-1…C2-4 (CONCERN), and absorbs `contact_bidx` from Phase 1 per N5/N6. All five cycle-1 FAILs were independently re-derived against real source and confirmed closed by the cycle-2 validator.

**TL;DR:** Turn Phase 1's outcomes into memory at three scopes — per-contact (encrypted, gated, and
erasable via a key collected at ENQUEUE time, mirroring the existing `fingerprint_list` design),
per-site/playbook (computed live, never materialized), and cross-tenant (own consent flag, k≥5, no
deltas, no PII) — and mount the surface that shows the owner the track record Phase 3b's gate reads.

---

## Inner Loop Refresh Note

**17-08-26 — PVL cycle 3 supplement (BLOCKED → supplement).** Every cycle-3 finding was a
propagation failure of the cycle-2 `contact_bidx` absorption: the package was accepted into this
phase but its consequences were not carried into the Entry Gate, the erasure dispatch, the migration
backfill, the touchpoints, or the gate lists. Sections amended: Entry Gate, Touchpoints, Blast
Radius, Steps A5b/B1/B5/B6/D3, Acceptance Criteria, Phase Completion Rules, Verification Evidence,
Test Procedure. Drivers: FAILs **F3-1** (the Entry Gate demanded the very column this phase creates —
an EXECUTE agent trusting it would have skipped A2b entirely), **F3-2** (`"engage_outcomes"` got a
target-list entry but no dispatch branch or delete stmt — the F-B1 silent no-op reproduced for the
newly absorbed table), **F3-3** (the migration backfill covered only one of the two new targets);
CONCERNs C3-1…C3-6.

**17-08-26 — PVL cycle 2 supplement (superseded above, retained for audit).** Sections amended: Overview, Touchpoints,
Public Contracts, Blast Radius, Implementation Checklist (Steps A, B, D, F), Verification Evidence,
Test Procedure, Blockers, Exit Gate. Drivers: validator FAILs F2-1 (the `if bidx or fps:` guard is
not widened, so an author-bidx-only request deletes nothing) and F2-2 (the enqueue-side derivation is
unnamed, so the two key spaces can silently diverge); CONCERNs C2-1…C2-4; and the N5/N6 transfer of
`contact_bidx` from Phase 1 into this phase.

**17-08-26 — PVL cycle 1 supplement (superseded above, retained for audit).** Sections amended: Overview (the factually
wrong erasure premise corrected), Touchpoints, Public Contracts, Blast Radius, Implementation Checklist
(Steps A–F, all rewritten), Acceptance Criteria, Verification Evidence, Test Procedure, Test Infra
Improvement Notes, Blockers, Exit Gate. Drivers: validator FAILs F-B1…F-E1, CONCERNs C-A1…C-OV1,
adversarial findings V2 (unowned surfaces) and V8 (no erasure join carrier), and orchestrator decisions
D-O3, D-O4, D-O7, D-O8.

---

## Overview / Context and Goals

Phase 1 records what happened. Phase 2 makes it *memory* without creating a new class of un-erasable
PII or a cross-tenant leak.

Three precedents govern this phase and must be followed rather than reinvented:

- `apps/api/services/identity_signals.py` — the gates-then-silent-skip write pattern.
- `apps/api/services/campaign_benchmark.py` — k-floor, sub-floor writes no row, non-consenting leaves
  no trace, no deltas ever, `normalize_category` reuse.
- **`ErasureRequest.fingerprint_list` (`models/erasure_request.py:68`) +
  `graph_erasure._collect_match_keys` (`graph_erasure.py:122`) — the enqueue-time match-key carrier.**
  This is the working precedent the social key must copy verbatim.

**Corrected premise (C-OV1).** An earlier draft of this plan claimed "the erasure sweep matches on the
email blind index only." That is **wrong**: `_graph_delete_stmt` already matches `email_bidx` OR
`fingerprint` OR `fingerprint_v3` via a `fingerprint_list` ARRAY column collected at enqueue; only
`_identity_signals_delete_stmt` is email-bidx-only. The correction matters because it identifies the
exact design to copy for the social key (D-O7).

**Why a sweep-time join is impossible (F-B2 / V8).** `routers/visitors.py:449-465` deletes
`identified_visitors` and `enrichment_profiles` **synchronously during the erasure request**, and
`_collect_match_keys` carries an explicit "ORDERING-CRITICAL: this MUST run before the caller's DELETE
loop" contract for exactly this reason. By sweep time the join source no longer exists. The key must be
collected at enqueue and persisted on the request row.

**Why tuple membership is not enough (F-B1).** `graph_erasure._process_claimed` (lines 387–396)
dispatches with a hardcoded `if target == "beam_identity_graph" / elif target == "identity_signals" /
else logger.warning("erasure_unknown_target")`. Adding a name to `ERASURE_TARGETS` without a matching
`elif` deletes ZERO rows while the request still commits `status="done"` — the icp_fit silent-no-op
class this program's charter bans.

One anti-pattern is explicitly avoided: the per-site/playbook track record is **computed at read/gate
time** from `engage_outcomes`, not materialized into a stats table.

Context loaded: `process/context/all-context.md`, `process/context/tests/all-tests.md`.

### Binding join rule inherited from Phase 1 (Q6)

`Draft.site_id` is `String(50)` referencing `sites.site_id` — the **slug**, not the UUID PK.
`engage_outcomes.site_id`, `engage_contact_memory.site_id`, and every aggregate in this phase carry
that same slug and join to `sites.site_id` directly, never to `sites.id`.

### Goals

1. Per-contact memory that is encrypted, gated, and **provably** erasable end-to-end (AC-5, AC-7).
2. Facts-and-timestamps only across outcome AND memory records (AC-6).
3. Owner-visible per-playbook track record on a **mounted** router (AC-8).
4. A third, dedicated cross-tenant consent flag (AC-9) and a k≥5 aggregate with no trace, no deltas,
   no PII (AC-10).

### Non-goals

Strategy selection and the pure autonomy gate belong to Phase 3a; the send path, the enum and the rails belong to Phase 3b. Neither is in this phase.

---

## Entry Gate

- Phase 1 exit gate met. **Mechanical check, not prose:**
  `.venv/bin/python3.11 -c "from apps.api.models.engage_outcome import EngageOutcome; print(EngageOutcome.__table__.c.keys())"`
  must succeed and list **`site_id` and `platform_ref` ONLY**.
  **(F3-1) `contact_bidx` is ABSENT BY DESIGN at this point and its absence is NOT a Phase 1 failure.**
  Phase 1 deliberately ships `engage_outcomes` without it (N5/N6); **this phase adds it in item A2b**
  together with its erasure registration. An entry gate that demanded the column could never pass, and
  an EXECUTE agent trusting it would conclude Phase 1 owed the column and skip A2b — silently dropping
  the entire absorbed package.
- Live alembic head re-derived at EXECUTE time (Phase 1's migration is now in the chain), DSN pinned
  per D-O10.
- Integration infra reachable: `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`.

---

## Touchpoints

**Owned exclusively by Phase 2:**

- `apps/api/models/engage_contact_memory.py` — NEW per-contact memory model.
- `apps/api/models/engage_benchmark.py` — NEW cross-tenant aggregate model.
- `apps/api/services/engage_memory.py` — NEW; `record_engage_outcome()`, the SINGLE write choke point.
- `apps/api/services/engage_track_record.py` — NEW; computed per-site/playbook stats (no table).
- `apps/api/services/engage_benchmark.py` — NEW; k-anonymous cross-tenant aggregation.
- `apps/api/models/erasure_request.py` — adds `"engage_contact_memory"` to `ERASURE_TARGETS` **and** the
  new `author_bidx_list` ARRAY column (F-B3).
- `apps/api/services/graph_erasure.py` — `_collect_match_keys` collection, `_claim_next` select
  extension, `_engage_memory_delete_stmt`, and the `elif` dispatch branch (F-B1, F-B2, D-O7).
- `apps/api/services/pii_crypto.py` — adds a generic `blind_index(value: str) -> str` (C-A1).
- `apps/api/models/engage_outcome.py` — **(C3-1) SHARED-with-rule.** Phase 1 authors the table; Phase 2
  appends EXACTLY ONE column (`contact_bidx`, item A2b) and touches nothing else in the file.
- `apps/api/routers/engagement.py` — the track-record read endpoint is added to the **already-mounted**
  `engagement` router (F-D1). No new router file, no new mount.
- `apps/api/schemas/engage.py` — NEW response models for the track-record endpoint.
- `apps/web/src/lib/api.ts` + `apps/web/src/app/dashboard/**` engage **track-record** surfaces only
  (D-O4 web split — Phase 3b owns the drafts page, status badge, draft card, and the `DraftStatus` union).
- `apps/api/migrations/versions/<new>_add_engage_memory.py` — NEW migration.
- `tests/unit/test_engage_memory_schema.py`, `tests/integration/test_engage_memory_privacy.py`,
  `tests/integration/test_engage_benchmark.py` — NEW.

**Shared, with binding rules:**

- `apps/api/models/site.py` — adds `engage_learning_contribution_enabled` ONLY (Phase 3b owns
  `engage_autonomy_enabled`).
- `apps/api/jobs/scheduler.py` — SHARED-append-only (D-O3, resolves F-E1). Phase 2 appends ONLY its own
  `engage_benchmark_aggregate` job id, with literal `jitter` + `misfire_grace_time`.
- `tests/unit/test_scheduler_job_config.py` — SHARED. **(C3-6)** Re-derive the inventory counts from the live `tests/unit/test_scheduler_job_config.py` at EXECUTE time and update them to the re-derived values; never trust the numbers written in this plan. Never relax the assertion.
- `apps/api/main.py` — SHARED-append-only: `# noqa: F401` registration imports for the two new models.
- `apps/api/config.py` — appends the `# ─── Engage memory (Phase 2) ───` block only.

---

## Public Contracts

- `ERASURE_TARGETS` gains one entry — additive; existing targets keep working (regression-gated).
- `erasure_requests` gains one nullable ARRAY column `author_bidx_list`. Existing rows and existing
  sweep behavior are unaffected (the new delete stmt is skipped when the array is NULL/empty).
- `Site` gains ONE new boolean column, default False, `server_default="false"`.
- New tenant-scoped read endpoint `GET /api/v1/engagement/{site_id}/track-record` on the EXISTING
  mounted router; every query filters through `Site.user_id == user.id`; unknown/foreign ids return
  404, never 403.
- `pii_crypto` gains a generic `blind_index()` — purely additive; `email_hash()` behavior unchanged.
- No change to `sender.py`, `DraftStatus`, `is_emailable_identity()`, or any visitor schema.
- Cross-tenant payloads carry NO tenant identifier, NO contact PII, NO reply text.

---

## Blast Radius

- **NEW (9):** 2 models, 3 services, 1 schemas module, 1 migration, 3 test files.
- **EDITED (9):** `models/erasure_request.py`, `services/graph_erasure.py`, `services/pii_crypto.py`,
  `routers/engagement.py`, `models/site.py`, `jobs/scheduler.py`,
  `tests/unit/test_scheduler_job_config.py`, `apps/api/main.py`, `apps/api/config.py`, plus the web
  track-record surface (`apps/web/src/lib/api.ts` + 1 dashboard component).
- 2 new tables (`engage_contact_memory`, `engage_benchmarks`); 1 new `Site` column; 1 new
  `erasure_requests` column.
- Risk class: **PII / trust boundary** (per-contact memory) + **cross-tenant data flow** + **schema
  migration on an EXISTING GDPR table**. All require at minimum a Hybrid gate; **no known-gap is
  acceptable for AC-5, AC-7, AC-9, or AC-10.**

---

## Implementation Checklist

### Step A — Schema and models (AC-5, AC-6)

- [ ] A0. **(C-A1)** Add `blind_index(value: str) -> str` to `apps/api/services/pii_crypto.py` — HMAC over
  the raw value using the same `_hmac_key()`, WITHOUT `normalize_email` (which `email_hash` applies).
  `email_hash` stays untouched. Unit-gate that `blind_index` and `email_hash` agree on a normalized
  email input so the two key spaces are reconcilable.
- [ ] A1. Create `apps/api/models/engage_contact_memory.py`: `id` UUID PK; `site_id` FK (site-scoped);
  `platform` enum; `author_bidx` String = `blind_index(f"{platform}:{author_identifier}")`;
  `handle_ciphertext` (ciphertext ONLY — never plaintext); `email_bidx` String **nullable**
  (**D-O7 second erasure match path**, populated when the contact is identity-linked);
  `fact_kind` String(32) from a closed vocabulary; numeric/boolean fact fields; `last_observed_at`;
  `created_at`/`updated_at`. **No third-party body/text column may exist.**
- [ ] A1b. **(C-A2) Name the `author_identifier` source and its limit explicitly.** The only social
  identifiers stored in this repo are `Post.author_username` and `EnrichmentProfile.twitter_handle` —
  both MUTABLE handles. Therefore: `author_identifier = Post.author_username`, and **handle-rename
  drift is a documented known limit** (after a rename the old blind index stops matching, so an erasure
  request may miss pre-rename rows). Record it in the module docstring AND as a backlog stub. Do not
  let a test suite that always uses a stable handle imply otherwise.
- [ ] A2. Unique index on `(site_id, platform, author_bidx, fact_kind)`; index on `author_bidx` alone
  and on `email_bidx` alone so the erasure sweep can match without a site filter.
- [ ] A2b. **(N5/N6 transfer from Phase 1) Add `engage_outcomes.contact_bidx`.** Phase 1 deliberately
  ships `engage_outcomes` WITHOUT this column because the `blind_index()` helper (A0) and the whole
  erasure machinery are Phase-2-owned — adding it in Phase 1 would have been a circular dependency
  AND un-erasable PII. Phase 2 therefore adds, in ONE change: (i) nullable `contact_bidx` String on
  `engage_outcomes`, derived from `Post.author_username` via the SAME `blind_index(f"{platform}:{handle}")`
  derivation and the SAME platform literal as A1/B2b — **for NEW rows only. `contact_bidx` is NEVER
  backfilled onto existing `engage_outcomes` rows (F3-3):** minting a fresh blind index for a person
  whose erasure request already completed would re-create erased PII. Historical rows keep
  `contact_bidx = NULL` and are simply excluded from DISTINCT-contact counting;
  (ii) the column in this phase's migration;
  (iii) `"engage_outcomes"` added to `ERASURE_TARGETS` with its own `elif` dispatch branch and delete
  stmt alongside the memory table's (B1/B5/B6 cover both tables). No PII-derived column ships without
  an erasure path in the same phase — that is the umbrella's hard constraint.
  Phase 3a's DISTINCT-contact positive-rate depends on this item.
- [ ] A3. Create `apps/api/models/engage_benchmark.py` mirroring `campaign_benchmark`: normalized
  category, strategy, pooled counts, `contributing_site_count`, period bounds. **No tenant identifier
  column.**
- [ ] A4. Add `Site.engage_learning_contribution_enabled: Mapped[bool]` default False,
  `server_default="false"`, nullable=False.
- [ ] A4b. **(F-B3)** Add `ErasureRequest.author_bidx_list: Mapped[list[str] | None]` ARRAY column,
  mirroring `fingerprint_list` (`erasure_request.py:68`) exactly — same nullability, same ARRAY type.
- [ ] A5. **(F-B3 + N5/N6)** The migration covers FIVE objects: the 2 new tables, the `Site` column,
  the `erasure_requests.author_bidx_list` ALTER, **and the `engage_outcomes.contact_bidx` ALTER (A2b)**. Re-derive the live head; never hardcode
  `down_revision`; pin the DSN per D-O10.
- [ ] A5b. **(C-B4) `targets` snapshot decision — recorded, not left open.** `ErasureRequest.targets`
  defaults to `list(ERASURE_TARGETS)` at ENQUEUE, so requests enqueued before this phase ships but
  drained after would never erase memory rows. **Decision: backfill.** The migration sets
  **(F3-3) `targets = targets || '{engage_contact_memory,engage_outcomes}'`** — BOTH new target names,
  for all rows with `status IN ('pending','processing')`. Backfilling only one leaves every in-flight
  request erasing memory rows but never unlinking `engage_outcomes.contact_bidx`: a permanent GDPR miss
  for exactly the requests open during the deploy. F4d asserts both.
  Rows already `done`/`failed` are left alone (they predate any memory row, so there is nothing to erase).
  Gate this in the migration round-trip test.
- [ ] A6. Live round-trip up → down → up against a **disposable** `postgres:16-alpine` container.
- [ ] A7. Add `# noqa: F401 — register for create_all` imports for both new models to `apps/api/main.py`
  (E2 — the integration lane's only table-registration mechanism, `tests/conftest.py:123`).

### Step B — Erasure: enqueue-time key + dispatch branch (AC-5) — the F-B1/F-B2 fix

Implement the `fingerprint_list` design **verbatim** (D-O7). Four coordinated edits, none optional:

- [ ] B1. **(F3-2) Add BOTH new targets to `ERASURE_TARGETS`:** `"engage_contact_memory"` AND
  `"engage_outcomes"`. A2b registers the second one; B5/B6 below must cover it too, or the sweep hits
  the `else` at `graph_erasure.py:395-396`, logs `erasure_unknown_target`, deletes nothing, and commits
  `status="done"`.
- [ ] B2. **Collect at ENQUEUE, never at sweep time.** In `graph_erasure._collect_match_keys`
  (`graph_erasure.py:122`), additionally collect the contact's `author_bidx` values (and `email_bidx`
  where identity-linked) for the visitor being erased. This MUST run before the caller's synchronous
  DELETE loop — the function already carries that ORDERING-CRITICAL contract.
- [ ] B2b. **(F2-2) Pin the reverse derivation EXACTLY — key-space divergence is silent and total.**
  The enqueue path is: visitor → `EnrichmentProfile.twitter_handle` (`enrichment.py:31`) →
  `blind_index(f"{platform}:{handle}")`. **The `platform` token MUST be the byte-identical literal the
  write side uses in A1.** If the write side emits `twitter:jdoe` and enqueue emits `x:jdoe`, nothing
  ever matches, every erasure silently misses, and `status="done"` is still written. Define the
  literal ONCE as a module constant and import it on both sides — do not spell it twice.
- [ ] B2c. **(C2-4) LinkedIn scope, stated.** `EnrichmentProfile` stores `linkedin_url`, not a
  LinkedIn handle, so there is no symmetric derivation. **v1 social-key erasure covers X/Twitter
  only.** Record a backlog stub for LinkedIn social-key erasure; do not silently imply coverage.
- [ ] B3. Persist them: `graph_erasure.py:212` already writes `fingerprint_list=fingerprints or None`;
  add `author_bidx_list=author_bidxs or None` alongside.
- [ ] B4. **(C2-1) Extend `_claim_next` — ordering is load-bearing.** The RETURNING clause
  (`graph_erasure.py:302-306`) currently returns `(id, attempts, email_bidx_list, fingerprint_list,
  targets)` and the claimed dict reads `claimed[4]` for `targets`. **Append `author_bidx_list` AFTER
  `targets` and read it as `claimed[5]`.** Inserting it before `targets` silently breaks `claimed[4]`
  and every erasure loses its target list.
- [ ] B5. Add `_engage_memory_delete_stmt` matching `author_bidx = func.any(:author_bidx_list)` OR
  `email_bidx = func.any(:email_bidx_list)` — mirroring how `_graph_delete_stmt`
  (**`graph_erasure.py:347-358`** — C2-3 citation fix; `:378` is `fps = claimed["fingerprint_list"]`
  inside `_process_claimed`) consumes `fingerprint_list`.
- [ ] B5b. **(F3-2) Add the SECOND delete statement — `_engage_outcomes_unlink_stmt`.** Semantics
  differ deliberately from the memory table: `engage_outcomes` rows are non-PII analytics facts whose
  only PII-derived field is `contact_bidx`, and deleting them would destroy the track records Phase 3a/3b
  depend on. So the erasure action is an **UNLINK, not a delete**:
  `UPDATE engage_outcomes SET contact_bidx = NULL WHERE contact_bidx = ANY(:author_bidxs)`.
  **This is CROSS-TENANT by design** — the sweep ignores `source_site_id` throughout (that is why it
  exists), so the unlink applies to every tenant's rows for that person. Stated deliberately, not
  inherited by accident. Row deletion remains the action for `engage_contact_memory`.
- [ ] B5c. **(F2-1; renumbered from a duplicate B5b at cycle-4 C4-1) Widen the outer dispatch guard — this is a separate defect one level up from B6.**
  `graph_erasure.py:380` gates the ENTIRE dispatch block (tombstone + the whole
  `for target in claimed["targets"]` loop) on `if bidx or fps:`. A request carrying a populated
  `author_bidx_list` but an EMPTY `email_bidx_list` and EMPTY `fingerprint_list` skips the block
  entirely and still commits `status="done"` at `:398` — the exact silent-no-op class B6 exists to
  prevent, reproduced in the enclosing function. Change to `if bidx or fps or author_bidxs:`.
  **Without this, the whole redesign is defeated for precisely the contacts it protects** — social
  contacts with no email link, which C2c itself calls "the majority social case".
- [ ] B6. **(F3-2) Add TWO dispatch branches to `_process_claimed`** (lines 387–396):
  `elif target == "engage_contact_memory"` → `_engage_memory_delete_stmt`, and
  `elif target == "engage_outcomes"` → `_engage_outcomes_unlink_stmt`. A target registered in B1 with no
  matching branch falls to the `else` at `:395-396`, logs `erasure_unknown_target`, deletes nothing, and
  still commits `status="done"` — and F4b/F4h would then fail at EXECUTE, meaning the plan would have
  instructed EXECUTE to build something that cannot pass its own gate.
- [ ] B7. Regression: existing `beam_identity_graph` + `identity_signals` erasure behavior unchanged.

### Step C — The write choke point (AC-7)

- [ ] C1. Create `apps/api/services/engage_memory.py` with `record_engage_outcome(db, …) -> bool`,
  mirroring `identity_signals.record_signal()`: evaluate gates FIRST, then silently skip (return False) —
  never raise, never partially write.
- [ ] C2. **(C-C1) Suppression gate — exact call named:**
  `is_email_suppressed_any(db, email, ("do_not_email", "erased"))`
  (`suppression.py:28`; `VALID_SCOPES = {"all","do_not_sell","do_not_process","do_not_email","erased"}`).
  The `"erased"` scope is mandatory: an erased person must never re-accrue memory. The single-scope
  `is_email_suppressed(db, email, scope)` is NOT sufficient.
- [ ] C2b. **(C-C2) Contact → email join — defined, not asserted.** Path:
  `Post.author_username` → `EnrichmentProfile.twitter_handle` (`models/enrichment.py:31`, **non-unique**)
  → the linked visitor's email. Because the handle column is non-unique, a multi-row match is treated as
  **unresolvable → fail-closed (no memory row written)**, never as "pick the first".
- [ ] C2c. **Unlinkable contacts (the majority social case) FAIL CLOSED for the suppression gate**: no
  email link ⇒ suppression cannot be evaluated ⇒ no memory row. Record this as a documented coverage
  limit; it is the safe direction and keeps AC-7 non-vacuous.
- [ ] C3. Gate order: (a) suppression per C2/C2b/C2c; (b) `do_not_resolve` sticky on the visitor record;
  (c) `engage_memory_enabled` flag ON. Blocked → **write nothing at all**, not even a skipped-contact
  counter (privacy invariant: leave no trace).
- [ ] C4. This function is the ONLY code path that writes `engage_contact_memory`. Add a structural
  grep gate asserting no other module performs an insert/add/merge on the model.
- [ ] C5. `engage_outcomes` (non-PII, Beam's own post facts) stay gated by flag only — they do NOT pass
  through these contact gates.
- [ ] C6. **(C-E2)** Config block declares BOTH `engage_memory_enabled: bool = False` **and**
  `engage_benchmark_enabled: bool = False` (the `campaign_benchmark` precedent has its own flag).

### Step D — Computed site/playbook track record (AC-8)

- [ ] D1. Create `apps/api/services/engage_track_record.py` with `compute_track_record(db, site_id, …)` —
  a `GROUP BY site_id, strategy` aggregate over `engage_outcomes`, computed at read/gate time. **No
  materialized stats table, no bulk write.** Uses `ix_engage_outcomes_site_strategy_created`.
  `playbook == Draft.strategy` (pinned in Phase 1 A2). **Rows with NULL `site_id` are excluded**
  (Phase 1 A1c fail-closed).
- [ ] D2. Return sends, replies-back, positive-outcome count, positive rate, and sample size per
  strategy. **Positive = `reply_received` OR `attributed_visit`** (likes alone are never positive).
  Define this ONCE here; Phase 3a imports it rather than redefining it.
- [ ] D3. **(D-O8)** Positive-rate uses DISTINCT-CONTACT counting over `engage_outcomes.contact_bidx`
  — **(C3-2) the column THIS phase adds in item A2b**, not Phase 1 (cycle-2 moved it here with its
  erasure registration). Rows with NULL `contact_bidx` are counted in the
  denominator but cannot contribute more than one distinct contact — document the resulting slight
  conservatism.
- [ ] D3b. **(D-O8) Segment dimension DROPPED from v1.** Gate keying is **playbook × site only**. No
  segment data source exists anywhere in the repo. Record as an explicit **SPEC deviation known-gap**
  with a backlog stub; Phase 3a's gate and Phase 3b's driver key the same way.
- [ ] D4. **(F-D1 + C2-2)** Add `GET /api/v1/engagement/{site_id}/track-record` to the EXISTING
  `apps/api/routers/engagement.py` (already mounted at `main.py:559`). **Do NOT create
  `routers/engage.py`** — it would need a new mount that no checklist item provides.
  **Tenant-scope via `apps.api.dependencies.verify_site_access` (`dependencies.py:30`)** — it returns
  the Site or raises 404 (never 403), exactly matching this plan's Public Contracts claim.
  `routers/engagement.py` imports only `get_current_user` today and has NO site-access check of its
  own (`/track` even accepts an unverified body `site_id`), so the helper must be imported explicitly.
- [ ] D4b. Add response models to `apps/api/schemas/engage.py`.
- [ ] D5. Add `api.getEngageTrackRecord` in `apps/web/src/lib/api.ts` and render a per-playbook
  track-record panel in the dashboard engage surface. This UI ships in Phase 2 — **before** Phase 3b's
  gate — so the owner can always see the evidence that will later authorize autonomy.

### Step E — Cross-tenant learning (AC-9, AC-10)

- [ ] E1. Create `apps/api/services/engage_benchmark.py` replicating `campaign_benchmark.py` posture:
  reuse `normalize_category`; `ENGAGE_BENCHMARK_K_FLOOR = 5`; a category pooling <5 distinct consenting
  sites produces NO row (discarded, never a suppressed/partial row).
- [ ] E2. Consent basis is the NEW flag ONLY. A site with `contribution_enabled` and/or
  `benchmark_contribution_enabled` ON but `engage_learning_contribution_enabled` OFF contributes nothing.
- [ ] E3. Non-consenting sites' rows are NEVER FETCHED. No skipped-site counter, no keyed trace anywhere.
- [ ] E4. No period-over-period delta is computed or exposed anywhere in the module.
- [ ] E5. The cross-boundary payload structurally contains no contact PII, no tenant identifier, no reply
  text — assert on the model's column set, not on a sample row.
- [ ] E6. **(F-E1/D-O3)** Register `engage_benchmark_aggregate` in `apps/api/jobs/scheduler.py`
  **append-only, own job id only** — this is now licensed by the umbrella registry
  (scheduler.py is SHARED-append-only across all three phases). Literal `jitter` +
  `misfire_grace_time`; advisory-locked with a NEW unique `_LOCK_KEY`; gated on
  `engage_benchmark_enabled`; short-circuits when no site consents.
- [ ] E7. Re-derive `tests/unit/test_scheduler_job_config.py` inventory counts in the same change
  (read the live values first — do not trust a number written here).

### Step F — Tests

- [ ] F1. `tests/unit/test_engage_memory_schema.py::test_engage_memory_schema_has_no_third_party_body_field`
  (AC-6) — structural column-set assertion over BOTH `engage_contact_memory` and `engage_outcomes`.
- [ ] F2. `…::test_erasure_targets_includes_engage_memory` (AC-5). **Marked in-file as necessary-but-not-
  sufficient** — it proves tuple membership only; F4/F4b prove deletion.
- [ ] F2b. `…::test_blind_index_helper_agrees_with_email_hash_on_normalized_input` (C-A1).
- [ ] F3. `…::test_cross_tenant_payload_contains_no_pii_fields` (AC-10).
- [ ] F4. `tests/integration/test_engage_memory_privacy.py::test_erasure_sweep_deletes_engage_memory`
  (AC-5) — non-vacuous control row survives.
- [ ] F4b. **(E4/F-B1) `…::test_erasure_sweep_never_logs_unknown_target`** — assert BOTH that the target
  row is gone AND that `erasure_unknown_target` was NOT logged. A `status="done"` request that deleted
  nothing must FAIL this test.
- [ ] F4c. `…::test_erasure_matches_via_enqueue_collected_author_bidx` (F-B2) — the request row carries a
  populated `author_bidx_list`; the identified-visitor join source is deleted BEFORE the sweep runs;
  the memory row is still erased.
- [ ] F4d. **(C-B4/A5b + cycle-4 C4-2)** `…::test_pending_request_backfill_erases_memory_and_unlinks_outcomes`
  — a request enqueued with the OLD `targets` list, backfilled by the migration, must prove BOTH halves:
  (i) the `engage_contact_memory` row is **erased**, AND (ii) the `engage_outcomes.contact_bidx` is
  **unlinked** (set NULL, row surviving). A5b and the Verification Evidence row both claim "asserts
  BOTH"; the earlier F4d text asserted only the memory half, so the claim was not honored at the
  referenced item — the same failure mode that produced cycle-3's F3-2.
- [ ] F4e. **(F2-1)** `…::test_erasure_deletes_memory_for_author_bidx_only_request` — a request whose
  ONLY match key is `author_bidx_list` (empty `email_bidx_list`, empty `fingerprint_list`) still
  erases. This is the majority social case and is currently dead code behind the `:380` guard.
- [ ] F4f. **(F2-2)** `tests/unit/test_engage_memory_schema.py::test_write_and_enqueue_derivations_agree`
  — for a fixed `(platform, handle)` pair, the write-side key (A1) and the enqueue-side key (B2b) are
  byte-identical.
- [ ] F4g. **(F2-2)** F4 and F4c MUST seed the memory row through the production write path
  `record_engage_outcome()` — NOT by constructing the ORM object directly. A hand-built fixture would
  pass while production silently fails on a key-space mismatch.
- [ ] F4h. **(N5/N6 + cycle-4 F4-1)** `…::test_erasure_unlinks_engage_outcomes_contact_bidx` — the
  erasure action for this table is an **UNLINK, not a delete** (B5b), so the gate name and its assertions
  must say unlink. The old name (`…_deletes_…`) was actively dangerous: test names drive
  implementations, so EXECUTE would likely have written a DELETE to satisfy it — destroying the
  analytics rows Phase 3a/3b track records depend on, while the gate went green.
  Assert ALL FOUR:
  1. the `engage_outcomes` row **still exists** after the sweep;
  2. its `contact_bidx` **IS NULL**;
  3. its non-PII columns (`outcome_type`, counts, `platform_ref`, `observed_at`) are **unchanged**;
  4. a **control contact's** `contact_bidx` on a different row is **untouched**.
  Without 1, 3 and 4 the gate passes vacuously against a table that was never written to.
- [ ] F5. `…::test_inbound_reply_body_not_persisted` (AC-6) — distinctive body string in zero DB columns
  across both tables.
- [ ] F6. `…::test_memory_write_gates_do_not_resolve_and_suppression` (AC-7) — non-vacuous: an identical
  un-held control contact in the SAME test must accrue a row.
- [ ] F6b. `…::test_erased_scope_blocks_memory_accrual` (C-C1) — a contact suppressed under `"erased"`
  (not `"do_not_email"`) accrues nothing.
- [ ] F6c. `…::test_unlinkable_contact_fails_closed` (C-C2c) — no email link ⇒ no memory row.
- [ ] F7. `…::test_site_playbook_track_record_matches_seeded_outcomes` (AC-8).
- [ ] F7b. `…::test_track_record_endpoint_is_mounted_and_tenant_scoped` (F-D1) — hit the real URL;
  a foreign `site_id` returns 404.
- [ ] F7c. `…::test_distinct_contact_positive_rate` (D-O8) — 5 outcomes from ONE contact do not produce a
  5-sample positive rate.
- [ ] F8. `tests/integration/test_engage_benchmark.py::test_engage_sharing_requires_own_flag_not_coop_or_benchmark_flags`
  (AC-9). **(C-F1) Must carry a POSITIVE control** in the same test: a site with the new flag ON DOES
  contribute — otherwise a wholly broken pipeline passes.
- [ ] F9. `…::test_engage_benchmark_k_floor_writes_no_row_below_5` (with a k=5 positive control),
  `…::test_nonconsenting_site_leaves_no_trace`, and `…::test_no_deltas_exposed` (AC-10).
  **(C-F1) `test_no_deltas_exposed` assertion shape is defined here:** assert the module's public
  surface exposes no function whose name or return contains a period-over-period comparison, AND that
  `EngageBenchmark.__table__.columns` contains no prior-period/delta column. It does not assert on a
  sample row.
- [ ] F10. **Flag-ON gates (MANDATORY):** run F4, F4b, F4c, **F4d, F4e, F4h**, F6, F7, F8, F9 with
  `engage_memory_enabled=True`
  and `engage_benchmark_enabled=True`, plus the consent flag ON via fixture where relevant, against real
  PG+Redis. Flag-OFF-only evidence is vacuous.
- [ ] F11. Flag-OFF control: memory writes are no-ops and the benchmark job produces zero rows.
- [ ] F12. Regression: full unit lane green **including re-derived scheduler counts**; existing erasure,
  suppression, and campaign-benchmark integration tests unchanged.

---

## Acceptance Criteria

| AC | Criterion | proven by | strategy |
|---|---|---|---|
| AC-5 | Per-contact memory is erasable PII, registered AND actually deleted by the sweep | **all EIGHT erasure gates**: F4, F4b, F4c, F4d, F4e, F4f, F4g, F4h | Fully-Automated |
| AC-6 | Fact-and-timestamp only; no third-party bodies stored | `test_engage_memory_schema_has_no_third_party_body_field` + `test_inbound_reply_body_not_persisted` (F1, F5) | Fully-Automated |
| AC-7 | Privacy holds and suppression gate memory writes | `test_memory_write_gates_do_not_resolve_and_suppression` + `test_erased_scope_blocks_memory_accrual` + `test_unlinkable_contact_fails_closed` (F6, F6b, F6c, flag-ON via F10) | Fully-Automated |
| AC-8 | Site-scope memory drives a visible track record | `test_site_playbook_track_record_matches_seeded_outcomes` + `test_track_record_endpoint_is_mounted_and_tenant_scoped` + `test_distinct_contact_positive_rate` (F7, F7b, F7c) | Fully-Automated (backend); dashboard render leg Hybrid pending the Clerk auth harness |
| AC-9 | Cross-tenant learning requires its OWN third consent flag | `test_engage_sharing_requires_own_flag_not_coop_or_benchmark_flags` with positive control (F8) | Fully-Automated |
| AC-10 | k≥5 floor, no deltas, no trace, no PII | F9 trio + `test_cross_tenant_payload_contains_no_pii_fields` (F3) | Fully-Automated |

**AC-8 SPEC deviation (D-O8):** the SPEC's "per segment" dimension is DROPPED from v1 — no segment data
source exists in the repo. Track records and the Phase 3a gate key on **playbook × site** only. Recorded
as a known-gap with a backlog stub; AC-8 stays CONDITIONAL on it.

---

## Phase Completion Rules

- 🔨 **CODE DONE** — checklist applied, gates unrun.
- 🧪 **TESTING** — gates running; any red gate keeps the phase here.
- ✅ **VERIFIED** — all 6 AC gates green INCLUDING flag-ON legs (F10), migration live round-tripped on
  a disposable container, validate-contract recorded, regression green, user confirmed — **and all
  EIGHT erasure gates green: F4, F4b, F4c, F4d, F4e, F4f, F4g, F4h**. Code-only is never VERIFIED. AC-8's dashboard leg may
  remain a Hybrid residual ONLY if the backend gates are green and a backlog stub exists; the gate stays
  CONDITIONAL until then.
- 🚧 **BLOCKED** — see blockers below.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `test_erasure_sweep_deletes_engage_memory` (flag-ON, non-vacuous control) | Fully-Automated | AC-5 |
| `test_erasure_sweep_never_logs_unknown_target` | Fully-Automated | AC-5 (kills the F-B1 silent no-op) |
| `test_erasure_matches_via_enqueue_collected_author_bidx` | Fully-Automated | AC-5 (kills the F-B2 impossible join) |
| `test_pending_request_backfill_erases_memory_and_unlinks_outcomes` (asserts BOTH backfilled targets) | Fully-Automated | AC-5 (C-B4 targets snapshot + F3-3) |
| `test_erasure_deletes_memory_for_author_bidx_only_request` (F4e) | Fully-Automated | AC-5 (majority social case; F2-1 guard) |
| `test_write_and_enqueue_derivations_agree` (F4f) | Fully-Automated | AC-5 (key-space divergence, F2-2) |
| F4 / F4c seeded through `record_engage_outcome()` (F4g) | Fully-Automated | AC-5 (production write path, F2-2) |
| `test_erasure_unlinks_engage_outcomes_contact_bidx` (F4h — row survives, `contact_bidx IS NULL`, non-PII columns unchanged, control row untouched) | Fully-Automated | AC-5 (absorbed column is erasable via UNLINK; F3-2) |
| `test_erasure_targets_includes_engage_memory` | Fully-Automated | AC-5 (necessary, NOT sufficient) |
| `test_engage_memory_schema_has_no_third_party_body_field` | Fully-Automated | AC-6 |
| `test_inbound_reply_body_not_persisted` | Fully-Automated | AC-6 |
| `test_memory_write_gates_do_not_resolve_and_suppression` (flag-ON) | Fully-Automated | AC-7 |
| `test_erased_scope_blocks_memory_accrual` | Fully-Automated | AC-7 (`"erased"` scope) |
| `test_unlinkable_contact_fails_closed` | Fully-Automated | AC-7 (majority social case) |
| `test_site_playbook_track_record_matches_seeded_outcomes` | Fully-Automated | AC-8 |
| `test_track_record_endpoint_is_mounted_and_tenant_scoped` | Fully-Automated | AC-8 (F-D1 mount) |
| `test_distinct_contact_positive_rate` | Fully-Automated | AC-8 (D-O8 anti-gaming) |
| Dashboard track-record panel renders seeded numbers | Hybrid (Clerk auth harness) | AC-8 residual — backlog stub required |
| `test_engage_sharing_requires_own_flag_not_coop_or_benchmark_flags` (+ positive control) | Fully-Automated | AC-9 |
| `test_engage_benchmark_k_floor_writes_no_row_below_5` (+ k=5 positive control) | Fully-Automated | AC-10 |
| `test_nonconsenting_site_leaves_no_trace` | Fully-Automated | AC-10 |
| `test_no_deltas_exposed` (public-surface + column-set assertion) | Fully-Automated | AC-10 |
| `test_cross_tenant_payload_contains_no_pii_fields` | Fully-Automated | AC-10 |
| Migration up→down→up on a **disposable** container (**FIVE objects**: 2 new tables, `Site` column, `erasure_requests.author_bidx_list` ALTER, `engage_outcomes.contact_bidx` ALTER) | Hybrid (needs container) | Schema safety (high-risk class) |
| Structural grep: only `engage_memory.py` writes the memory model | Fully-Automated | AC-7 choke-point invariant |
| Handle-rename drift (blind index stops matching after a rename) | Known-Gap → backlog stub (C-A2) | AC-5 residual — keeps AC-5 CONDITIONAL |
| Segment-dimension gate keying | Known-Gap → backlog stub (D-O8) | AC-8 SPEC deviation |

### Test Procedure / Post-Phase Testing

```bash
lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'

# Entry-gate mechanical check (Phase 1 landed?)
.venv/bin/python3.11 -c "from apps.api.models.engage_outcome import EngageOutcome; print(EngageOutcome.__table__.c.keys())"
# Expected: includes site_id and platform_ref. contact_bidx is ABSENT by design (F3-1) — this
# phase adds it in A2b; do not treat its absence as a Phase 1 failure.

.venv/bin/python3.11 -m pytest tests/unit -m unit -q
# Expected: 0 failed (includes re-derived scheduler inventory counts)

.venv/bin/python3.11 -m pytest tests/integration/test_engage_memory_privacy.py tests/integration/test_engage_benchmark.py -q
# Expected: 0 failed

# Flag-ON leg (MANDATORY)
ENGAGE_MEMORY_ENABLED=true ENGAGE_BENCHMARK_ENABLED=true \
  .venv/bin/python3.11 -m pytest tests/integration/test_engage_memory_privacy.py tests/integration/test_engage_benchmark.py -q
# Expected: 0 failed; memory rows actually written for control contacts

# Erasure + suppression regression
.venv/bin/python3.11 -m pytest tests/ -m integration -k "erasure or suppression or benchmark" -q
# Expected: no new failures vs baseline

# Choke-point structural gate
grep -rn "EngageContactMemory" apps/api --include=*.py | grep -v "models/engage_contact_memory.py" | grep -v "services/engage_memory.py"
# Expected: only read-only usages (no insert/add/merge)

# Migration round-trip on a DISPOSABLE container (NOT the shared dev DB)
DOCKER=/Applications/Docker.app/Contents/Resources/bin/docker
$DOCKER run -d --rm --name engage-mig-p2 -e POSTGRES_PASSWORD=pg -p 55434:5432 postgres:16-alpine
export DATABASE_URL='postgresql+asyncpg://postgres:pg@localhost:55434/postgres'
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini downgrade -1
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head
$DOCKER stop engage-mig-p2
# Expected: clean each direction
# Head derivation only (read-only) may use the shared dev DSN:
#   postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent
```

---

## Test Infra Improvement Notes

- No Clerk Playwright auth harness exists — the AC-8 dashboard leg is Hybrid-blocked on the same
  repo-wide gap that blocks the privacy-hold Clear e2e. A backlog stub is required if left unrun.
- A shared fixture factory for `(site, identified_visitor, suppression entry, do_not_resolve visitor,
  enrichment_profile with twitter_handle)` would remove copy-paste across F4/F6/F6b/F6c.
- The erasure gates need a fixture that deletes the identified-visitor join source BEFORE running the
  sweep — otherwise F4c silently passes for the wrong reason.
- `tests/unit/test_scheduler_job_config.py` AST-enforces literal kwargs and hardcoded counts; re-derive
  from the live file in the same change.

---

## Blockers That Would Justify BLOCKED Status

- `_collect_match_keys` cannot be extended to collect the social key at enqueue without restructuring
  the erasure request path — that would make AC-5 structurally unmeetable and needs a design change.
- `DATABASE_URL` cannot be pinned away from Supabase PROD for a migration command (HARD STOP).
- `normalize_category` cannot be reused without modifying `campaign_benchmark.py` (outside this phase's
  blast radius — surface rather than edit).
- The `EnrichmentProfile.twitter_handle` join proves unusable for every realistic contact, making the
  AC-7 suppression gate vacuous even with the fail-closed rule.

---

## Phase Loop Progress

- [ ] 1. RESEARCH — prior phase report read; alembic head re-derived; plan drift checked
- [ ] 2. INNOVATE — approach confirmed against locked D5/D6 + D-O7/D-O8; Decision Summary written
- [x] 3. PLAN-SUPPLEMENT — PVL cycle 1 supplement applied 17-08-26 (F-B1…F-E1, C-A1…C-OV1, V2, V8); Inner Loop Refresh Note written
- [ ] 4. PVL — vc-validate-agent: full V1–V7; re-run from V1 after this supplement
- [ ] 5. EXECUTE — all checklist items done; per-section gates green
- [ ] 6. EVL — independent vc-tester re-run; follow-up stubs registered
- [ ] 7. UPDATE PROCESS — phase report written; umbrella state updated; commit done

**Validate-contract required before execute.**

---

## Exit Gate

- All 6 AC gates green including flag-ON legs; AC-8's dashboard residual either green or backlogged with
  the gate held CONDITIONAL.
- **All EIGHT erasure gates green** (F4, F4b, F4c, F4d, F4e, F4f, F4g, F4h) — including the non-vacuous `erasure_unknown_target` assertion and the F4h unlink assertions (cycle-4 C4-4).
- k≥5 / no-trace / no-delta / no-PII gates green, each with a positive control.
- Migration live round-tripped on a disposable container, covering all **FIVE** schema objects (2 new tables, `Site` column, `erasure_requests.author_bidx_list`, `engage_outcomes.contact_bidx`) — cycle-4 C4-4.
- Handle-rename drift and the segment-dimension deviation each recorded with a backlog stub.
- Phase report written.

---

## Execute Anchor

This file IS the primary execute anchor for its phase — pass this exact path to vc-execute-agent.
Supporting phase files (read-only context, never the execute target): the umbrella plan, the sibling
phase plans, and the locked SPEC in this task folder.

---

## Resume and Execution Handoff

1. Selected plan file path: `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-2-memory-privacy_PLAN_17-08-26.md`
2. Last completed phase or step: PVL cycle 1 supplement applied 17-08-26; awaiting PVL re-run from V1. Depends on Phase 1 exit.
3. Validate-contract status: written (BLOCKED, cycle 1) — must be re-run from V1 after this supplement.
4. Supporting context files loaded: `process/context/all-context.md`, `process/context/tests/all-tests.md`, the SPEC, the umbrella plan, Phase 1 plan.
5. Next step for a fresh agent: re-spawn vc-validate-agent from V1 against this amended plan.

---

## Next Step

Re-run PVL from V1 (`ENTER VALIDATE MODE`). Never ENTER EXECUTE MODE while the contract verdict below
reads BLOCKED.

---

## Validate Contract

Status: CONDITIONAL
Date: 17-08-26
date: 2026-08-17
generated-by: outer-pvl
supersedes: 2026-08-17 (outer-pvl, PVL cycle 5 — CONDITIONAL on C5-1/C5-2) — cycle 6 verified both fixes physically applied; ZERO FAILs and ZERO open CONCERNs remain; CONDITIONAL now rests solely on the four named residuals

Parallel strategy: sequential (no Agent tool in this env — dimension and section checks run sequentially in-agent against real source)
Rationale: signal score 5/7 (S2 schema/API, S4 phase program, S5 depth requested, S6 high-risk class, S7 5+ files). Dominant signal: S6 high-risk — PII/trust boundary + cross-tenant unlink + schema migration on two GDPR-relevant tables.

PVL cycle count (mechanical): `results.tsv` records 4 completed supplement cycles for `phase-2-memory-privacy` beyond baseline. This is NOT a first-pass CONDITIONAL.

### Cycle-5 closure audit (verified physically, not by claim)

| Cycle-5 finding | Verification method | Result |
|---|---|---|
| C5-1 stale four-gate clause + self-falsifying parenthetical | `grep "four erasure gates"` over the plan body → **zero hits**; `grep "REPLACED, not appended"` → **zero hits**. The three surviving `F4, F4b, F4c, F4d` matches (lines 468, 487, 613) are each the opening of the full EIGHT-gate enumeration `F4, F4b, F4c, F4d, F4e, F4f, F4g, F4h`, not a stale four-gate list | CLOSED |
| C5-2 F4d evidence-row name drift | Evidence row now reads `test_pending_request_backfill_erases_memory_and_unlinks_outcomes`, matching the checklist item at line 407 | CLOSED |

Consistency sweep of the two touched sections: the Phase Completion Rules VERIFIED bullet now reads as a single coherent requirement (6 AC gates + flag-ON legs + migration round-trip + contract + regression + user confirmation + all EIGHT erasure gates) with no residual four-gate reading and no provenance note asserting anything about itself. Verification Evidence carries exactly 8 erasure-gate rows. No new contradiction introduced by either edit.

Duplicate-block scan (per the known plan-agent tooling risk): zero duplicated `##` headings, zero duplicated checklist IDs, zero duplicated consecutive long lines. Plan-artifact validator: 0 failures, 0 warnings.

### Net Gate Derivation

| Layer 1 dimension | Status |
|---|---|
| Infra fit | PASS |
| Test coverage | PASS |
| Breaking changes | PASS |
| Security surface | PASS |

| Layer 2 section | Status |
|---|---|
| Entry Gate | PASS |
| Step A — Schema and models | PASS |
| Step B — Erasure | PASS |
| Step C — Write choke point | PASS |
| Step D — Computed track record | PASS |
| Step E — Cross-tenant learning | PASS |
| Step F — Tests | PASS |
| Phase Completion Rules / Verification Evidence | PASS |

**Totals: 0 FAILs / 0 open CONCERNs / 12 PASSes → Net Gate: CONDITIONAL (on named residuals only)**

### Why CONDITIONAL and not PASS

Stated plainly, because this was a delegated judgment call. Two independent reasons, and the first is decisive:

1. **Vacuous-green ban (the deciding factor).** KG-4 — the AC-8 dashboard track-record panel — is *developed behavior shipped by this phase* (item D5 builds the UI) whose only coverage is an Agent-Probe residual. There is no Fully-Automated or Hybrid gate proving the panel renders; the backend numbers are gated (F7, F7b, F7c) but the render is not. A net PASS where developed behavior rests on a named residual alone is banned as a terminal state. That is a coverage fact, not a bookkeeping preference — so this residual belongs in the gate, not only in the known-gap list.
2. **The plan's own exit criteria say so.** Two separate statements in the plan hold gates CONDITIONAL on residuals: "AC-8's dashboard leg may remain a Hybrid residual ONLY if the backend gates are green and a backlog stub exists; the gate stays CONDITIONAL until then", and the Verification Evidence row "AC-5 residual — keeps AC-5 CONDITIONAL". Grading PASS would contradict the artifact being graded.

This is a materially stronger CONDITIONAL than cycle 5's: zero open CONCERNs, every implementation step verified against real source across six cycles, and every residual named with a backlog stub. The remaining conditionality is honest scope acknowledgement, not unfinished validation.

### Test gates (C3 5-column)

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-5a | Sweep deletes memory rows; unrelated control survives | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_engage_memory_privacy.py::test_erasure_sweep_deletes_engage_memory -q` (seeded via `record_engage_outcome()` per F4g) | A |
| AC-5b | No `erasure_unknown_target` logged for EITHER target | Fully-Automated | `…::test_erasure_sweep_never_logs_unknown_target -q` | A |
| AC-5c | Match works via enqueue-collected key after join source destroyed | Fully-Automated | `…::test_erasure_matches_via_enqueue_collected_author_bidx -q` | A |
| AC-5d | Pending request, BOTH backfilled targets: memory erased AND outcomes unlinked | Fully-Automated | `…::test_pending_request_backfill_erases_memory_and_unlinks_outcomes -q` | A |
| AC-5e | Author-bidx-ONLY request still erases (majority social case) | Fully-Automated | `…::test_erasure_deletes_memory_for_author_bidx_only_request -q` | A |
| AC-5f | Write-side and enqueue-side derivations byte-identical | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_engage_memory_schema.py::test_write_and_enqueue_derivations_agree -q` | A |
| AC-5g | `engage_outcomes.contact_bidx` UNLINKED: row survives, bidx NULL, non-PII columns unchanged, control untouched | Fully-Automated | `…::test_erasure_unlinks_engage_outcomes_contact_bidx -q` | A |
| AC-5h | `ERASURE_TARGETS` membership (necessary, NOT sufficient) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_engage_memory_schema.py::test_erasure_targets_includes_engage_memory -q` | A |
| AC-6a | No third-party body column on either table | Fully-Automated | `…::test_engage_memory_schema_has_no_third_party_body_field -q` | A |
| AC-6b | Distinctive inbound body string in zero DB columns | Fully-Automated | `tests/integration/test_engage_memory_privacy.py::test_inbound_reply_body_not_persisted -q` | A |
| AC-7a | do_not_resolve + suppression gate writes; un-held control accrues | Fully-Automated | `ENGAGE_MEMORY_ENABLED=true .venv/bin/python3.11 -m pytest …::test_memory_write_gates_do_not_resolve_and_suppression -q` | A |
| AC-7b | `"erased"` scope blocks accrual | Fully-Automated | `…::test_erased_scope_blocks_memory_accrual -q` | A |
| AC-7c | Unlinkable contact fails closed | Fully-Automated | `…::test_unlinkable_contact_fails_closed -q` | A |
| AC-7d | Choke-point: only `engage_memory.py` writes the model | Fully-Automated | `grep -rn "EngageContactMemory" apps/api --include=*.py \| grep -v "models/engage_contact_memory.py" \| grep -v "services/engage_memory.py"` → no insert/add/merge | A |
| AC-8a | Track record matches seeded outcomes | Fully-Automated | `…::test_site_playbook_track_record_matches_seeded_outcomes -q` | A |
| AC-8b | Endpoint mounted; foreign site_id → 404 | Fully-Automated | `…::test_track_record_endpoint_is_mounted_and_tenant_scoped -q` | A |
| AC-8c | DISTINCT-contact positive rate (anti reply-spam) | Fully-Automated | `…::test_distinct_contact_positive_rate -q` | A |
| AC-8d | Dashboard panel renders seeded numbers | Agent-Probe | manual authed dashboard check — no Clerk Playwright harness repo-wide | D — backlog stub; **this is the residual that holds the gate CONDITIONAL** |
| AC-9 | New flag is the ONLY basis, WITH positive control | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_engage_benchmark.py::test_engage_sharing_requires_own_flag_not_coop_or_benchmark_flags -q` | A |
| AC-10a | k-floor writes no row below 5, with k=5 positive control | Fully-Automated | `…::test_engage_benchmark_k_floor_writes_no_row_below_5 -q` | A |
| AC-10b | Non-consenting site leaves no trace | Fully-Automated | `…::test_nonconsenting_site_leaves_no_trace -q` | A |
| AC-10c | No deltas — public surface + column-set assertion | Fully-Automated | `…::test_no_deltas_exposed -q` | A |
| AC-10d | Cross-boundary payload has no PII / tenant id | Fully-Automated | `tests/unit/test_engage_memory_schema.py::test_cross_tenant_payload_contains_no_pii_fields -q` | A |
| ENTRY | Phase 1 landed; `contact_bidx` absent by design | Fully-Automated | `.venv/bin/python3.11 -c "from apps.api.models.engage_outcome import EngageOutcome; print(EngageOutcome.__table__.c.keys())"` lists `site_id` and `platform_ref` ONLY | A |
| SCHEMA | Migration up→down→up, all FIVE objects | Hybrid | disposable `postgres:16-alpine` on :55434 per the Test Procedure; NEVER the shared dev DB; DSN pinned (repo `.env` targets Supabase PROD) | A |
| REGRESSION | Erasure / suppression / benchmark unchanged | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/ -m integration -k "erasure or suppression or benchmark" -q` | A |
| REGRESSION-UNIT | Unit lane green incl. re-derived scheduler counts | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` | A |

gap-resolution legend: A — proven now; B — fixed in this plan; C — deferred to a named later phase; D — backlog test-building stub.

C-4 reconciliation: the `strategy:` column carries ONLY Fully-Automated / Hybrid / Agent-Probe. Known-Gap is never a strategy — it is a named residual (see Known Gaps below).

Legacy line form:
- Per-contact memory + erasure: [Fully-automated: `.venv/bin/python3.11 -m pytest tests/integration/test_engage_memory_privacy.py -q`]
- Flag-ON leg (MANDATORY, non-vacuous): [hybrid: `ENGAGE_MEMORY_ENABLED=true ENGAGE_BENCHMARK_ENABLED=true .venv/bin/python3.11 -m pytest tests/integration/test_engage_memory_privacy.py tests/integration/test_engage_benchmark.py -q` + precondition PG:5433 & Redis:6379 listening]
- Cross-tenant benchmark: [Fully-automated: `.venv/bin/python3.11 -m pytest tests/integration/test_engage_benchmark.py -q`]
- Structural/unit: [Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit -m unit -q`]
- Migration safety: [hybrid: disposable postgres:16-alpine up→down→up covering FIVE objects, DSN pinned]
- Dashboard render: [agent-probe: manual authed dashboard check]

Failing stub (AC-5g):
```
def test_erasure_unlinks_engage_outcomes_contact_bidx():
    raise NotImplementedError("NOT IMPLEMENTED — TDD stub: seed engage_outcomes row with contact_bidx; run sweep; assert row STILL EXISTS, contact_bidx IS NULL, non-PII columns unchanged, control contact's contact_bidx untouched")
```
Failing stub (AC-5d):
```
def test_pending_request_backfill_erases_memory_and_unlinks_outcomes():
    raise NotImplementedError("NOT IMPLEMENTED — TDD stub: request enqueued with the OLD targets list, backfilled by the migration, erases the memory row AND nulls engage_outcomes.contact_bidx")
```
Failing stub (AC-5e):
```
def test_erasure_deletes_memory_for_author_bidx_only_request():
    raise NotImplementedError("NOT IMPLEMENTED — TDD stub: request with populated author_bidx_list but EMPTY email_bidx_list and EMPTY fingerprint_list still deletes")
```

### Dimension findings

- Infra fit: PASS — every edited file is owned in both Touchpoints and the umbrella registry, including `models/engage_outcome.py` (SHARED-with-rule) and `jobs/scheduler.py` (SHARED-append-only). Phase 2 ⟂ Phase 3a file-set disjointness verified against the registry.
- Test coverage: PASS — eight erasure gates each with a named non-vacuity control or structural assertion; F10 runs the flag-ON leg across F4, F4b, F4c, F4d, F4e, F4h, F6, F7, F8, F9; F4g forces production-write-path seeding. Only AC-8d lacks an automated gate (KG-4, named).
- Breaking changes: PASS — two nullable additive columns, two additive `ERASURE_TARGETS` entries, one additive endpoint on an already-mounted router, one additive `pii_crypto` helper; cross-tenant unlink semantics documented in B5b and Public Contracts.
- Security surface: PASS — the GDPR path is specified end to end: enqueue-time key collection, persisted carrier column, extended claim (`claimed[5]`), widened dispatch guard, two dispatch branches, delete for memory and unlink for outcomes, backfill of both target names, new-rows-only derivation with no post-erasure minting, and a four-assertion non-vacuity gate on the unlink.
- Entry Gate / Steps A–F / Phase Completion Rules / Verification Evidence: PASS — all re-derived against real source across cycles 1–6.

### Open gaps

**FAILs: none. Open CONCERNs: none.**

**Known Gaps (named residuals — these alone hold the gate at CONDITIONAL):**

- **KG-1 — handle-rename drift. ⚠ PENDING USER DECISION — the one item still requiring an explicit accept/reject.** The social blind index derives from a MUTABLE handle (`Post.author_username` / `EnrichmentProfile.twitter_handle`). A contact who renames leaves pre-rename rows in BOTH `engage_contact_memory` (undeletable) and `engage_outcomes` (un-unlinkable) that no later erasure request can match — Beam would hold un-erasable per-contact PII for that person across two tables. Accepting means a bounded, documented GDPR residual on a privacy feature; the plan records it in the module docstring plus a backlog stub (A1b) and holds AC-5 CONDITIONAL on it. Rejecting means persisting a platform-stable numeric author id, which no repo surface stores today — a scope increase that would likely push work back into Phase 1.
- **KG-2 — segment dimension dropped from v1 keying (D-O8).** SPEC AC-8/AC-11 imply per-segment track records; no segment data source exists in the repo, so gate keying is playbook × site only. Documented SPEC deviation with a backlog stub; Phase 3a/3b key identically. Accepted by orchestrator.
- **KG-3 — LinkedIn social-key erasure out of scope for v1 (B2c).** `EnrichmentProfile` stores `linkedin_url`, not a handle, so no symmetric derivation exists. v1 covers X/Twitter only, with a backlog stub. Accepted.
- **KG-4 — AC-8 dashboard render leg.** Blocked on the repo-wide missing Clerk Playwright auth harness (same gap as privacy-hold Clear). This is developed behavior with no Fully-Automated or Hybrid gate — the reason the net gate is CONDITIONAL rather than PASS. Backend legs are Fully-Automated; the render leg is Agent-Probe with a backlog stub.

### Plan updates applied

None by this agent. The plan required no further edits — both cycle-5 fixes were applied by the plan-agent and verified physically here.

### Execute-agent instructions

| # | Instruction | Trigger |
|---|---|---|
| E1 | Re-derive the live alembic head with `DATABASE_URL` pinned. Repo `.env` points at Supabase PROD and `migrations/env.py` has NO local-host guard — an unpinned alembic command applies DDL to production. HARD STOP if it cannot be pinned. | Step A5 entry |
| E2 | Run the migration round-trip on a DISPOSABLE `postgres:16-alpine` container, never the shared dev DB on :5433. Docker CLI is off PATH — use `/Applications/Docker.app/Contents/Resources/bin/docker`. Verify all FIVE objects. | Step A6 |
| E3 | Add both model imports to `apps/api/main.py` with `# noqa: F401`. `tests/conftest.py:123` (`import apps.api.main`) is the ONLY table-registration mechanism for the integration lane. | Step A7 |
| E4 | Append `author_bidx_list` AFTER `targets` in the `_claim_next` RETURNING clause and read it as `claimed[5]`. Inserting earlier silently breaks the existing `claimed[4]` targets read. | Step B4 |
| E5 | Define the platform literal ONCE as a module constant, imported by the write side (A1, A2b) and the enqueue side (B2b). Never spell it twice. | Steps A1, A2b, B2b |
| E6 | `engage_outcomes` erasure is an UNLINK (`SET contact_bidx = NULL`), never a DELETE. Deleting those rows destroys the track records Phase 3a/3b read. If any gate name or assertion says "delete" for this table, the gate is wrong — fix the gate, not the implementation. | Steps B5b, F4h |
| E7 | Seed memory and outcome rows in every erasure gate through the production write path `record_engage_outcome()`, never by constructing ORM objects directly — a hand-built fixture hides a key-space mismatch. | Step F erasure gates |
| E8 | Run all EIGHT erasure gates (F4, F4b, F4c, F4d, F4e, F4f, F4g, F4h), not four. | Step F / phase exit |
| E9 | Re-derive `test_scheduler_job_config.py` counts from the live file in the same change. Do not trust any number written in the plan. | Step E7 |
| E10 | Run every flag-gated gate with the flag ON against real PG+Redis. This repo has shipped two silent no-ops that survived flag-OFF-only validation (icp_fit, ip-org G8/G10). | Step F10 |
| E11 | Write the backlog stubs for KG-1…KG-4 as part of this phase, not after. The Exit Gate requires the handle-rename and segment-dimension stubs to exist. | Phase exit |

### Backlog artifacts

| Artifact | Location | Tracks |
|---|---|---|
| `engage-memory-handle-rename-drift_NOTE_17-08-26.md` | `process/features/campaigns-outreach/backlog/` | KG-1 — mutable-handle blind index leaves un-erasable rows across BOTH tables; pending user accept/reject |
| `engage-linkedin-social-key-erasure_NOTE_17-08-26.md` | `process/features/campaigns-outreach/backlog/` | KG-3 — LinkedIn has no handle column, so no symmetric erasure derivation in v1 |
| `engage-track-record-segment-dimension_NOTE_17-08-26.md` | `process/features/campaigns-outreach/backlog/` | KG-2 — SPEC segment dimension dropped from v1 gate keying |
| `engage-track-record-e2e-auth-harness_NOTE_17-08-26.md` | `process/features/campaigns-outreach/backlog/` | KG-4 — AC-8 dashboard render leg, blocked on the Clerk Playwright auth harness |

### What this coverage does NOT prove

- No gate proves erasure for a contact who renamed their handle after the rows were written (KG-1) — un-erasable across both tables — nor for LinkedIn contacts (KG-3).
- No gate proves the AC-8 dashboard panel renders (KG-4) — backend numbers only. This is the named coverage hole behind the CONDITIONAL verdict.
- `test_erasure_unlinks_engage_outcomes_contact_bidx` proves the unlink for the seeded contact and one control row. It does NOT prove correctness under concurrent sweeps, nor that every historical row with a NULL `contact_bidx` was genuinely never linked rather than silently skipped.
- `test_erasure_targets_includes_engage_memory` proves tuple membership only — never deletion or unlink. This distinction produced FAILs in three consecutive cycles.
- `test_memory_write_gates_do_not_resolve_and_suppression` does NOT prove behavior for suppression scopes beyond the two seeded, nor for handles matching multiple enrichment rows beyond the single fail-closed case.
- `test_inbound_reply_body_not_persisted` proves absence of ONE string across the two named tables — not across logs, Redis, or prompts.
- `test_no_deltas_exposed` proves the module exposes no delta function and the model has no delta column — it does NOT prove a delta is uncomputable by a caller polling the endpoint over time.
- `test_engage_benchmark_k_floor_writes_no_row_below_5` does NOT prove the floor holds under concurrent aggregation runs, nor that k=5 is sufficient anonymity for the real site population.
- Nothing measures the cross-tenant side effect of the unlink: nulling one contact's `contact_bidx` reduces every tenant's DISTINCT-contact denominator, and no gate quantifies that.
- The migration round-trip proves disposable-container safety only. It does NOT prove the Supabase PROD apply path; prod head must be re-derived at deploy time.
- All integration gates depend on PG:5433 + Redis:6379 (confirmed listening 17-08-26). Nothing here proves CI-runnability.
- Every gate above is a WRITTEN contract, not a run result. Nothing in this phase has been executed — these gates are what EXECUTE and EVL must run and turn green.

Gate: CONDITIONAL (0 FAILs, 0 open CONCERNs; conditional solely on named residuals KG-1…KG-4, with KG-4 the coverage hole that bars a terminal PASS)
Accepted by: NOT YET ACCEPTED — vc-validate-agent does not self-accept. Sign-off requires: (a) the USER's explicit accept/reject on **KG-1 handle-rename drift**, and (b) the orchestrator recording acceptance of KG-2, KG-3, KG-4 by name. Once recorded, EXECUTE is legal — `results.tsv` shows 4 completed supplement cycles, satisfying the N≥1 requirement for a non-first-pass CONDITIONAL.
