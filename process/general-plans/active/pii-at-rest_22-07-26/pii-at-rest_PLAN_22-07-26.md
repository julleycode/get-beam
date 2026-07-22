---
name: plan:pii-at-rest
description: "Complete PII encryption-at-rest — backfill, blind-index lookup cutover, read cutover, plaintext column drop"
date: 22-07-26
feature: general
---

# PII Encryption-at-Rest — Completion Plan

**Date**: 22-07-26
**Status**: DRAFT — awaiting VALIDATE
**Complexity**: COMPLEX (5 phases, migration-bearing, one destructive phase, cross-cutting blast radius across routers/services/agents)

## TL;DR

Phase 05 left plaintext PII authoritative even though ciphertext/blind-index columns and write-side hooks already exist. This plan finishes the job in 5 ordered phases — backfill existing rows, unify the two duplicate hash implementations, cut lookups over to the blind index (and repoint the risky `ON CONFLICT` upsert keys **before** anything else touches them), cut reads over to decrypted ciphertext, and only then drop the plaintext columns. The single riskiest step (identity-graph dedup silently breaking) is neutralized by sequencing: Phase 3 must land before Phase 5 can even be proposed.

## Overview

**Goal:** Genuine PII encryption at rest for email, full_name, and social handles across `visitor_emails`, `identified_visitors`, `beam_identity_graph`, and `enrichment_profiles`. Today: ciphertext/bidx columns exist and are dual-written on new rows (5a+5b done), but pre-existing rows are unencrypted, all 30 read sites still consume plaintext, 11 lookup sites still query plaintext equality, and the 3 `ON CONFLICT` upserts still key on plaintext email — so plaintext remains authoritative in every way that matters.

**Scope:** Backend only (`apps/api/`). No frontend, no new external providers, no billing/auth surface changes. Touches: `services/pii_crypto.py`, `services/known_hash.py`, `services/identity_resolver.py`, `services/enricher.py`, `services/csv_exporter.py`, `services/outcome_digest.py`, `services/hot_alert.py`, `services/campaign_sender.py`, `agents/segmenter.py`, `routers/visitors.py`, `routers/visitors_helpers.py`, `routers/campaigns.py`, `services/sync.py`, `services/social_intelligence.py`, `routers/events.py` (raw insert only, already patched), `routers/click.py` (raw insert only, already patched), `services/suppression.py`, `services/email_sender.py`, `routers/unsubscribe.py`, plus 2 new Alembic migrations and 1 new backfill script.

**Out of scope:** New encryption algorithm/library, key rotation tooling, encrypting fields beyond email/full_name/social handles, any provider integration change, `known_contacts` table redesign (only its hash impl is touched in Phase 2).

## Phase Completion Rules

- A phase is `CODE DONE` when its checklist edits are applied and its own Verification Evidence table gates are green.
- A phase is `VERIFIED` only when: (a) its own gates are green, AND (b) any earlier-phase regression checks it depends on (e.g. Phase 3's ON CONFLICT fix) are still green, AND (c) for Phase 5 specifically, the manual-first evidence pack is signed off by the operator (code-only completion is never sufficient for the destructive phase).
- Do not mark any phase `✅ VERIFIED` on automated gates alone if that phase carries a Hybrid or Agent-Probe tier gate — those require the corresponding manual/integration confirmation to have actually run, not just be theoretically available. Phase 5's `✅ VERIFIED` state additionally requires explicit user-confirmed / operator-confirmed sign-off on the manual evidence pack — automated gates alone never satisfy it.

## Acceptance Criteria

1. Every pre-existing row in the 4 target tables has ciphertext (and bidx, where applicable) populated — verified via Phase 1's dry-run zero-remaining-rows gate.
2. `known_hash.email_hash` and `pii_crypto.email_hash` are provably equal (pinned by test) — Phase 2.
3. All 11 plaintext-equality lookup sites and all 3 `ON CONFLICT` upsert sites use the blind index — verified via Phase 3's lookup + riskiest-site regression tests, including production confirmation before Phase 5 proceeds.
4. All 30 read sites (including GDPR export) return decrypted plaintext via the centralized `.pii_*` accessor, with zero raw plaintext-column reads remaining outside the accessor definitions — verified via Phase 4's grep sweep + GDPR export test.
5. Plaintext columns are physically dropped from all 4 tables, with the manual-first evidence pack accepted by the operator beforehand — verified via Phase 5's staging dry-run + full regression suite + sign-off.
6. At no point does the identity-graph/email dedup upsert path silently fail (the "Riskiest Site" failure mode) — continuously verified from Phase 3 onward via the riskiest-site regression tests.

## Implementation Checklist / Phased Delivery Plan

This plan uses a 5-phase delivery structure (Phase 1 through Phase 5 below) as its implementation checklist — each phase section contains its own ordered touchpoints, migration steps, and verification gates in sequence. See "Phase Ordering" implicit in the phase numbering: 1 (backfill) -> 2 (unify hash) -> 3 (lookup cutover) -> 4 (read cutover) -> 5 (drop plaintext, destructive).

## Touchpoints

See the Blast Radius tables below (READ sites, WRITE sites, LOOKUP sites, ON CONFLICT constraints) for the complete file:line inventory. Summary by phase: Phase 1 — new `scripts/backfill_pii_ciphertext.py` only. Phase 2 — `services/known_hash.py` + test. Phase 3 — 11 lookup sites across 6 files, 3 ON CONFLICT sites across 3 files, 1 new migration. Phase 4 — ~30 read sites across ~12 files, 4 model files (new accessors). Phase 5 — 1 migration (drop columns), accessor fallback removal in 4 model files.

## Verification Evidence

Full per-phase Verification Evidence tables (with exact pytest commands and TDD failing stubs) are embedded in each phase section below (Phase 1 through Phase 5). Summary: Phase 1-2 gates are Fully-Automated; Phase 3-4 gates are Fully-Automated + Hybrid (integration, needs PG+Redis per `docker-compose.yml`); Phase 5 gates are Hybrid + Agent-Probe (manual evidence pack review), reflecting its high-risk/destructive classification.

## Prior Research (verified, do not re-derive)

- Crypto: `apps/api/services/pii_crypto.py` — `encrypt_pii`/`decrypt_pii` (Fernet; `decrypt_pii` is **tolerant**: non-ciphertext input is returned as-is — this is what makes Phase 4 safe on partially-backfilled data). `email_hash` = HMAC-SHA256 blind index. `normalize_email`. Keys: `PII_ENCRYPTION_KEY`/`PII_HMAC_KEY`, falling back to `ENCRYPTION_KEY`.
- **5a DONE** — migration `e7b4c2f9a1d8` added `*_ciphertext` + `*_bidx` columns to `visitor_emails`, `identified_visitors`, `beam_identity_graph`, `enrichment_profiles`. Enrichment profile columns have ciphertext but **no bidx** (no blind-index lookup need there today).
- **5b DONE** — `apps/api/services/pii_encryption_hooks.py`: SQLAlchemy `before_insert`/`before_update` mapper events populate ciphertext/bidx for `IdentifiedVisitor`, `BeamIdentityNode`, `VisitorEmail`, `EnrichmentProfile`. 3 raw `pg_insert` sites bypass ORM hooks and are **already manually patched**: `identity_resolver.py:808-828` (B11), `events.py:479-488` (B12), `click.py:117-128` (B13).
- 2 lookups **already** on bidx: `identity_resolver.py:858` (`BeamIdentityNode.email_bidx`), `outcomes.py:490` (`VisitorEmail.email_bidx`) — both use `pii_crypto.email_hash`.
- **Migration head:** `b8f3c1d92a47`. New migrations in this plan chain off this head, in phase order (Phase 1 has no migration; Phase 3's migration is head→X; Phase 5's migration is X→Y).
- `apps/api/services/known_hash.py` confirmed on disk: `normalize_email` (17), `_hmac_key` (22), `email_hash` (35) — a byte-identical second implementation of the same algorithm using the same key fallback chain, serving only `known_contacts.email_hash`.

## Blast Radius

### READ sites (30) — plaintext PII consumed today, cut to decrypt in Phase 4

| # | File:line | Field | Notes |
|---|---|---|---|
| 1-2 | `routers/visitors.py:122-123` | email/name | list view |
| 3-4 | `routers/visitors.py:147-148` | email/name | detail view |
| 5 | `routers/visitors.py:164` | email | |
| 6 | `routers/visitors.py:169` | email | joins `known_hash` lookup — coordinate with Phase 2 |
| 7-9 | `routers/visitors.py:330-332` | email/name/handles | **GDPR export** — must decrypt explicitly or export ships ciphertext |
| 10-11 | `routers/visitors.py:530-531` | email/name | |
| 12-13 | `routers/visitors.py:553-554` | email + enrichment handles | |
| 14-15 | `routers/campaigns.py:278-279` | email/name | |
| 16 | `routers/campaigns.py:728` | email | |
| 17-18 | `routers/campaigns.py:734-744` | email + enrichment handles | |
| 19 | `services/campaign_sender.py:194` | email | |
| 20 | `services/campaign_sender.py:208` | email | |
| 21 | `services/campaign_sender.py:244` | email | |
| 22-23 | `services/hot_alert.py:85-87` | email/name | |
| 24 | `services/csv_exporter.py:69` | email | |
| 25 | `services/csv_exporter.py:73` | email (feeds `known_hash`) | |
| 26 | `services/csv_exporter.py:84` | name | |
| 27-28 | `services/csv_exporter.py:95,100` | email/name → consumed by `:122/144/160` | |
| 29 | `services/outcome_digest.py:136` | email | |
| 30-31 | `agents/segmenter.py:97-98,108-109` | email/name | `build_visitor_profiles`, reused by `campaigns.py:120` → feeds Gemini prompt (goes through `prompt_safety.sanitize_profiles` already — decrypt BEFORE sanitize, not instead of) |
| 32 | `routers/visitors_helpers.py:61` | email | |
| 33-37 | `services/identity_resolver.py:149,281,289-322,309,342` | email | multiple read points in resolution waterfall |
| 38-39 | `services/identity_resolver.py:886-899` | email | |
| 40-41 | `routers/visitors.py:553-554` / `campaigns.py:734-744` | enrichment handles | (same lines as 12-13/17-18 — cross-listed since both email and handle appear on these lines) |
| 42 | `services/sync.py:113` | enrichment handles | |
| 43-44 | `services/social_intelligence.py:66,71-73` | enrichment handles | |

(Line-count note: several lines carry 2 fields — 30 distinct *sites*, ~44 distinct field-reads. Treat the file:line list above as authoritative, not the summed count.)

### WRITE sites (13) — 10 ORM (hooks already fire, no plan changes needed) + 3 raw (already patched, verify only)

- ORM (ALREADY correct via 5b hooks): `identity_resolver.py:737-747`, `visitors.py:766-779`, `enricher.py:354-366`, `enricher.py:835-840`, `visitors.py:796-808`, `visitors.py:979-982`, `visitors_helpers.py:307`, `visitors_helpers.py:365`.
- Raw `pg_insert` (ALREADY patched — B11/B12/B13): `identity_resolver.py:808-828`, `events.py:479-488`, `click.py:117-128`.
- **Regression guard (Phase 3 + ongoing):** any NEW raw insert added to these 4 tables must set ciphertext/bidx manually — add this to code-review checklist language in Phase 3's verification section; no code change needed today since no new raw insert exists.

### LOOKUP sites (11) — plaintext email-equality queries, cut to bidx in Phase 3

| # | File:line | Notes |
|---|---|---|
| 1 | `services/suppression.py:61` | |
| 2 | `services/suppression.py:69` | |
| 3 | `services/suppression.py:79` | |
| 4 | `services/email_sender.py:33` | |
| 5 | `services/identity_resolver.py:713` | |
| 6 | `routers/unsubscribe.py:81` | |
| 7 | `routers/unsubscribe.py:99` | |
| 8 | `routers/visitors_helpers.py:63` | NOT-NULL filter, not equality — confirm bidx column non-null semantics match |
| 9 | `services/identity_resolver.py:886` | NOT-NULL filter |
| 10 | `services/identity_resolver.py:859` | NOT-NULL filter |
| 11 | `services/sync.py:117-118` | **twitter_handle — no bidx column exists.** Cannot query-filter by bidx. Must load candidate rows and decrypt-filter in Python, capped at 50 rows to bound cost. |

### Uniqueness / ON CONFLICT constraints (Phase 3 migration)

| ID | Constraint | Referenced by | Change |
|---|---|---|---|
| C14 | `uq_visitor_email_site_vid_email` (`site_id, visitor_id, email`) | `events.py:485`, `click.py:127` (`ON CONFLICT`) | Add parallel bidx-keyed unique constraint; repoint `ON CONFLICT index_elements` to bidx version; keep plaintext constraint until Phase 5 |
| C15 | `uq_beam_identity_fp_email` (`fingerprint, email`) | `identity_resolver.py:819-820` (`on_conflict_do_update`) | Same treatment |
| C17 | `uq_identified_site_visitor` | — | **Not email-keyed — no change** |

## Riskiest Site (sequencing-critical — read before touching anything)

`identity_resolver.py:819-820` `on_conflict_do_update(index_elements=["fingerprint","email"])`, plus the matching upserts at `events.py:485` and `click.py:127`, use **plaintext email as the ON CONFLICT key**. If plaintext is dropped (Phase 5) before these are repointed to `email_bidx` (Phase 3), the upsert raises — and the exception is **silently swallowed at debug level** (`identity_resolver.py:836-838`, and equivalently in `events.py`/`click.py`). Failure mode: cross-customer identity-graph merging and email dedup silently stop working — every returning visitor re-triggers identity resolution and re-pays a provider, with no error surfaced anywhere.

**Hard sequencing rule:** Phase 3 (bidx unique constraints + ON CONFLICT repoint) MUST land and be verified before Phase 5 (drop plaintext) is even proposed for execution. Phase 5's gate explicitly re-checks this.

## known_hash Duplication (Phase 2)

`apps/api/services/known_hash.py` is a byte-identical second implementation of `email_hash` (same HMAC-SHA256 algorithm, same key fallback chain) used only for `known_contacts.email_hash` (`known_contacts.py`, `known_contacts_match.py`, `csv_exporter.py:73`, `visitors_helpers.py:66`, `visitors.py:169`). `pii_crypto.email_hash` serves the 4 target models plus suppression lookups. Same key today, but **no test pins equality** — this is a cutover hazard: a future dev reaches for `known_hash.email_hash` to query `identified_visitors.email_bidx` (or vice versa), works today because they're identical, and silently diverges later if either key or algorithm changes independently → emails sent to opted-out users, duplicate identity rows.

**Fix:** `known_hash.email_hash` delegates to `pii_crypto.email_hash` internally (keep the public function name/signature so existing 5 import sites are untouched). Add a unit test asserting `known_hash.email_hash(x) == pii_crypto.email_hash(x)` for a fixed set of inputs, so future drift is caught immediately, not silently.

## Mixed-Data Window (why the phase order is safe)

`decrypt_pii` is tolerant — non-ciphertext input is returned unchanged. This means:
- **Read cutover (Phase 4) is safe on partially-backfilled data** — a decrypted read of a still-plaintext row just returns the plaintext as-is.
- **Lookup cutover (Phase 3) is NOT safe until backfill (Phase 1) completes** — a bidx-keyed query against a row with `NULL` bidx will never match, silently breaking lookups for un-backfilled rows (suppression checks, unsubscribe, identity resolution).

This is why **Phase 1 (backfill) strictly precedes Phase 3 (lookup cutover)**, even though Phase 4 (read cutover) could technically run before backfill finishes. The plan still orders 1→2→3→4→5 for simplicity and to keep the riskiest constraint change (Phase 3) as early as safely possible.

---

## Phase 1 — Backfill Existing Rows

**Objective:** Every existing row in `visitor_emails`, `identified_visitors`, `beam_identity_graph`, `enrichment_profiles` gets ciphertext (and bidx, where applicable) populated from its current plaintext value.

**Touchpoints:** New file `apps/api/scripts/backfill_pii_ciphertext.py` (standalone script, not an Alembic data migration — row-by-row Fernet encryption of potentially large tables should not run unbatched inside a schema-migration transaction/deploy step).

**Design:**
- Iterate each of the 4 tables in batches (e.g. 500 rows/batch) `WHERE ciphertext IS NULL` (email tables also filter `OR bidx IS NULL` to catch any partial-write edge case).
- For each row: `pii_crypto.encrypt_pii(plaintext)` → ciphertext column; `pii_crypto.email_hash(normalize_email(plaintext))` → bidx column (email fields only — `enrichment_profiles` ciphertext-only, no bidx per current schema).
- Idempotent: safe to re-run (WHERE clause naturally skips completed rows). Resumable: no in-memory checkpoint needed since it's WHERE-driven.
- Log per-batch counts (structlog, keys/counts only — never log PII value per repo convention).
- CLI flags: `--dry-run` (count only, no writes), `--batch-size`, `--table` (optional single-table run for staged rollout).

**Migration:** None — pure data backfill via application code using existing columns from `e7b4c2f9a1d8`.

**Blast radius:** New file only. Zero risk to running application code paths (script is not imported by any router/service).

**Verification Evidence:**

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Unit test: seed a row with only plaintext, run backfill function, assert ciphertext decrypts to original + bidx matches `pii_crypto.email_hash` | Fully-Automated | Backfill correctness |
| Unit test: seed a row with ciphertext already populated, run backfill, assert no double-encryption (row untouched / re-encrypt is idempotent via decrypt-then-check) | Fully-Automated | Idempotency |
| `--dry-run` against dev DB, assert reported count matches `SELECT COUNT(*) WHERE ciphertext IS NULL` | Hybrid (needs DB) | Resumability / accurate targeting |
| Failing stub | | |

```
test("should encrypt a plaintext-only row and populate matching bidx", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: backfill encrypts plaintext row and sets ciphertext+bidx")
})
test("should skip a row that already has ciphertext populated (idempotent)", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: backfill idempotency on already-encrypted row")
})
```

Command: `.venv/bin/python -m pytest tests/unit/test_backfill_pii_ciphertext.py -v`

**Rollback:** Backfill only writes to already-nullable ciphertext/bidx columns; plaintext columns are untouched. Rollback = no-op (leave populated columns as-is; they're inert until Phase 3/4 read them).

**Risk:** LOW, fully reversible (no schema change, no behavior change — new columns are not yet read by anything).

**Gate to advance:** `--dry-run` on dev DB reports 0 remaining un-backfilled rows across all 4 tables after a real run; unit tests green.

---

## Phase 2 — Unify Blind Index Implementation

**Objective:** Eliminate the `known_hash`/`pii_crypto` duplication risk before any new consumer is added to either function.

**Touchpoints:**
- `apps/api/services/known_hash.py` — `email_hash()` body becomes `return pii_crypto.email_hash(email)` (keep function signature/name so all 5 existing call sites — `known_contacts.py`, `known_contacts_match.py`, `csv_exporter.py:73`, `visitors_helpers.py:66`, `visitors.py:169` — are untouched).
- New/updated test: assert `known_hash.email_hash(x) == pii_crypto.email_hash(x)` for a fixed input set (including edge cases: mixed-case email, leading/trailing whitespace — confirm both go through the same `normalize_email`).

**Migration:** None.

**Blast radius:** 1 file body change, 0 call-site changes, 1 new/updated test file. Behaviorally a no-op today (same key, same algorithm) — this phase is pure risk-reduction for Phase 3/4.

**Verification Evidence:**

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Equality test: `known_hash.email_hash(x) == pii_crypto.email_hash(x)` for 5+ fixed inputs incl. case/whitespace variants | Fully-Automated | No silent divergence between the two implementations |
| Existing `known_contacts` tests still pass unmodified (no behavior change from caller's perspective) | Fully-Automated | Refactor is behavior-preserving |
| Failing stub | | |

```
test("should return identical hash from known_hash.email_hash and pii_crypto.email_hash for equivalent inputs", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: known_hash/pii_crypto equality")
})
```

Command: `.venv/bin/python -m pytest tests/unit/test_known_hash.py tests/unit/test_pii_crypto.py -v`

**Rollback:** Revert single-file edit; trivial `git revert`.

**Risk:** LOW, fully reversible.

**Gate to advance:** Equality test green; full existing `known_contacts`-related test suite green with no changes required to those tests.

---

## Phase 3 — Lookup Cutover + Constraint Repoint (the safety-critical gate for Phase 5)

**Objective:** All 11 plaintext-equality lookup sites move to bidx; the 3 `ON CONFLICT` upserts move their `index_elements` to bidx-backed unique constraints; both plaintext and bidx unique constraints coexist during the transition window (removed in Phase 5).

**Prerequisite:** Phase 1 backfill fully complete (verified via gate) — bidx-keyed lookups against NULL bidx never match.

**Touchpoints (code):**
- `services/suppression.py:61,69,79` — email-equality → `email_bidx == pii_crypto.email_hash(normalize_email(email))`
- `services/email_sender.py:33` — same pattern
- `services/identity_resolver.py:713` — same pattern
- `routers/unsubscribe.py:81,99` — same pattern
- `routers/visitors_helpers.py:63` — NOT-NULL filter: confirm swap to `email_bidx IS NOT NULL` preserves intended semantics (should — bidx is populated exactly when email is present, post-backfill)
- `services/identity_resolver.py:886,859` — same NOT-NULL swap
- `services/sync.py:117-118` — **no bidx column for twitter_handle.** Load candidate rows (bounded query, e.g. by site_id + recency), decrypt each `handle_ciphertext` in Python, filter for match, **cap at 50 rows** to bound cost. Document this as the one lookup site that stays O(n) by design.

**Touchpoints (migration):** New Alembic migration (head → new revision, chained after `b8f3c1d92a47`):
- Add unique constraint on `beam_identity_graph(fingerprint, email_bidx)` — parallel to existing `uq_beam_identity_fp_email`.
- Add unique constraint on `visitor_emails(site_id, visitor_id, email_bidx)` — parallel to existing `uq_visitor_email_site_vid_email`.
- Do NOT drop the plaintext-keyed constraints yet (Phase 5 only).

**Touchpoints (ON CONFLICT repoint):**
- `identity_resolver.py:819-820` — `index_elements=["fingerprint","email"]` → `["fingerprint","email_bidx"]` (now targets the new constraint)
- `events.py:485` and `click.py:127` — **NOT the same repoint mechanism as above.** Both use `.on_conflict_do_nothing(constraint="uq_visitor_email_site_vid_email")` — a *named-constraint* reference, not `index_elements=[...]`. The repoint here is: change the `constraint=` string to the new bidx-keyed constraint's name (once named in the migration, e.g. `uq_visitor_email_site_vid_email_bidx`). Do not attempt an `index_elements=` swap on these two sites — it is the wrong API for `on_conflict_do_nothing`. (VALIDATE spot-check: confirmed via direct read of `events.py:485` and `click.py:117-128`.)

**Blast radius:** ~14 files (11 lookup sites across 6 files + 3 ON CONFLICT sites across 3 files, some overlapping) + 1 migration. Medium risk — this is the phase that fixes the riskiest site identified above.

**Regression guard note (for code review, not a code change):** any future raw insert to these 4 tables must populate bidx or the new bidx-keyed constraint will silently fail to dedupe. Call this out in the PR description.

**Verification Evidence:**

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Migration applies cleanly on dev DB; both old and new unique constraints exist | Hybrid (needs PG) | Migration correctness |
| `suppression.py` lookup finds a suppressed email via bidx after backfill | Fully-Automated (unit, mocked DB) + Hybrid (integration, real PG) | Suppression still enforced — GDPR/compliance-critical |
| `unsubscribe.py` lookup finds correct visitor via bidx | Hybrid (needs PG) | Unsubscribe flow correctness |
| **Riskiest-site regression test:** duplicate insert via `identity_resolver.py` upsert path triggers `ON CONFLICT` on `(fingerprint, email_bidx)` and updates rather than errors/duplicates | Hybrid (needs PG, integration marker) | The exact failure mode identified in "Riskiest Site" above is closed |
| Same riskiest-site test repeated for `events.py:485` and `click.py:127` upsert paths | Hybrid (needs PG) | Same |
| `sync.py:117-118` twitter_handle lookup returns correct match via decrypt-filter, capped at 50 rows | Fully-Automated (unit) | Non-bidx lookup path correctness |
| Failing stub | | |

```
test("should match suppressed email via email_bidx lookup after backfill", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: suppression lookup via bidx")
})
test("should upsert via ON CONFLICT on (fingerprint, email_bidx) without error on duplicate insert", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: identity_resolver ON CONFLICT bidx repoint")
})
test("should upsert visitor_emails via ON CONFLICT on (site_id, visitor_id, email_bidx) without error on duplicate insert", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: events/click ON CONFLICT bidx repoint")
})
```

Command (unit): `.venv/bin/python -m pytest tests/unit -k "suppression or unsubscribe or identity_resolver" -v`
Command (integration, needs PG+Redis per `docker-compose.yml`): `.venv/bin/python -m pytest tests/integration -m integration -k "bidx or conflict or suppression" -v`

**Rollback:** Migration is additive-only (new constraints, old ones untouched) — reversible via `alembic downgrade`. Code changes are revertible; since old plaintext constraints/queries still work throughout this phase, a partial rollback (revert code, keep migration) is also safe.

**Risk:** MEDIUM — this is the phase most likely to have a subtle bug (constraint semantics, NOT-NULL edge cases). Extra integration-test emphasis on the ON CONFLICT paths specifically because the failure mode is silent.

**Gate to advance:** All lookup/upsert verification evidence above green, INCLUDING the 3 riskiest-site regression tests. This gate is the hard prerequisite for even proposing Phase 5.

---

## Phase 4 — Read Cutover (30 sites → decrypt)

**Objective:** All 30 read sites consume decrypted values instead of plaintext columns. GDPR export decrypts explicitly. Prefer one centralized accessor over 30 scattered `decrypt_pii()` calls.

**Design decision — centralize via model-level accessor:** Add a `hybrid_property` (or plain `@property` + a shared helper function, whichever fits the existing SQLAlchemy model style in `apps/api/models/`) on each of the 4 models, e.g. `IdentifiedVisitor.pii_email` returning `pii_crypto.decrypt_pii(self.email_ciphertext or self.email)` (fallback to plaintext column covers the pre-backfill/pre-cutover window and any code path this plan misses). Do the same for `full_name` → `pii_name`, and per-provider handle fields → `pii_<handle>`.

Rationale: 30 scattered call sites is a maintenance and audit hazard (easy to miss one, easy for a future dev to reintroduce a raw plaintext read). One property per field per model is auditable via `grep -rn "\.email\b"` vs `.pii_email` diff, and keeps `decrypt_pii`'s tolerant behavior as the single safety net.

**Touchpoints — replace read pattern at all 30 sites (see Blast Radius table above for exact file:lines) with the new `.pii_*` accessor:**
- `routers/visitors.py` (10 sites: list/detail/GDPR export/etc.)
- `routers/campaigns.py` (5 sites)
- `services/campaign_sender.py` (3 sites)
- `services/hot_alert.py` (1 site, 2 fields)
- `services/csv_exporter.py` (4 sites)
- `services/outcome_digest.py` (1 site)
- `agents/segmenter.py` (2 sites, `build_visitor_profiles` — decrypt BEFORE `prompt_safety.sanitize_profiles`, not instead of; sanitize still runs on the now-plaintext value since it's the injection defense layer, unrelated to encryption)
- `routers/visitors_helpers.py` (1 site)
- `services/identity_resolver.py` (7 sites — read-only paths, distinct from the write/lookup sites already handled in Phases 1-3)
- `services/sync.py`, `services/social_intelligence.py` (enrichment handle reads)

**VALIDATE finding — the accessor pattern does NOT mechanically apply to every site; split into two edit patterns (confirmed by direct read of the actual code, not inferred):**

*Pattern A — full model instance already loaded (accessor works as-written):* most `identity_resolver.py`, `csv_exporter.py`, `campaign_sender.py`, `hot_alert.py`, `segmenter.py` sites load a full ORM row, then read `.email`/`.full_name` in Python. Swap `.email` → `.pii_email` directly — no other change needed.

*Pattern B — column-projection `select(Model.field, ...)` sites (accessor does NOT reach these — a Python `@property`/plain `hybrid_property` is never included in a SQL projection):* confirmed instances — `routers/visitors.py:122-123` and `:147-148` (`select(IdentifiedVisitor.visitor_id, IdentifiedVisitor.email, IdentifiedVisitor.full_name, ...)`), `routers/campaigns.py:734` (`select(EnrichmentProfile.linkedin_url)`), `services/outcome_digest.py:136` (`select(..., IdentifiedVisitor.full_name)`), `routers/visitors_helpers.py:61` (`select(IdentifiedVisitor.visitor_id, IdentifiedVisitor.email)`), `services/identity_resolver.py:149,281` (`select(VisitorEmail.email)` read-only uses, distinct from the lookup-site instances of the same lines already covered in Phase 3). For these sites: change the projection to select the `_ciphertext` column instead (e.g. `IdentifiedVisitor.email_ciphertext`) and call `pii_crypto.decrypt_pii(...)` explicitly on the fetched value in Python — do NOT attempt to reference `.pii_email` inside a `select()` call, it will raise or silently no-op depending on how it's defined. (This is roughly half of the 30 sites — the plan's single "replace `.email` with `.pii_email`" instruction as originally written undercounts the required design change here.)

**GDPR export special-case (`routers/visitors.py:368-376`, via `_row_to_dict()` in `visitors_helpers.py:36-38`):** confirmed by direct read — `_row_to_dict(obj)` returns `{c.key: getattr(obj, c.key) for c in obj.__table__.columns}`, i.e. it iterates the SQLAlchemy **Table** column set. A `hybrid_property`/`@property` accessor is not a table column and will **never** appear in this dict — adding `.pii_email` to the model does nothing for this call site by itself. Required fix: after building the export payload's `identified`/`enrichment`/`emails` dict entries via `_row_to_dict`, explicitly overwrite the PII fields with the decrypted accessor values (e.g. `identified_dict["email"] = identified.pii_email if identified else None`) before serialization — or write a small `_row_to_dict_decrypted(obj, pii_fields=[...])` variant for PII-bearing models and use it only for `identified`, `enrichment`, `emails` (the non-PII rows — `visitor`, `events`, `resolution_logs`, `segments`, `social_posts` — keep using plain `_row_to_dict`). Add an explicit test asserting the export payload contains decrypted plaintext, not ciphertext, in the `identified`/`enrichment`/`emails` sub-dicts specifically.

**Backstop note:** Phase 4's own exit gate (grep sweep below) is broad enough to catch `Model.email`-style column-projection reads textually (the pattern `\.email\b` matches `IdentifiedVisitor.email`), so an incomplete first pass on Pattern-B sites would be caught before the phase gate passes — but the categorization above should be followed from the start to avoid a wasted edit-then-fail-gate-then-refix cycle.

**Migration:** None.

**Blast radius:** ~20 files, ~30 read-site edits + 4 model files (new properties). Highest file-count phase; risk is behavioral correctness per-site rather than schema risk.

**Verification Evidence:**

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Model accessor unit tests: `.pii_email` on ciphertext-populated row returns original plaintext | Fully-Automated | Core decrypt correctness |
| Model accessor unit tests: `.pii_email` on a row with NULL ciphertext (mixed-data window) falls back to plaintext column, returns correct value | Fully-Automated | Mixed-data-window safety net |
| `routers/visitors.py` list/detail endpoint integration test: response contains decrypted email/name, not ciphertext blob | Hybrid (needs PG) | Primary user-facing read path |
| **GDPR export test:** exported payload contains plaintext email/name/handles, not ciphertext | Hybrid (needs PG) — HIGH-RISK class (PII/GDPR) so hybrid minimum is mandatory per harness rules | Export correctness — regulatory-relevant |
| `agents/segmenter.py` — `build_visitor_profiles` output passed to `sanitize_profiles` contains decrypted values, and prompt-injection sanitization still applies post-decrypt | Fully-Automated (unit) | AI-layer read path + prompt-safety chain intact |
| `csv_exporter.py` output rows contain decrypted values | Hybrid (needs PG) | Export correctness |
| Failing stub | | |

```
test("should return decrypted plaintext from .pii_email accessor when ciphertext is populated", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: pii_email accessor decrypt path")
})
test("should fall back to plaintext column when ciphertext is NULL (mixed-data window)", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: pii_email accessor fallback path")
})
test("should export decrypted plaintext (not ciphertext) in GDPR data export", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: GDPR export decrypt")
})
```

Command (unit): `.venv/bin/python -m pytest tests/unit -k "pii_email or pii_name or gdpr or segmenter" -v`
Command (integration): `.venv/bin/python -m pytest tests/integration -m integration -k "visitors or export or campaigns" -v`

**Rollback:** Per-site diffs are individually revertible; model accessors are additive (old plaintext columns still exist and are still populated by 5b hooks) so a partial revert of any single call site is safe throughout this phase.

**Risk:** MEDIUM-HIGH — highest file-count, and a missed site means a silent plaintext leak persisting after Phase 5 drops the column read fallback. Mitigate with a repo-wide `grep` sweep as a final verification step (see gate below) rather than relying solely on the file:line table.

**Gate to advance:** All 30 sites from the Blast Radius READ table are individually confirmed updated (grep sweep: `grep -rn "\.email\b\|\.full_name\b" apps/api/routers apps/api/services apps/api/agents` reviewed line-by-line, no remaining raw plaintext-column reads outside the model accessor definitions themselves and the fallback inside them). GDPR export test green. Full integration suite green.

---

## Phase 5 — Drop Plaintext Columns (DESTRUCTIVE — high-risk class, manual-first evidence required)

**Objective:** Plaintext `email`/`full_name`/handle columns are dropped from the 4 tables. This is the step that makes encryption-at-rest actually true (today, even after Phases 1-4, plaintext columns still physically exist on disk).

**Hard preconditions (all must hold before this phase is even scheduled for execution, not just planned):**
1. Phases 1-4 shipped and soaked in production for a stated period (recommend ≥ 2 weeks — long enough to catch any missed read/write site via error monitoring, not a hard technical requirement, a judgment call for the operator).
2. Phase 3's ON CONFLICT repoint verified in production (real duplicate-insert events observed to upsert correctly, not just in tests) — this is the harness's manual-first evidence requirement for this high-risk class (destructive schema/data mutation).
3. Grep sweep from Phase 4's gate re-run against the then-current `main` to catch any site added during the soak period that still reads plaintext.
4. Written manual evidence artifact (see below) reviewed by the operator before migration is applied to prod.

**Touchpoints (code):** Remove the plaintext-column fallback branch from the `.pii_*` model accessors added in Phase 4 (accessor becomes ciphertext-only, no `or self.email` fallback) — this is what actually "locks in" the cutover; leaving the fallback in place after the column is dropped would throw an `AttributeError` on every read, so this code change and the migration below must ship together.

**Touchpoints (migration):** New Alembic migration (chained after Phase 3's revision):
- Drop plaintext `email`, `full_name`, handle columns from `visitor_emails`, `identified_visitors`, `beam_identity_graph`, `enrichment_profiles`.
- Drop the now-superseded plaintext-keyed unique constraints (`uq_visitor_email_site_vid_email`, `uq_beam_identity_fp_email`) — the bidx-keyed constraints added in Phase 3 remain.
- **Irreversible in the conventional sense** — a `downgrade()` can re-add the columns but cannot repopulate plaintext data (that data is gone). Document this explicitly in the migration docstring.

**Blast radius:** 2 files (migration + accessor fallback removal) but the **consequence radius is every one of the 30+ sites from Phase 4** — if any was missed, this is where it breaks loudly (AttributeError / missing column) rather than silently, which is the intended fail-safe design (loud failure > silent plaintext leak).

**Manual-first evidence pack (required before EXECUTE per harness High-Risk Execution Handoff rule):**
1. Grep sweep output (Phase 5 precondition 3) showing zero remaining plaintext-column reads.
2. Production log/metrics excerpt showing Phase 3's ON CONFLICT paths firing successfully (no swallowed-exception spikes in `identity_resolver.py:836-838` or equivalent) over the soak window.
3. Staging/dev dry-run of the drop migration + full test suite green against a DB where plaintext has already been backfilled and cutover for ≥1 soak cycle.
4. Explicit operator sign-off note (this plan cannot self-authorize the destructive step).

**Execute-agent instruction — conform to the canonical `vc-risk-evidence-pack` schema:** the 4 artifacts above are the *content*; deliver them as the 5-JSON-artifact schema (`risk-gate.json`, `context-snippets.json`, `verification.json`, `review-decision.json`, `adversarial-validation.json` — the last is mandatory here since this is a destructive/irreversible data-mutation high-risk class) written into this task folder's `harness/` subdir (`process/general-plans/active/pii-at-rest_22-07-26/harness/`), not as free-form prose. `adversarial-validation.json` must at minimum cover: (a) a missed Phase-4 read site surfacing as an `AttributeError` in prod after drop, (b) the Phase-3 ON CONFLICT repoint silently regressing during the soak window without being caught by log monitoring, (c) backup/restore verified BEFORE the drop migration runs (data is not recoverable after).

**Verification Evidence:**

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Migration dry-run on a staging DB clone: columns dropped, application boots, smoke-test read/write/lookup paths all green | Hybrid (needs PG, staging-like env) | Migration safety |
| Full regression suite (Phases 1-4 test files) green against post-drop schema | Hybrid | No missed site — this is the loud-failure catch |
| Manual evidence pack reviewed (4 artifacts above) | Agent-Probe / manual review | High-risk class requires human judgment, not just automation |
| Failing stub | | |

```
test("should boot application and pass full read/write/lookup smoke suite against schema with plaintext columns dropped", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: post-drop-migration smoke suite")
})
```

Command: `.venv/bin/python -m pytest tests/ -v` (full suite, both unit and integration markers, against a migrated staging DB)

**Rollback:** `alembic downgrade` re-adds columns as NULL (data is NOT recoverable — this must be communicated as part of sign-off, not discovered during an incident). True rollback safety = do not run this migration against prod without a verified recent backup taken before the drop.

**Risk:** HIGH — destructive/irreversible data loss. This is the one phase in the plan that should NOT proceed to EXECUTE without explicit manual sign-off per the harness's High-Risk Execution Handoff protocol, regardless of how clean the automated gates look.

**Gate to advance:** All 4 manual-first evidence artifacts produced and explicitly accepted by the operator; staging dry-run + full regression suite green; sequencing precondition (Phase 3 verified in prod) confirmed. At-rest encryption is realized once this migration ships.

---

## Public Contracts

- No public API response shape changes (decrypted values are the same values callers already see today — the change is invisible to API consumers except that GDPR export payload shape is now explicitly asserted to be plaintext, matching current behavior).
- Internal contract change: model classes gain `.pii_email`/`.pii_name`/`.pii_<handle>` properties (Phase 4) — additive, not breaking.
- Schema contract change: plaintext columns removed (Phase 5) — internal only, no external schema is exposed.

## Test Infra Improvement Notes

(none identified yet)

## Resume and Execution Handoff

1. **Selected plan file path:** `process/general-plans/active/pii-at-rest_22-07-26/pii-at-rest_PLAN_22-07-26.md`
2. **Last completed phase or step:** None yet — plan just written, prior work (5a/5b) is pre-existing and already merged; this plan starts fresh at Phase 1.
3. **Validate-contract status:** pending (placeholder below — vc-validate-agent writes this section before EXECUTE)
4. **Supporting context files loaded:** `process/context/all-context.md`, `process/development-protocols/plan-lifecycle.md`, `process/context/tests/all-tests.md`; plus direct reads of `apps/api/services/pii_crypto.py`, `apps/api/services/pii_encryption_hooks.py`, `apps/api/services/known_hash.py` for spot-verification.
5. **Next step for a fresh agent picking up mid-execution:** Check which phase's Verification Evidence tests exist on disk yet (they do not, at plan-write time — see TDD stubs per phase) to determine last-completed phase; start at Phase 1 if none exist. Never start Phase 3 code changes without confirming Phase 1's gate (grep/dry-run of backfill script showing 0 remaining rows) has actually run against the target DB — do not trust the plan's "done" language alone.

## Validate Contract

Status: PASS
Date: 22-07-26
date: 2026-07-22
generated-by: outer-pvl

Parallel strategy: sequential (across phases) — within-Phase-4 fan-out is parallel-subagent-viable once split by file
Rationale: Score 3/7 (S2 schema/migration surface, S6 high-risk PII/GDPR + destructive class, S7 20+ files in blast radius). Dominant signal is the HARD SEQUENCING DEPENDENCY (Phase 1 backfill → Phase 3 lookup/ON-CONFLICT cutover → Phase 5 destructive drop; Phase 3 must be prod-verified before Phase 5 is even proposed) — this overrides the file-count signal that would otherwise suggest parallel subagents for the whole program. Recommend: EXECUTE phases 1→2→3→4→5 sequentially, one phase fully verified (gate green) before the next begins. WITHIN Phase 4 only, the ~20 files/~30 read-site edits have no inter-site dependency once the Pattern A / Pattern B categorization below is applied — parallel subagents (one per file group, e.g. routers/ vs services/ vs agents/) are viable there to cut wall-clock time, with the orchestrator merging and re-running the Phase 4 grep-sweep gate once all agents report done.

Test gates (C3 5-column table — ADDITIVE; existing consumers still parse the legacy line form below it):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC1 | Every pre-existing row backfilled with ciphertext(+bidx) | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_backfill_pii_ciphertext.py -v` + `--dry-run` zero-remaining-rows check (Hybrid, needs PG) | A |
| AC2 | `known_hash.email_hash` == `pii_crypto.email_hash` (pinned) | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_known_hash.py tests/unit/test_pii_crypto.py -v` | A |
| AC3 | 11 lookup sites + 3 ON CONFLICT sites use bidx | Hybrid (needs PG) | `.venv/bin/python -m pytest tests/unit -k "suppression or unsubscribe or identity_resolver" -v` (unit) + `tests/integration -m integration -k "bidx or conflict or suppression" -v` (integration, incl. the 3 riskiest-site regression tests) | A |
| AC4 | All 30 read sites (incl. GDPR export) return decrypted plaintext, zero raw plaintext-column reads outside accessor definitions | Hybrid (needs PG) — HIGH-RISK class (PII/GDPR), hybrid minimum mandatory | `.venv/bin/python -m pytest tests/unit -k "pii_email or pii_name or gdpr or segmenter" -v` (unit) + `tests/integration -m integration -k "visitors or export or campaigns" -v` (integration) + grep sweep `grep -rn "\.email\b\|\.full_name\b" apps/api/routers apps/api/services apps/api/agents` reviewed line-by-line | A |
| AC5 | Plaintext columns physically dropped, manual evidence pack accepted | Agent-Probe (manual review) + Hybrid (staging dry-run + full suite) | `.venv/bin/python -m pytest tests/ -v` against a migrated staging DB + 5-JSON-artifact `vc-risk-evidence-pack` (see Phase 5) reviewed by operator | D — backlog N/A; this is an inherent manual-sign-off gate for a destructive/irreversible class, not a coverage gap. Residual: automated tests cannot substitute for the human "is the soak window long enough" judgment call — this is by design (Agent-Probe tier), documented here as a named residual, not silently passed. |
| AC6 | Identity-graph/email dedup upsert never silently fails from Phase 3 onward | Hybrid (needs PG, integration marker) | Riskiest-site regression tests (`identity_resolver.py`, `events.py:485`, `click.py:127` ON CONFLICT paths) — same command as AC3 integration row | A |

gap-resolution legend: A — proven now (gate passes in this cycle). D — backlog test-building stub (named residual; keep-active; continue).

C-4 reconciliation: `strategy:` column above carries only Fully-Automated / Hybrid / Agent-Probe. No row uses Known-Gap as a proving strategy.

Legacy line form (retained so existing validate-contract consumers still parse):
- Phase 1 backfill: Fully-automated: `pytest tests/unit/test_backfill_pii_ciphertext.py -v` | hybrid: `--dry-run` against dev DB, precondition PG reachable
- Phase 2 hash unify: Fully-automated: `pytest tests/unit/test_known_hash.py tests/unit/test_pii_crypto.py -v`
- Phase 3 lookup/ON-CONFLICT cutover: Fully-automated: unit subset via `-k` filter | hybrid: `pytest tests/integration -m integration -k "bidx or conflict or suppression" -v`, precondition PG+Redis via `infra/docker-compose.yml`
- Phase 4 read cutover: Fully-automated: unit subset via `-k` filter | hybrid: `pytest tests/integration -m integration -k "visitors or export or campaigns" -v`, precondition PG reachable | agent-probe: grep-sweep line-by-line review
- Phase 5 destructive drop: hybrid: full suite against migrated staging DB | agent-probe: 5-JSON-artifact manual evidence pack, operator sign-off (`process/general-plans/active/pii-at-rest_22-07-26/harness/`)

Failing stubs: embedded verbatim in each phase's Verification Evidence section above (Phase 1 lines ~176-182, Phase 2 ~215-218, Phase 3 ~272-280, Phase 4 ~333-341, Phase 5 ~390-392 in this same file) — not duplicated here to avoid drift between two copies of the same stub text.

Dimension findings:
- Infra fit: PASS (fixed in plan) — 2 file-path errors found and corrected: `routers/sync.py`→`services/sync.py`, `routers/social_intelligence.py`→`services/social_intelligence.py` (spot-checked: files did not exist at the `routers/` path; confirmed present at `services/`, content matches the cited line numbers). Migration head `b8f3c1d92a47` confirmed current (no migration chains off it yet). `apps/api/scripts/` dir confirmed to exist for Phase 1's new file. `PII_HMAC_KEY`/`PII_ENCRYPTION_KEY` confirmed present in `config.py` with correct fallback chain.
- Test coverage: PASS (fixed in plan) — Phase 1/2 test commands referenced a `tests/unit/services/` path that does not match this repo's flat `tests/unit/` convention (existing `tests/unit/test_pii_crypto.py` confirmed on disk at the flat path); corrected. Phase 3/4/5 commands use `-k` filters or full-suite runs, unaffected. High-risk-class minimum-hybrid rule correctly applied to AC3/AC4/AC5. No Known-Gap rows exist without rationale (see AC5 residual note above).
- Breaking changes: PASS — no external API/response-shape changes; new model accessors (Phase 4) are additive; Phase 3's dual-constraint transition keeps both plaintext- and bidx-keyed uniqueness live until Phase 5; Phase 5's destructive drop is internal-schema-only (no external contract exposed) and is correctly gated as irreversible with explicit no-data-recovery language.
- Security surface: PASS (fixed in plan) — see `vc-security`-style review below. Root design (tolerant `decrypt_pii`, blind-index lookups, dual-write hooks already live, hard sequencing P1→P3→P5) is sound and independently re-verified against source (not re-derived from the plan's own claims). One material completeness gap found and fixed in plan text: the single-hybrid-property design for Phase 4 does not mechanically cover (a) `_row_to_dict()`-serialized sites — confirmed by direct read that it iterates `obj.__table__.columns`, which never includes a Python property — this is exactly the GDPR export path (`visitors.py:368-376`); or (b) column-projection `select(Model.field, ...)` sites — confirmed 6+ instances (`visitors.py:122-123/147-148`, `campaigns.py:734`, `outcome_digest.py:136`, `visitors_helpers.py:61`, `identity_resolver.py:149,281`) where a Python-level accessor is never reachable inside a SQL projection. Both are now called out in Phase 4 with the correct alternate edit pattern (select ciphertext column + explicit `decrypt_pii()`, or explicit dict-field overwrite for the export serializer). Phase 4's own grep-sweep exit gate is broad enough to have caught this as a backstop even if unfixed, so this was a plan-completeness/efficiency finding, not a silent-failure risk that would have shipped undetected.
- Phase 1 (Backfill) feasibility: PASS — mechanical feasibility confirmed (new-file-only, `apps/api/scripts/` exists, `pii_crypto.encrypt_pii`/`email_hash` behave exactly as the plan describes per direct source read). No gaps or conflicts found. Lowest-risk phase, correctly classified.
- Phase 2 (Unify hash) feasibility: PASS — `known_hash.py` and `pii_crypto.py` confirmed byte-identical algorithm + key-fallback chain by direct read; the proposed delegation fix is safe and behavior-preserving. No gaps or conflicts found.
- Phase 3 (Lookup cutover + ON CONFLICT repoint) feasibility: PASS (fixed in plan) — constraint names `uq_visitor_email_site_vid_email` / `uq_beam_identity_fp_email` confirmed to exist in `cd811a8b1f32_baseline_schema.py`. Gap found and fixed: `identity_resolver.py` repoints via `index_elements=[...]` but `events.py`/`click.py` use `.on_conflict_do_nothing(constraint="...")` (named-constraint reference) — a different repoint mechanism than the plan's original "same repoint pattern" phrasing implied; now called out explicitly. Highest-risk edit (per plan's own correct self-assessment): the 3 ON CONFLICT repoints, with adequate regression-test coverage already planned.
- Phase 4 (Read cutover) feasibility: PASS (fixed in plan) — see Security surface finding above; same root cause, now resolved via explicit Pattern A/B categorization and an explicit GDPR-export-serializer fix. Highest-risk edit: the 6+ column-projection sites, now correctly flagged.
- Phase 5 (Drop plaintext, destructive) feasibility: PASS — hard preconditions, irreversibility framing, and sequencing gate (Phase 3 must be prod-verified first) are all correctly designed. Fixed in plan: evidence pack reconciled to the canonical `vc-risk-evidence-pack` 5-JSON-artifact schema (was previously 4 prose bullets) with an explicit `adversarial-validation.json` content requirement, written to this task folder's `harness/` subdir per the artefact-colocation rule.

Open gaps: none unresolved — all findings from the two-layer fan-out were fixed directly in the plan text during this VALIDATE pass (see Dimension findings above for the "fixed in plan" detail per item).

What this coverage does NOT prove:
- AC1 (backfill): the Fully-Automated/Hybrid gates prove backfill correctness and idempotency on dev-scale data; they do NOT prove batch performance/lock behavior on prod-scale table sizes — that is only exercised by the actual staged production run (soak period referenced in Phase 5 precondition 1), not by any test in this plan.
- AC2 (hash unify): proves algorithmic equality for a fixed input set; does NOT prove there is no third undiscovered caller of either hash function outside the 5 known call sites (mitigated by the fact the function signature/name is unchanged, so no new caller can silently diverge).
- AC3 (lookup cutover): the integration tests prove correctness against a fresh dev/CI Postgres; they do NOT prove production behavior under real concurrent-insert race conditions at scale — that is what Phase 5 precondition 2 (real production observation over the soak window) is for, not automatable in this plan's test suite.
- AC4 (read cutover): unit + integration tests + grep sweep prove the known 30 sites are correctly cut over; they do NOT prove there is no 31st site outside the file list this plan enumerated (mitigated by the grep sweep being pattern-based, not list-based, so it would catch an unlisted site too — but only sites matching `\.email\b`/`\.full_name\b` textually; a site that already stores email under a differently-named local variable after an earlier `.email` read would not be caught by a second grep pass).
- AC5 (destructivedrop): the staging dry-run + full regression suite prove the migration mechanics are safe on a schema level; they explicitly do NOT prove readiness — that is an inherent human judgment call (soak-period-adequate, evidence-pack-accepted) that this plan correctly refuses to automate away.
- AC6 (riskiest-site): the regression tests prove the ON CONFLICT repoint works under a single-process test run; they do NOT prove behavior under the specific concurrency/connection-pool conditions of the real production upsert path (same limitation as AC3).

Gate: PASS (no FAILs, plan updated — all identified concerns fixed in plan text during this VALIDATE pass)
Accepted by: N/A — Gate is PASS, no unresolved concerns require acceptance. (Fixes applied by vc-validate-agent directly to plan text; see Dimension findings for the full "before/after" list — file-path corrections, test-path corrections, Phase 3 ON-CONFLICT-mechanism clarification, Phase 4 read-site Pattern A/B split + GDPR-serializer fix, Phase 5 evidence-pack schema conformance.)

## Autonomous Goal Block

SESSION GOAL: Finish PII encryption-at-rest — backfill existing rows, unify blind-index hash, cut lookups + ON CONFLICT to bidx, cut reads to decrypt, then drop plaintext columns.
Charter + umbrella plan: N/A — single plan (no umbrella/phase-program structure; this is one COMPLEX plan with 5 internally-ordered phases).
Autonomy: Standard /goal autonomous execution rules apply (see process/development-protocols/orchestration.md §Autonomy Mode). CONDITIONAL findings auto-apply and proceed; BLOCKED items go to backlog + continue with remaining phases; irreversible/outward-facing actions without explicit contract instruction are a hard stop.
Hard stop conditions / safety constraints:
- Phase 3 (bidx unique constraints + ON CONFLICT repoint) MUST land and be verified before Phase 5 (drop plaintext) is even proposed for execution — do not skip-ahead under any autonomy setting.
- Phase 5 (destructive column drop) requires the 5-JSON-artifact manual evidence pack (risk-gate.json / context-snippets.json / verification.json / review-decision.json / adversarial-validation.json) reviewed and explicitly accepted by the operator BEFORE the migration runs against prod — this is a hard stop even under full autonomy (irreversible data-loss action).
- Never log PII values (structlog events log keys/ids only, per repo convention) — applies to the backfill script's per-batch logging (Phase 1).
- Do not drop the plaintext-keyed unique constraints until Phase 5 (Phase 3 adds bidx constraints in parallel; both coexist through Phase 4).
Next phase: EXECUTE Phase 1 — process/general-plans/active/pii-at-rest_22-07-26/pii-at-rest_PLAN_22-07-26.md
Validate contract: inline in plan (`## Validate Contract` section, this file)
Execute start: Phase 1 fully-auto command `.venv/bin/python -m pytest tests/unit/test_backfill_pii_ciphertext.py -v` | e2e spec: none (backend-only, no e2e in blast radius) | probe scenario: Phase 1 `--dry-run` against dev DB (Hybrid, needs PG) | high-risk pack: yes — required at Phase 5 only, not Phases 1-4.
