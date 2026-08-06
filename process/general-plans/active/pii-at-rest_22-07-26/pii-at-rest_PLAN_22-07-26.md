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

## Run Disposition (07-08-26 — read first)

**This plan does NOT EXECUTE in the 07-08-26 autopilot run.** It is plan-complete-pending-prerequisites, not
archivable. Prerequisites that must ALL hold before any EXECUTE is authorized:

1. **(a) Phase-1 backfill RUN completed + verified — ✅ DONE 07-08-26 (operator-run against prod).**
   Full ritual executed via `railway run -s retarget-agent -- .venv/bin/python3.11 -m
   apps.api.scripts.backfill_pii_ciphertext`: dry-run showed pending `{visitor_emails: 4,
   identified_visitors: 12, beam_identity_graph: 0, enrichment_profiles: 6}`; real run updated
   exactly 22/22 (4+12+0+6, zero failures, zero no-update stalls); re-dry-run confirmed
   **0 pending across all 4 tables** (06:25 +07). Notably `beam_identity_graph` had **zero**
   un-backfilled rows — the graph write path has used the pii pattern since inception, so the
   NULL-bidx erasure-miss exposure had no rows actually affected. The GDPR prerequisite is
   satisfied; the erasure sweep now reaches every graph row. (Original requirement text retained
   below for audit: `--dry-run` → real run → re-`--dry-run` proving zero, live-DB operator action.)
2. **(b) Docker available** for the migration round-trip and every Hybrid gate. **Zero Hybrid gates in this plan
   have ever run**, in any session, against any database. AC3/AC4/AC5/AC6 therefore carry no runtime evidence
   whatsoever.
3. **(c) High-risk evidence pack** per `vc-risk-evidence-pack` — mandatory because this plan carries both a
   schema/data-migration class and a destructive/irreversible Phase 5. Deliver as the 5-JSON-artifact schema in
   `process/general-plans/active/pii-at-rest_22-07-26/harness/` (see Phase 5).
4. **(d) Re-run PVL from V1 at EXECUTE time.** Every `file:line` in this document is a dated snapshot against a
   dirty working tree, and anchors drift **within a single day** (uncommitted change count went 113 → 130 in one
   day). Do not execute against anchors validated on an earlier day.

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
3. All **15** predicate-position plaintext-PII lookup sites (10 equality/IN-list + 5 NOT-NULL/presence filters
   — count derived 07-08-26 from the REPAIRED 4-command grep set in §LOOKUP sites; the earlier "11" and "14"
   were both produced by the broken grep scope now fixed as F5) and all 3 `ON CONFLICT` upsert sites use the
   blind index (or, for `full_name`/`twitter_handle` where no bidx column exists, the documented
   ciphertext-presence / decrypt-filter shapes) — verified via Phase 3's lookup + riskiest-site regression tests, including production confirmation before Phase 5 proceeds.
4. All 35 read sites (including GDPR export) return decrypted plaintext via the centralized `.pii_*` accessor, with zero raw plaintext-column reads remaining outside the accessor definitions — verified via Phase 4's grep sweep + GDPR export test.
5. Plaintext columns are physically dropped from all 4 tables, with the manual-first evidence pack accepted by the operator beforehand — verified via Phase 5's staging dry-run + full regression suite + sign-off.
6. At no point does the identity-graph/email dedup upsert path silently fail (the "Riskiest Site" failure mode) — continuously verified from Phase 3 onward via the riskiest-site regression tests.

## Implementation Checklist / Phased Delivery Plan

This plan uses a 5-phase delivery structure (Phase 1 through Phase 5 below) as its implementation checklist — each phase section contains its own ordered touchpoints, migration steps, and verification gates in sequence. See "Phase Ordering" implicit in the phase numbering: 1 (backfill) -> 2 (unify hash) -> 3 (lookup cutover) -> 4 (read cutover) -> 5 (drop plaintext, destructive).

## Touchpoints

See the Blast Radius tables below (READ sites, WRITE sites, LOOKUP sites, ON CONFLICT constraints) for the complete file:line inventory. Summary by phase: Phase 1 — `scripts/backfill_pii_ciphertext.py` (**shipped `be39585`**; only the RUN remains).
Phase 2 — `services/known_hash.py` + test (**shipped `991fff3`**). Phase 3 — **15** predicate sites across 11 files
(re-derived 07-08-26 with the repaired grep set; was 11 across 6, then 14 across 9), 3 ON CONFLICT sites across 3 files, 1 new migration. Phase 4 — ~35 read sites across ~17 files, 4 model files (new accessors). Phase 5 — 1 migration (drop columns), accessor fallback removal in 4 model files.

## Verification Evidence

Full per-phase Verification Evidence tables (with exact pytest commands and TDD failing stubs) are embedded in each phase section below (Phase 1 through Phase 5). Summary: Phase 1-2 gates are Fully-Automated; Phase 3-4 gates are Fully-Automated + Hybrid (integration, needs PG+Redis per `docker-compose.yml`); Phase 5 gates are Hybrid + Agent-Probe (manual evidence pack review), reflecting its high-risk/destructive classification.

## Prior Research (verified, do not re-derive)

- Crypto: `apps/api/services/pii_crypto.py` — `encrypt_pii`/`decrypt_pii` (Fernet; `decrypt_pii` is **tolerant**: non-ciphertext input is returned as-is — this is what makes Phase 4 safe on partially-backfilled data). `email_hash` = HMAC-SHA256 blind index. `normalize_email`. Keys: `PII_ENCRYPTION_KEY`/`PII_HMAC_KEY`, falling back to `ENCRYPTION_KEY`.
- **5a DONE** — migration `e7b4c2f9a1d8` added `*_ciphertext` + `*_bidx` columns to `visitor_emails`, `identified_visitors`, `beam_identity_graph`, `enrichment_profiles`. Enrichment profile columns have ciphertext but **no bidx** (no blind-index lookup need there today).
- **5b DONE** — `apps/api/services/pii_encryption_hooks.py`: SQLAlchemy `before_insert`/`before_update` mapper events populate ciphertext/bidx for `IdentifiedVisitor`, `BeamIdentityNode`, `VisitorEmail`, `EnrichmentProfile`. 3 raw `pg_insert` sites bypass ORM hooks and are **already manually patched**: `identity_resolver.py:808-828` (B11), `events.py:479-488` (B12), `click.py:117-128` (B13).
- 2 lookups **already** on bidx: `identity_resolver.py:858` (`BeamIdentityNode.email_bidx`), `outcomes.py:490` (`VisitorEmail.email_bidx`) — both use `pii_crypto.email_hash`.
- **Migration head: DO NOT trust any hash written in this plan.** Re-derive live at apply time with
  `.venv/bin/python -m alembic -c apps/api/alembic.ini heads` (migrations live in `apps/api/migrations/versions/`).
  Never chain a new migration off a hash recorded in a plan document — concurrent programs in this repo move
  the head repeatedly (see `all-context.md` §Migration head status and the migration-collision memory note).
  *Dated snapshot only (07-08-26, branch `devjulley`, working tree dirty):* live head was `d1a6c4e93f27`
  (`add_erasure_requests`), with 4 uncommitted migrations present (`a4f2b8c15d70`, `b8e3f6a2c904`,
  `c9f4a7b31e85`, `d1a6c4e93f27`). This snapshot is expected to be stale — re-derive, do not reuse.
  The previously written head `b8f3c1d92a47` was stale and has been deleted from this plan.
- `apps/api/services/known_hash.py` confirmed on disk: `normalize_email` (17), `_hmac_key` (22), `email_hash` (35) — a byte-identical second implementation of the same algorithm using the same key fallback chain, serving only `known_contacts.email_hash`.

## Blast Radius

### READ sites (35) — plaintext PII consumed today, cut to decrypt in Phase 4

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
| 45-46 | `services/hot_contacts.py:111-112` | email/name | **NEW (found 07-08-26)** — `select(IdentifiedVisitor.email, IdentifiedVisitor.full_name)` column projection = **Pattern B** (see Phase 4). Absent from the 22-07-26 inventory |
| 47-50 | `services/daily_digest.py:393,395,406,408` | name/email/handles | **NEW (cycle-2 F4)** — whole file was unlisted. `select(IdentifiedVisitor.full_name, …, IdentifiedVisitor.email, EnrichmentProfile.linkedin_url, EnrichmentProfile.twitter_handle)` = **Pattern B** projections |
| 51-52 | `services/job_change_detector.py:272,495` | email / name | **NEW (cycle-2 F4)** — `select(IdentifiedVisitor.email)` and `select(IdentifiedVisitor.full_name)` = **Pattern B** |
| 53-54 | `services/graph_erasure.py:145,149` | email | **NEW (cycle-2 F4)** — `select(IdentifiedVisitor.email)` + `select(VisitorEmail.email)` = **Pattern B.** GDPR erasure path — this file is the same one whose `email_bidx` sweep drives the Phase-1-RUN prerequisite; getting its reads wrong compounds a compliance path |
| 55 | `jobs/backfill_enrichment.py:79` | email | **NEW (cycle-2 F4)** — `identified.email` on a loaded instance = **Pattern A** (simple `.pii_email` swap). In `apps/api/jobs/`, a directory no prior grep scanned |
| 56 | `tasks/resolution_tasks.py:155` | name | **NEW (cycle-2 F4)** — `identified.full_name` = **Pattern A**. In `apps/api/tasks/`, likewise never scanned |

(Line-count note: several lines carry 2 fields — 35 distinct *sites* after the cycle-2 F4 additions, ~54 distinct field-reads. Treat the file:line list above as authoritative, not the summed count.)

### WRITE sites (13) — 10 ORM (hooks already fire, no plan changes needed) + 3 raw (already patched, verify only)

- ORM (ALREADY correct via 5b hooks): `identity_resolver.py:737-747`, `visitors.py:766-779`, `enricher.py:354-366`, `enricher.py:835-840`, `visitors.py:796-808`, `visitors.py:979-982`, `visitors_helpers.py:307`, `visitors_helpers.py:365`.
- Raw `pg_insert` (ALREADY patched — B11/B12/B13): `identity_resolver.py:808-828`, `events.py:479-488`, `click.py:117-128`.
- **Regression guard (Phase 3 + ongoing):** any NEW raw insert added to these 4 tables must set ciphertext/bidx manually — add this to code-review checklist language in Phase 3's verification section; no code change needed today since no new raw insert exists.

### LOOKUP sites (15) — plaintext email/name/handle predicates, cut to bidx in Phase 3

**Anchor discipline (read before using any `file:line` below).** Every line number in this plan is a
**dated snapshot**, not a durable coordinate. Snapshot taken 07-08-26 against branch `devjulley` at commit
`5293cbc` **with 113 uncommitted changes present**. The prior inventory (written 22-07-26) had ~80% anchor
drift, so treat these the same way. Anchors are paired with a **content anchor** (the code pattern) and a
**reproducing grep** — match on content, then confirm the line, never the reverse:

**REPAIRED re-derivation commands (07-08-26 cycle-2 — F5 fix).** The previous commands had three
structural holes that caused two consecutive incomplete censuses. Every hole is fixed below and these are now
the ONLY sanctioned re-derivation commands: (1) **scope is all of `apps/api`** — the old commands scanned only
`services` + `routers` and never saw `apps/api/jobs/` or `apps/api/tasks/`, where real PII predicates live;
(2) **both operator spellings** — `.isnot(` AND `.is_not(` are both live in this repo; (3) **full field set** —
`full_name` and the handle/url fields are included, not just `email`/`twitter_handle`.

```
# 1 — equality / IN-list predicates (all of apps/api)
grep -rn "func\.lower(.*email\|\.email ==\|email\.in_(" apps/api --include="*.py" \
  | grep -v "_bidx\|email_hash\|body\.email\|admin\.email\|user\.email"
# 2 — NOT-NULL / IS-NULL email predicates, BOTH operator spellings
grep -rn "email\.isnot(\|email\.is_not(\|email\.is_(" apps/api --include="*.py"
# 3 — full_name predicates (this is the grep whose absence hid identity_resolver.py:1351)
grep -rn "full_name\.isnot(\|full_name\.is_not(\|full_name ==\|full_name\.in_(" apps/api --include="*.py"
# 4 — handle / url predicates (twitter_handle, linkedin_url, and any future handle field)
grep -rn "handle\.isnot(\|handle\.is_not(\|handle ==\|_url\.isnot(\|_url\.is_not(" apps/api --include="*.py"
```

All four commands must be run — running only #1 and #2 reproduces the exact defect that made this the second
consecutive short census.

| # | File:line (snapshot 07-08-26) | Content anchor | Notes |
|---|---|---|---|
| 1 | `services/suppression.py:78` | `func.lower(IdentifiedVisitor.email) == norm` | in `_cascade_suppress`. Note the suppression table's *own* lookup is already blind-index (`SuppressionEntry.email_hash`, `:43`) — only the cascade is plaintext |
| 2 | `services/suppression.py:86` | `VisitorEmail.email == norm` | |
| 3 | `services/suppression.py:96` | `func.lower(IdentifiedVisitor.email) == norm` | |
| 4 | `services/email_sender.py:33` | `func.lower(IdentifiedVisitor.email) == to_email...` | |
| 5 | `services/identity_resolver.py:1126` | `func.lower(IdentifiedVisitor.email) == data["email"]` | (was cited as `:713`) |
| 6 | `routers/unsubscribe.py:81` | `func.lower(IdentifiedVisitor.email) == email_lower` | |
| 7 | `routers/unsubscribe.py:99` | `func.lower(VisitorEmail.email) == email_lower` | |
| 8 | `services/identity_signals.py:77` | `func.lower(IdentifiedVisitor.email) == norm` | **NEW — 12th site, added by the owned-data-layer program after this plan was written.** Absent from the 22-07-26 inventory; Phase 5 would have dropped a column this live site still reads |
| 9 | `services/contact_importer.py:169` | `IdentifiedVisitor.email.in_([...])` | `IN`-list against plaintext; must become an `IN`-list of bidx hashes. **See the C7 coordination note below — this is one leg of a 3-line coordinated edit.** (`:167` was previously listed here as a lookup; it is a *projection*, reclassified to Phase 4 Pattern B — see C7) |
| 11 | `services/leadpipe_webhook.py:186` | `func.lower(VisitorEmail.email) == email` | **NEW — same** |
| 12 | `routers/visitors_helpers.py:74` | `IdentifiedVisitor.email.isnot(None)` | NOT-NULL filter (was cited as `:63`). Confirm bidx non-null semantics match; note `:72` also *projects* `.email` — that projection is a Phase 4 Pattern-B read site, listed separately |
| 13 | `services/identity_resolver.py:1386` | `BeamIdentityNode.email.isnot(None)` | NOT-NULL filter (was cited as `:886`). Nearby `:1350` is **already on bidx** (`BeamIdentityNode.email_bidx == bidx`) — matches the "2 already on bidx" note above |
| 14 | `services/sync.py:117-118` | `EnrichmentProfile.twitter_handle.isnot(None)` + `!= ""` | **twitter_handle — no bidx column exists.** Cannot query-filter by bidx. Must load candidate rows and decrypt-filter in Python; the existing `.limit(50)` already bounds the cost |
| 14 | `services/identity_resolver.py:1351` | `BeamIdentityNode.full_name.isnot(None)` | **NEW (cycle-2 F4).** **THIRD EDIT SHAPE — not a bidx swap.** `beam_identity_graph` has `full_name_ciphertext` (`models/beam_identity.py:57`) but **NO `full_name_bidx`** — so this predicate cannot become a bidx filter at all. Required edit shape: `BeamIdentityNode.full_name_ciphertext.isnot(None)` (presence-only predicate; no value comparison is possible without decrypt). Phase 4/5 disposition: the *presence* semantics are preserved by the ciphertext column, so no decrypt-filter is needed here — but if a value comparison is ever added, it must follow the `sync.py:117-118` load-and-decrypt-in-Python pattern, not a bidx pattern. **Second §Riskiest-Site location:** this predicate sits inside `_graph_email_lookup`'s `try/except`, which swallows to `logger.debug("graph_email_lookup_failed")` — post-Phase-5 a missed edit here fails **silently** and degrades the owned/no-provider-spend path into paid re-resolution, with no error surfaced. Treat with the same sequencing rigor as the ON CONFLICT sites |
| 15 | `jobs/backfill_enrichment.py:62` | `IdentifiedVisitor.email.is_not(None)` | **NEW (cycle-2 F4).** Missed twice because of BOTH F5 holes at once: `.is_not(` spelling AND `apps/api/jobs/` was never scanned. Standard NOT-NULL → `email_bidx.isnot(None)` swap |

**Deliberately out of scope (matched the grep, not one of the 4 target tables):** `services/auth.py:43`
(`User`), `routers/billing.py:538` (`User`), `routers/demo.py:648` (`WaitlistSignup`), `routers/privacy.py:103,109`
(`body.email` request payload / `admin.email` on a `User` row).

### Uniqueness / ON CONFLICT constraints (Phase 3 migration)

| ID | Constraint | Referenced by | Change |
|---|---|---|---|
| C14 | `uq_visitor_email_site_vid_email` (`site_id, visitor_id, email`) | `events.py:818`, `click.py:127` (`ON CONFLICT`) — snapshot 07-08-26 | Add parallel bidx-keyed unique constraint; repoint `ON CONFLICT index_elements` to bidx version; keep plaintext constraint until Phase 5 |
| C15 | `uq_beam_identity_fp_email` (`fingerprint, email`) | `identity_resolver.py:1305-1306` (`on_conflict_do_update`) — snapshot 07-08-26 (was cited as `:819-820`) | Same treatment |
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

## Phase 1 — Backfill Existing Rows — ✅ CODE DONE (script), ⚠️ RUN STILL PENDING (GDPR prerequisite)

**Status (07-08-26):** **CODE DONE + COMMITTED** at `be39585` ("feat(pii): add idempotent ciphertext/bidx
backfill script (Phase 1)"). `apps/api/scripts/backfill_pii_ciphertext.py` exists on disk (322 lines) and
implements every design bullet below, plus a defensive infinite-loop guard the plan did not specify
(`backfill_batch_no_updates_stop`). Unit tests `tests/unit/test_backfill_pii_ciphertext.py` exist and pass.
Do NOT re-implement this phase.

**⚠️ PRIORITY RECLASSIFICATION (07-08-26) — the backfill RUN is now a GDPR compliance PREREQUISITE, not
optional prep, and is re-prioritized AHEAD of Phase 3.** The "Risk: LOW / optional prep" framing below is
superseded. Reason: `apps/api/services/graph_erasure.py:330-341` (`_graph_delete_stmt`, uncommitted
graph-erasure work) deletes cross-tenant shared-graph rows via
`BeamIdentityNode.email_bidx == func.any(...)`. A pre-backfill row has `email_bidx = NULL`, and **NULL never
matches** — so the cross-tenant GDPR erasure sweep **silently fails to delete un-backfilled graph rows**
whose only match key is email. The `fingerprint` / `fingerprint_v3` OR-branches mitigate only where a
fingerprint also matches. This is exactly the NULL-bidx failure mode this plan already documents in
§Mixed-Data Window, now manifesting in a live compliance path.

**Remaining work for this phase is operational, not implementation:** run the script (`--dry-run` first,
then a real run) against each target database and capture the zero-remaining-rows evidence. No
`--dry-run` evidence exists anywhere in this repo today — the script has never been run against any
database, dev or prod.

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
~~Failing stubs~~ — **SATISFIED 07-08-26, struck.** Real tests exist on disk in
`tests/unit/test_backfill_pii_ciphertext.py` and pass; the TDD stubs are no longer applicable.

Command: `.venv/bin/python -m pytest tests/unit/test_backfill_pii_ciphertext.py -v`

**Rollback:** Backfill only writes to already-nullable ciphertext/bidx columns; plaintext columns are untouched. Rollback = no-op (leave populated columns as-is; they're inert until Phase 3/4 read them).

**Risk:** ~~LOW~~ → **the CODE is low-risk and reversible; NOT RUNNING it is now a MEDIUM GDPR-compliance
risk** (see the priority reclassification at the top of this phase — un-backfilled rows are invisible to
the `graph_erasure.py` cross-tenant deletion sweep). The mechanics are unchanged: no schema change, no
behavior change.

**Gate to advance:** `--dry-run` on dev DB reports 0 remaining un-backfilled rows across all 4 tables after a real run; unit tests green.

---

## Phase 2 — Unify Blind Index Implementation — ✅ CODE DONE

**Status (07-08-26):** **DONE + COMMITTED** at `991fff3` ("refactor(security): collapse known_hash into
pii_crypto delegation"). `apps/api/services/known_hash.py` `email_hash()` now reads
`return pii_crypto.email_hash(email)`; the public `email_hash` / `normalize_email` names are preserved
exactly as planned, so all 5 call sites are untouched. Pinning tests `tests/unit/test_known_hash.py` +
`tests/unit/test_pii_crypto.py` exist and pass. Do NOT re-implement this phase.

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
~~Failing stub~~ — **SATISFIED 07-08-26, struck.** The equality-pinning test exists on disk and passes.

Command: `.venv/bin/python -m pytest tests/unit/test_known_hash.py tests/unit/test_pii_crypto.py -v`

**Rollback:** Revert single-file edit; trivial `git revert`.

**Risk:** LOW, fully reversible.

**Gate to advance:** Equality test green; full existing `known_contacts`-related test suite green with no changes required to those tests.

---

## Phase 3 — Lookup Cutover + Constraint Repoint (the safety-critical gate for Phase 5)

**Objective:** All 15 predicate-position plaintext-PII sites move to bidx (or the documented ciphertext-presence / decrypt-filter shape where no bidx column exists); the 3 `ON CONFLICT` upserts move their `index_elements` to bidx-backed unique constraints; both plaintext and bidx unique constraints coexist during the transition window (removed in Phase 5).

**Prerequisite (HARD — now doubly binding):** Phase 1 backfill **actually RUN and verified** via its
zero-remaining-rows gate. The Phase 1 *script* is shipped, but the *run* has never happened — and per the
Phase 1 priority reclassification, that run is also a standalone GDPR prerequisite. Phase 1 backfill fully complete (verified via gate) — bidx-keyed lookups against NULL bidx never match.

**Touchpoints (code):**
(Anchors below are 07-08-26 snapshots re-derived by the grep commands in the LOOKUP table — match on the
content anchor, then confirm the line.)

- `services/suppression.py:78,86,96` — email-equality → `email_bidx == pii_crypto.email_hash(normalize_email(email))` (was cited as `61,69,79`)
- `services/email_sender.py:33` — same pattern
- `services/identity_resolver.py:1126` — same pattern (was cited as `:713`)
- `routers/unsubscribe.py:81,99` — same pattern
- `services/identity_signals.py:77` — same pattern (**site not in the original inventory**)
- `services/contact_importer.py:167,169` — equality + `IN`-list → `IN`-list of bidx hashes (**not in the original inventory**)
- `services/leadpipe_webhook.py:186` — same pattern (**not in the original inventory**)
- `routers/visitors_helpers.py:74` — NOT-NULL filter: confirm swap to `email_bidx IS NOT NULL` preserves intended semantics (should — bidx is populated exactly when email is present, post-backfill) (was cited as `:63`)
- `services/identity_resolver.py:1386` — same NOT-NULL swap; `:1350` is already on bidx, leave it (was cited as `886,859`)
- `services/identity_resolver.py:1351` — **THIRD EDIT SHAPE, not a bidx swap.** `BeamIdentityNode.full_name.isnot(None)` → `BeamIdentityNode.full_name_ciphertext.isnot(None)` (no `full_name_bidx` column exists; see LOOKUP row 14). **Silent-failure site** — inside `_graph_email_lookup`'s swallowing `try/except` (`graph_email_lookup_failed` debug log); a miss here is invisible, exactly like the §Riskiest Site pattern. Add an explicit regression test that this branch still matches after the swap.
- `jobs/backfill_enrichment.py:62` — `IdentifiedVisitor.email.is_not(None)` → `email_bidx.isnot(None)` (**`apps/api/jobs/` is a directory no prior grep in this plan scanned**)
- `services/sync.py:117-118` — **no bidx column for twitter_handle.** Load candidate rows (bounded query, e.g. by site_id + recency), decrypt each `handle_ciphertext` in Python, filter for match, **cap at 50 rows** to bound cost. Document this as the one lookup site that stays O(n) by design.

**Touchpoints (migration):** New Alembic migration chained off the **live** head — re-derive it at apply time
with `.venv/bin/python -m alembic -c apps/api/alembic.ini heads`; never chain off a hash written in this plan
(see §Prior Research "Migration head"). Confirm a single head before and after adding the revision:
- Add unique constraint on `beam_identity_graph(fingerprint, email_bidx)` — parallel to existing `uq_beam_identity_fp_email`.
- Add unique constraint on `visitor_emails(site_id, visitor_id, email_bidx)` — parallel to existing `uq_visitor_email_site_vid_email`.
- Do NOT drop the plaintext-keyed constraints yet (Phase 5 only).

**Touchpoints (ON CONFLICT repoint):**
- `identity_resolver.py:1305-1306` (snapshot; was cited as `:819-820`) — `index_elements=["fingerprint","email"]` → `["fingerprint","email_bidx"]` (now targets the new constraint)
- `events.py:818` (snapshot; was cited as `:485`) and `click.py:127` — **NOT the same repoint mechanism as above.** Both use `.on_conflict_do_nothing(constraint="uq_visitor_email_site_vid_email")` — a *named-constraint* reference, not `index_elements=[...]`. The repoint here is: change the `constraint=` string to the new bidx-keyed constraint's name (once named in the migration, e.g. `uq_visitor_email_site_vid_email_bidx`). Do not attempt an `index_elements=` swap on these two sites — it is the wrong API for `on_conflict_do_nothing`. (VALIDATE spot-check: confirmed via direct read of `events.py:485` and `click.py:117-128`.)

**Blast radius:** ~14 files (15 predicate sites across 11 files + 3 ON CONFLICT sites across 3 files, some overlapping) + 1 migration. Medium risk — this is the phase that fixes the riskiest site identified above.

**C7 — coordinated 3-line edit at `services/contact_importer.py:167`/`:169`/`:178` (do NOT split).**
`:167` is `select(func.lower(IdentifiedVisitor.email))` — a **projection**, not a filter (it was previously
misfiled as a lookup site). Its result populates the `already` set, which is compared at `:178`
(`if contact["email"] in already`) against **plaintext** CSV input. The three lines are one unit:

| Line | Today | After |
|---|---|---|
| `:167` | `select(func.lower(IdentifiedVisitor.email))` | `select(IdentifiedVisitor.email_bidx)` |
| `:169` | `IdentifiedVisitor.email.in_([c["email"] for c in valid])` | `IdentifiedVisitor.email_bidx.in_([pii_crypto.email_hash(normalize_email(c["email"])) for c in valid])` |
| `:178` | `if contact["email"] in already` | `if pii_crypto.email_hash(normalize_email(contact["email"])) in already` |

If the projection/filter are converted but `:178` is not, `already` holds hashes while the comparison supplies
plaintext — every membership test misses, and re-uploading the same list silently becomes a **duplicate-row
generator**, which the code's own comment at `:161-162` states must not happen. Convert all three together, in
one commit, with a dedup regression test (re-upload the same CSV twice → zero new rows).

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

**Commands (REPAIRED 07-08-26 — F6 fix; the old `-k` filters are void).** The prior filter
`-k "suppression or unsubscribe or identity_resolver"` collected 54 of 2076 tests and structurally could not
reach the covering test files for 5 of the sites it claimed to prove (`test_identity_signals.py`,
`test_contact_importer.py`, `test_leadpipe_webhook.py`, `test_email_sender_branding.py`, sync tests). Covering
test files are now **named explicitly** so the gate cannot silently under-cover a grown census:

Command (unit): `.venv/bin/python3.11 -m pytest tests/unit/test_suppression.py tests/unit/test_suppression_list.py tests/unit/test_identity_signals.py tests/unit/test_contact_importer.py tests/unit/test_contact_import_merge.py tests/unit/test_leadpipe_webhook.py tests/unit/test_email_sender_branding.py tests/unit/test_identity_resolver_parallel.py tests/unit/test_linkedin_sync.py tests/unit/test_graph_erasure.py -v`
Command (integration, needs PG+Redis per `infra/docker-compose.yml`): `.venv/bin/python3.11 -m pytest tests/integration/test_suppression_list.py tests/integration/test_identity_signals_persistence.py tests/integration/test_leadpipe_webhook_persistence.py tests/integration/test_contact_import.py -m integration -v`

Site → covering test file map (every census row must appear here; add a row when the census grows):

| Census site(s) | Covering test file |
|---|---|
| `suppression.py:78,86,96` | `tests/unit/test_suppression.py`, `tests/unit/test_suppression_list.py`, `tests/integration/test_suppression_list.py` |
| `email_sender.py:33` | `tests/unit/test_email_sender_branding.py` |
| `identity_resolver.py:1126`, `:1351`, `:1386`, ON CONFLICT `:1305-1306` | `tests/unit/test_identity_resolver_parallel.py` + new integration riskiest-site test |
| `unsubscribe.py:81,99` | new unit test (**no covering test file exists today** — must be created in Phase 3) |
| `identity_signals.py:77` | `tests/unit/test_identity_signals.py`, `tests/integration/test_identity_signals_persistence.py` |
| `contact_importer.py:167,169,178` (C7 coordinated edit) | `tests/unit/test_contact_importer.py`, `tests/unit/test_contact_import_merge.py`, `tests/integration/test_contact_import.py` |
| `leadpipe_webhook.py:186` | `tests/unit/test_leadpipe_webhook.py`, `tests/integration/test_leadpipe_webhook_persistence.py` |
| `visitors_helpers.py:74` | new unit test (**none today** — create in Phase 3) |
| `sync.py:117-118` | `tests/unit/test_linkedin_sync.py` |
| `jobs/backfill_enrichment.py:62` | new unit test (**none today** — create in Phase 3) |
| `events.py:817-818`, `click.py:127` ON CONFLICT | new integration riskiest-site tests |

The four "no covering test file exists today" rows are Phase-3 checklist items, not Known-Gaps — each must have
a real test before the Phase 3 gate can pass.

**Rollback:** Migration is additive-only (new constraints, old ones untouched) — reversible via `alembic downgrade`. Code changes are revertible; since old plaintext constraints/queries still work throughout this phase, a partial rollback (revert code, keep migration) is also safe.

**Risk:** MEDIUM — this is the phase most likely to have a subtle bug (constraint semantics, NOT-NULL edge cases). Extra integration-test emphasis on the ON CONFLICT paths specifically because the failure mode is silent.

**Gate to advance:** All lookup/upsert verification evidence above green, INCLUDING the 3 riskiest-site regression tests. This gate is the hard prerequisite for even proposing Phase 5.

---

## Phase 4 — Read Cutover (30 sites → decrypt)

**Objective:** All 35 read sites consume decrypted values instead of plaintext columns. GDPR export decrypts explicitly. Prefer one centralized accessor over 30 scattered `decrypt_pii()` calls.

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
- `services/daily_digest.py` (4 Pattern-B projections — whole file added cycle 2)
- `services/job_change_detector.py` (2 Pattern-B projections)
- `services/graph_erasure.py` (2 Pattern-B projections, GDPR path)
- `jobs/backfill_enrichment.py`, `tasks/resolution_tasks.py` (Pattern-A instance reads — **`apps/api/jobs/` and `apps/api/tasks/` are directories no grep in the pre-cycle-2 plan ever scanned; they must be in every sweep from now on**)

**VALIDATE finding — the accessor pattern does NOT mechanically apply to every site; split into two edit patterns (confirmed by direct read of the actual code, not inferred):**

*Pattern A — full model instance already loaded (accessor works as-written):* most `identity_resolver.py`, `csv_exporter.py`, `campaign_sender.py`, `hot_alert.py`, `segmenter.py` sites load a full ORM row, then read `.email`/`.full_name` in Python. Swap `.email` → `.pii_email` directly — no other change needed.

*Pattern B — column-projection `select(Model.field, ...)` sites (accessor does NOT reach these — a Python `@property`/plain `hybrid_property` is never included in a SQL projection):* confirmed instances — `routers/visitors.py:122-123` and `:147-148` (`select(IdentifiedVisitor.visitor_id, IdentifiedVisitor.email, IdentifiedVisitor.full_name, ...)`), `routers/campaigns.py:734` (`select(EnrichmentProfile.linkedin_url)`), `services/outcome_digest.py:136` (`select(..., IdentifiedVisitor.full_name)`), `routers/visitors_helpers.py:61` (`select(IdentifiedVisitor.visitor_id, IdentifiedVisitor.email)`), `services/identity_resolver.py:149,281` (`select(VisitorEmail.email)` read-only uses, distinct from the lookup-site instances of the same lines already covered in Phase 3). For these sites: change the projection to select the `_ciphertext` column instead (e.g. `IdentifiedVisitor.email_ciphertext`) and call `pii_crypto.decrypt_pii(...)` explicitly on the fetched value in Python — do NOT attempt to reference `.pii_email` inside a `select()` call, it will raise or silently no-op depending on how it's defined. (This is roughly half of the 30 sites — the plan's single "replace `.email` with `.pii_email`" instruction as originally written undercounts the required design change here.)

**GDPR export special-case (`routers/visitors.py:368-376`, via `_row_to_dict()` in `visitors_helpers.py:36-38`):** confirmed by direct read — `_row_to_dict(obj)` returns `{c.key: getattr(obj, c.key) for c in obj.__table__.columns}`, i.e. it iterates the SQLAlchemy **Table** column set. A `hybrid_property`/`@property` accessor is not a table column and will **never** appear in this dict — adding `.pii_email` to the model does nothing for this call site by itself. Required fix: after building the export payload's `identified`/`enrichment`/`emails` dict entries via `_row_to_dict`, explicitly overwrite the PII fields with the decrypted accessor values (e.g. `identified_dict["email"] = identified.pii_email if identified else None`) before serialization — or write a small `_row_to_dict_decrypted(obj, pii_fields=[...])` variant for PII-bearing models and use it only for `identified`, `enrichment`, `emails` (the non-PII rows — `visitor`, `events`, `resolution_logs`, `segments`, `social_posts` — keep using plain `_row_to_dict`). Add an explicit test asserting the export payload contains decrypted plaintext, not ciphertext, in the `identified`/`enrichment`/`emails` sub-dicts specifically.

**Backstop note:** Phase 4's own exit gate (grep sweep below) is broad enough to catch `Model.email`-style column-projection reads textually (the pattern `\.email\b` matches `IdentifiedVisitor.email`), so an incomplete first pass on Pattern-B sites would be caught before the phase gate passes — but the categorization above should be followed from the start to avoid a wasted edit-then-fail-gate-then-refix cycle.

**Migration:** None.

**Blast radius:** ~25 files, ~35 read-site edits + 4 model files (new properties). Highest file-count phase; risk is behavioral correctness per-site rather than schema risk.

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

**Commands (REPAIRED 07-08-26 — F6 fix).** The old unit filter `-k "pii_email or pii_name or gdpr or
segmenter"` could not reach the newly-added Pattern-B files. Covering files named explicitly:

Command (unit): `.venv/bin/python3.11 -m pytest tests/unit/test_daily_digest.py tests/unit/test_job_change_detector.py tests/unit/test_graph_erasure.py tests/unit/test_contact_importer.py -k "pii_email or pii_name or gdpr or segmenter or digest or job_change or erasure or import" -v`
Command (integration): `.venv/bin/python3.11 -m pytest tests/integration -m integration -k "visitors or export or campaigns or hot_contacts or contact_import" -v`

**Rollback:** Per-site diffs are individually revertible; model accessors are additive (old plaintext columns still exist and are still populated by 5b hooks) so a partial revert of any single call site is safe throughout this phase.

**Risk:** MEDIUM-HIGH — highest file-count, and a missed site means a silent plaintext leak persisting after Phase 5 drops the column read fallback. Mitigate with a repo-wide `grep` sweep as a final verification step (see gate below) rather than relying solely on the file:line table.

**Gate to advance (REPAIRED 07-08-26 — F5 fix; the old 3-directory sweep is void).** The prior exit-gate sweep
scanned only `apps/api/routers apps/api/services apps/api/agents` and therefore could not see
`apps/api/jobs/backfill_enrichment.py:62,79` or `apps/api/tasks/resolution_tasks.py:155` — the gate had a hole in
exactly the same place the inventory did, so the plan's "pattern-based gate is self-correcting" mitigation did
not hold. The sweep is now **repo-wide across all of `apps/api`** and covers all PII fields:

```
# ALL of apps/api — never a directory subset
grep -rn "\.email\b\|\.full_name\b\|\.twitter_handle\b\|\.linkedin_url\b" apps/api --include="*.py" \
  | grep -v "_bidx\|_ciphertext\|pii_email\|pii_name\|pii_twitter_handle\|pii_linkedin_url"
```

Review line-by-line; zero remaining raw plaintext-column reads may survive outside the model accessor
definitions themselves (and the fallback branch inside them) and the documented out-of-scope `User` /
`WaitlistSignup` matches. Additionally: all 35 sites from the Blast Radius READ table individually confirmed
updated; GDPR export test green; full integration suite green.

**Known residual (unchanged, now explicit):** a text sweep cannot catch a site that reads `.email` once into a
differently-named local and then consumes that local, nor dynamic access (`getattr(obj, "email")`), nor a raw
SQL string naming the column. Run `grep -rn "getattr(.*\"email\"\|getattr(.*'email'" apps/api --include="*.py"`
as a supplementary check; the local-variable shape has no mechanical gate and is recorded in §Test Infra
Improvement Notes as a named residual.

---

## Phase 5 — Drop Plaintext Columns (DESTRUCTIVE — high-risk class, manual-first evidence required)

**Objective:** Plaintext `email`/`full_name`/handle columns are dropped from the 4 tables. This is the step that makes encryption-at-rest actually true (today, even after Phases 1-4, plaintext columns still physically exist on disk).

**Hard preconditions (all must hold before this phase is even scheduled for execution, not just planned):**
1. Phases 1-4 shipped and soaked in production for a stated period (recommend ≥ 2 weeks — long enough to catch any missed read/write site via error monitoring, not a hard technical requirement, a judgment call for the operator).
2. Phase 3's ON CONFLICT repoint verified in production (real duplicate-insert events observed to upsert correctly, not just in tests) — this is the harness's manual-first evidence requirement for this high-risk class (destructive schema/data mutation).
3. Grep sweep from Phase 4's **repaired** gate (repo-wide across all of `apps/api`, all PII fields, both operator spellings — NOT the void 3-directory version) re-run against the then-current `main` to catch any site added during the soak period that still reads plaintext.
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

- **No Hybrid gate in this plan has ever been executed.** Every Phase 3/4/5 gate needs PG+Redis via
  `infra/docker-compose.yml`, and Docker was unavailable in every session that has touched this plan. AC3/AC4/
  AC5/AC6 therefore carry zero runtime evidence. Closing this needs a working local Docker (or a CI lane), not
  a new test.
- **Anchor-drift-resistant gates only.** Phase 4's exit gate is a *pattern-based* grep sweep rather than a
  list-based checkoff, which is why ~80% inventory drift cost an edit cycle instead of shipping a silent leak.
  Prefer pattern gates over enumerated-site gates for the remaining phases.
- **Grep sweep blind spot:** the Phase 4 sweep would NOT catch a site that reads `.email` once into a
  differently-named local and then consumes that local. No test currently covers that shape.
- **F5/F6 root cause (cycle 2) — the census mechanism was the defect, not the census.** Two consecutive PVL
  passes produced a short inventory because the re-derivation greps AND Phase 4's exit-gate sweep shared three
  holes: directory scope (`apps/api/jobs/`, `apps/api/tasks/` never scanned), operator variant (`.is_not(` vs
  `.isnot(`), and field scope (`full_name` never grepped). Both surfaces are now repaired and must stay in sync —
  **if a new PII field or a new `apps/api` subpackage appears, update the 4 re-derivation commands AND the Phase 4
  exit-gate sweep in the same edit.** A gate that cannot see the directory where misses live provides none of the
  protection it appears to.
- **Gate filters must grow with the census.** Cycle 1 grew the inventory 11→14 but left the `-k` filters
  untouched, so the gate provably under-covered its own criterion. Gates now name test files explicitly and carry
  a site→test-file map; adding a census row requires adding a map row.
- **4 census sites have no covering test file at all today** (`unsubscribe.py:81,99`, `visitors_helpers.py:74`,
  `jobs/backfill_enrichment.py:62`, and the `events.py`/`click.py` ON CONFLICT paths). These are Phase-3
  test-building work items, not Known-Gaps.
- **Named residual — local-variable shape.** No mechanical gate catches a site that reads `.email` into a
  differently-named local, nor `getattr(obj, "email")`, nor raw SQL naming the column. Supplementary
  `getattr` grep is in the Phase 4 gate; the local-variable shape stays a residual.
- Reminder: `.venv/bin/pytest` is broken in this repo (stale shebang) — always use
  `.venv/bin/python3.11 -m pytest` (explicit interpreter; `.venv/bin/python` also works but `python3.11` is the
  form proven working from repo root and worktrees).

## Resume and Execution Handoff

1. **Selected plan file path:** `process/general-plans/active/pii-at-rest_22-07-26/pii-at-rest_PLAN_22-07-26.md`
2. **Last completed phase or step:** **Phase 2 (code)** — re-baselined 07-08-26. Phase 1 is CODE DONE
   (`be39585`) and Phase 2 is DONE (`991fff3`); combined gate
   `.venv/bin/python -m pytest tests/unit/test_backfill_pii_ciphertext.py tests/unit/test_known_hash.py tests/unit/test_pii_crypto.py -q`
   → 24 passed. **The plan does NOT start fresh at Phase 1** (the earlier "starts fresh" wording was wrong
   and is deleted). Next implementation work is Phase 3 — but the Phase 1 backfill **RUN** (operational, never
   executed anywhere) is a GDPR prerequisite that comes first.
3. **Validate-contract status:** written 07-08-26 — `Gate: BLOCKED` at cycle 1 and again at cycle 2.
   **Cycle-1 supplement** closed F1/F2/F3/C1/C2/C3 (all independently verified closed). **Cycle-2 supplement
   (this one, FINAL mechanism-repair cycle)** addressed F5 (repaired the 4 re-derivation greps + Phase 4's
   exit-gate sweep — scope now all of `apps/api`, both `.isnot(`/`.is_not(` spellings, `full_name` + handle/url
   fields), F4 (re-derived census with the repaired greps → **15** predicate sites incl. `identity_resolver.py:1351`
   as a third edit shape with no `full_name_bidx`, and `jobs/backfill_enrichment.py:62`; **35** read sites incl.
   `daily_digest.py`, `job_change_detector.py`, `graph_erasure.py`, `jobs/`, `tasks/`), F6 (gates now name covering
   test files explicitly + carry a site→test-file map), C7 (`contact_importer.py:167` reclassified to Pattern B;
   the 3-line `:167`/`:169`/`:178` coordinated edit is now spelled out), plus the new §Run Disposition block.
   Re-run PVL from V1.
4. **Supporting context files loaded:** `process/context/all-context.md`, `process/development-protocols/plan-lifecycle.md`, `process/context/tests/all-tests.md`; plus direct reads of `apps/api/services/pii_crypto.py`, `apps/api/services/pii_encryption_hooks.py`, `apps/api/services/known_hash.py` for spot-verification.
5. **Next step for a fresh agent picking up mid-execution:** Do **not** start at Phase 1 — its script is
   shipped (`be39585`) and Phase 2 is shipped (`991fff3`); re-implementing either would clobber working code.
   Order of remaining work: (i) **run** the Phase 1 backfill (`--dry-run`, then real, then re-`--dry-run` to
   prove zero remaining rows) — GDPR prerequisite; (ii) Phase 3; (iii) Phase 4; (iv) Phase 5 (operator
   sign-off gated). Before touching any coordinate in this plan, **re-derive it by grep** — every `file:line`
   here is a 07-08-26 snapshot taken against a dirty working tree, and the prior inventory had ~80% drift.
   Re-derive the live migration head with `.venv/bin/python -m alembic -c apps/api/alembic.ini heads`; never
   chain off a hash written in this document. Never start Phase 3 code changes without confirming Phase 1's gate (grep/dry-run of backfill script showing 0 remaining rows) has actually run against the target DB — do not trust the plan's "done" language alone.

## Validate Contract

Status: CONDITIONAL
Date: 07-08-26
date: 2026-08-07
generated-by: outer-pvl
supersedes: 2026-08-07 (outer-pvl, PVL cycle 2) — cycle-2 repaired the census MECHANISM (F5) and
re-derived the predicate census from it (F4) and named covering test files per gate (F6). This
contract is the cycle-3 (FINAL) re-validation: the repaired predicate mechanism **self-verifies
exactly**, and 2 NEW CONCERNs are raised on the READ axis, accepted as named known-gaps under the
orchestrator convergence rule with the plan held at NOT-EXECUTE.

**Answer first:** the mechanism repair worked. Running the plan's own 4 repaired census commands
verbatim reproduces **exactly 15 predicate sites — 10 equality/IN-list + 5 NOT-NULL/presence — the
precise decomposition the plan claims**, site-for-site with no extras and no misses. That is the
self-verification test this cycle existed to run, and it passes. Two consecutive short censuses are
over: the greps now see `apps/api/jobs/`, both `.isnot(`/`.is_not(` spellings, and `full_name`.
All three assigned spot-checks are confirmed correct against the live tree. What is NOT closed is the
**READ axis**: cycle 2 repaired the predicate derivation and the Phase-4 exit *gate*, but the 35-site
READ inventory was never re-derived from that repaired sweep — and running the repaired sweep surfaces
**3 files with unlisted plaintext reads on target tables**, one of which (`services/enricher.py`) the
plan actively mislabels as needing no changes. These are accepted as known-gaps because the repaired
Phase-4 exit gate mechanically catches every one of them before Phase 4 can pass (loud, not silent),
and because prerequisite (d) forces a full PVL re-run before any EXECUTE.

### Focus-item results (as assigned)

| # | Assigned check | Result |
|---|---|---|
| 1 | Run the plan's OWN repaired census commands verbatim; do counts match 15? | **PASS — EXACT.** 15/15, decomposed 10 + 5 exactly as claimed. Mechanism self-verifies. |
| 2 | Spot-check third edit shape (`identity_resolver.py:1351`, no `full_name_bidx`) + C7 table (`:167/:169/:178`) | **PASS — all claims exact.** Details below. |
| 3 | Confirm Run Disposition block exists (NOT-EXECUTE + 4 prereqs) | **PASS.** Present at plan lines 14–32, NOT-EXECUTE + prereqs (a)–(d). |
| 4 | Confirm no new gaps of behavioral/execution impact | **CONCERN — 2 found on the READ axis.** Gate-catchable, not silent. Accepted as known-gaps. |

### Census self-verification (the cycle-3 acceptance test)

Ran verbatim, all 4 commands, all of `apps/api`:

| Command | In-scope predicate hits | Plan claims | Verdict |
|---|---|---|---|
| #1 equality / IN-list | 10 (`suppression.py:78,86,96`, `email_sender.py:33`, `identity_resolver.py:1126`, `unsubscribe.py:81,99`, `identity_signals.py:77`, `contact_importer.py:169`, `leadpipe_webhook.py:186`) | 10 | **EXACT** |
| #2 NOT-NULL email, both spellings | 3 (`visitors_helpers.py:74`, `jobs/backfill_enrichment.py:62`, `identity_resolver.py:1386`) | — | — |
| #3 `full_name` predicates | 1 (`identity_resolver.py:1351`) | — | — |
| #4 handle / url predicates | 1 (`sync.py:117`) | — | — |
| #2+#3+#4 NOT-NULL/presence family | **5** | 5 | **EXACT** |
| **Total** | **15** | **15** | **EXACT — mechanism self-verifies** |

Grep-hygiene notes (no impact on the count): command #2 also returns 2 boolean-flag false positives
(`csv_exporter.py:70` and `email_sender.py:34`, both `do_not_email.is_not(`/`.is_(` — the pattern
`email\.is_not(` matches `do_not_email.is_not(` as a substring). These are not PII predicates and are
correctly absent from the census. Command #1 also returns `contact_importer.py:167`, correctly
reclassified to Phase 4 Pattern B by C7.

### Spot-check 2 — third edit shape and C7 (both confirmed exact)

**Third edit shape — `identity_resolver.py:1351`. Every claim verified:**

- Line 1351 is exactly `BeamIdentityNode.full_name.isnot(None),` — anchor exact, no drift.
- `apps/api/models/beam_identity.py:57` defines `full_name_ciphertext` (Text, nullable). Grepping the
  whole model file for `_bidx` returns **only** `email_bidx` (`:56`). There is **no `full_name_bidx`
  column** — confirmed. The plan's conclusion that this predicate *cannot* become a bidx filter, and
  that `full_name_ciphertext.isnot(None)` is the only viable shape, is correct.
- The predicate sits inside `_graph_email_lookup`'s `try/except` whose handler is
  `logger.debug("graph_email_lookup_failed", error=str(exc))` — confirmed by direct read. The plan's
  "second §Riskiest-Site location / silent-failure path" classification is correct.
- Adjacent `:1350` is `BeamIdentityNode.email_bidx == bidx` — already on bidx, consistent with the
  plan's "2 already on bidx" note and its instruction to leave it alone.

**C7 coordinated 3-line edit — `contact_importer.py`. All three anchors exact:**

| Line | Live content | Plan's claim | Verdict |
|---|---|---|---|
| `:167` | `select(func.lower(IdentifiedVisitor.email)).where(` | projection, not filter | **exact** |
| `:169` | `IdentifiedVisitor.email.in_([c["email"] for c in valid]),` | IN-list filter | **exact** |
| `:178` | `if contact["email"] in already:` | plaintext membership compare | **exact** |

The plan quotes the code's own comment as forbidding duplicate rows; the live comment at `:161-162`
reads "re-uploading the same list / must be a no-op, not a duplicate-row generator" — the plan's
paraphrase is faithful. The 3-lines-as-one-unit instruction and the dedup regression test requirement
are both correct and necessary: converting `:167`/`:169` without `:178` leaves `already` holding
hashes while the comparison supplies plaintext, so every membership test misses.

### Structural + live-gate results

- `validate-plan-artifact.mjs`: **0 failures, 0 warnings**, 829 lines.
- Phase 1 + Phase 2 fully-automated gates re-run live this cycle:
  `.venv/bin/python3.11 -m pytest tests/unit/test_backfill_pii_ciphertext.py tests/unit/test_known_hash.py tests/unit/test_pii_crypto.py -q`
  → **24 passed in 0.31s.** The shipped-phase baseline (`be39585`, `991fff3`) is still green.
- No `git` mutation, no `results.tsv` write, no source edit, no agent spawn performed by this agent.

Parallel strategy: parallel-subagents (recorded for the future EXECUTE, not used this run)
Rationale: signal score 3/7 — S2 (schema/PII surface), S6 (high-risk: schema-migration + destructive
Phase 5), S7 (~25 files in Phase 4 blast radius). MEDIUM band. Dominant signal is S6. Not actioned
this run: the plan is held at NOT-EXECUTE, so no fan-out is spawned. Layer 1 / Layer 2 fan-out could
not be executed internally either — this agent has no Agent tool in this environment (a standing
environment limitation, see the validate-agent-no-agent-tool memory note); all findings above are
from a sequential single-pass with live command execution.

Test gates (C3 5-column table — ADDITIVE; the legacy line form below is retained for existing consumers):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC1 (backfill correctness) | backfill writes ciphertext+bidx from plaintext, idempotently | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_backfill_pii_ciphertext.py -v` | A — proven now (green this cycle) |
| AC1 (backfill RUN) | zero remaining un-backfilled rows across all 4 tables | Hybrid | `--dry-run` → real run → re-`--dry-run` against a live DB | C — deferred: operator action, prereq (a) |
| AC2 (hash unify) | `known_hash.email_hash(x) == pii_crypto.email_hash(x)` | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_known_hash.py tests/unit/test_pii_crypto.py -v` | A — proven now (green this cycle) |
| AC3 (15 predicates → bidx) | all 15 predicate sites match via bidx / ciphertext-presence / decrypt-filter | Fully-Automated | unit command in Phase 3 (10 named test files) | B — gates now name covering files; 4 sites need tests built in Phase 3 |
| AC3 (integration leg) | bidx predicates match against real PG after backfill | Hybrid | integration command in Phase 3 (4 named files, `-m integration`) | C — deferred: Docker, prereq (b) |
| AC6 (riskiest site) | ON CONFLICT on `(fingerprint, email_bidx)` upserts instead of raising | Hybrid | Phase 3 riskiest-site integration tests (`identity_resolver`, `events.py`, `click.py`) | C — deferred: Docker, prereq (b); tests not yet written |
| AC6 (2nd silent path) | `identity_resolver.py:1351` branch still matches after ciphertext swap | Fully-Automated | new Phase 3 regression test (does not exist yet) | B — Phase 3 checklist item |
| AC4 (35 reads → decrypt) | zero raw plaintext-column reads survive outside accessor definitions | Fully-Automated | repo-wide Phase 4 exit sweep across all `apps/api` | B — sweep is repaired and works; inventory needs re-derivation (see G1) |
| AC4 (GDPR export) | export payload carries decrypted plaintext, not ciphertext | Hybrid | Phase 4 GDPR export integration test | C — deferred: Docker, prereq (b) |
| AC5 (drop plaintext) | app boots + full suite green against post-drop schema | Hybrid | `.venv/bin/python3.11 -m pytest tests/ -v` against a migrated staging DB | C — deferred: Docker + soak + prereq (b) |
| AC5 (evidence pack) | 5-JSON artifact pack reviewed and accepted by operator | Agent-Probe | manual review of `harness/` pack | C — deferred: operator sign-off, prereq (c) |
| local-variable / dynamic-access reads | a read via a renamed local or `getattr(obj, "field")` is caught | — | none exists | D — backlog residual (see G2) |

gap-resolution legend: A — proven now. B — fixed by this plan's checklist. C — deferred to a named
prereq/phase. D — backlog test-building stub (named residual; continue).

C-4 reconciliation: the `strategy` column carries only the 3 proving strategies (Fully-Automated /
Hybrid / Agent-Probe). Known-Gap is never a strategy value — it is carried as gap-resolution D.

Legacy line form (retained so existing validate-contract consumers still parse):
- Phase 1 backfill code: `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_backfill_pii_ciphertext.py -v` — **green this cycle**
- Phase 2 hash unify: `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_known_hash.py tests/unit/test_pii_crypto.py -v` — **green this cycle**
- Phase 1 backfill RUN: `hybrid: --dry-run + real run + re-dry-run, precondition: live DB + operator authorization` — **never run**
- Phase 3 predicate cutover: `Fully-automated: 10 named unit test files (see Phase 3)` + `hybrid: 4 named integration files, precondition: PG+Redis via infra/docker-compose.yml` — **never run**
- Phase 4 read cutover: `Fully-automated: repo-wide apps/api grep sweep` + `hybrid: GDPR export + csv integration, precondition: PG` — **never run**
- Phase 5 drop: `hybrid: full suite vs migrated staging DB, precondition: PG + completed soak` + `agent-probe: 5-JSON evidence pack operator review` — **never run**
- local-variable / dynamic-access read shape: `known-gap: documented, no mechanical gate exists`

Dimension findings:
- Infra fit: **CONCERN** — Docker is down in this environment and has been in every session that ever touched this plan, so all 8 Hybrid gates remain unexecuted. The commands themselves are correct: `infra/docker-compose.yml` provides PG 16 + Redis 7, and the interpreter form `.venv/bin/python3.11 -m pytest` is the one proven working (the `.venv/bin/pytest` shebang is broken in this repo). Migration-head discipline is right — the plan now forbids chaining off any hash written in its own body and mandates a live `alembic heads` re-derive.
- Test coverage: **CONCERN** — zero Hybrid gates have ever run, so AC3/AC4/AC5/AC6 carry no runtime evidence at all; the only green evidence in the whole plan is the Phase 1+2 unit suite (24 tests, re-confirmed live this cycle). Gate commands are now materially better than cycle 2: covering test files are named explicitly instead of relying on a `-k` filter that provably under-covered its own criterion, and a site→test-file map makes census growth force gate growth. 4 census sites still have no covering test file; the plan correctly classes these as Phase-3 build items rather than known-gaps.
- Breaking changes: **PASS** — no public API response-shape change (decrypted values are the values callers already see). The internal `.pii_*` accessor addition is additive. The Phase 5 column drop is internal-only with no externally-exposed schema. The one genuinely irreversible step (Phase 5) is correctly gated behind Phase 3 verification, a soak window, and an operator sign-off, and the migration docstring is required to state that `downgrade()` cannot repopulate data.
- Security surface: **PASS** — this plan *is* a security improvement (real encryption at rest). Compliance reasoning is sound and now correctly prioritized: the un-run backfill leaves `beam_identity_graph.email_bidx = NULL` on pre-existing rows, and `graph_erasure.py`'s cross-tenant sweep matches on `email_bidx == func.any(...)` where NULL never matches — so GDPR erasure silently under-deletes today. Elevating the backfill RUN to a compliance prerequisite ahead of Phase 3 is the right call. PII-logging discipline (keys/counts only) is carried into the backfill script. The `prompt_safety.sanitize_profiles` chain is correctly preserved (decrypt BEFORE sanitize, not instead of).
- Section feasibility — Phase 1 (backfill): **PASS** — code shipped at `be39585`, 322 lines on disk, tests green. Only the operator RUN remains; correctly reclassified as a GDPR prerequisite. Highest-risk element is that it has never touched any database.
- Section feasibility — Phase 2 (hash unify): **PASS** — shipped at `991fff3`, delegation in place, public names preserved so all 5 call sites are untouched, equality pinned by test. Nothing left to do.
- Section feasibility — Phase 3 (predicate cutover): **PASS** — mechanically feasible and now fully specified. All 15 anchors reproduce from the plan's own commands; the three distinct edit shapes (bidx swap / ciphertext-presence / load-and-decrypt-filter) are each correctly assigned; the two ON CONFLICT APIs are correctly distinguished (`index_elements=` for `on_conflict_do_update` vs `constraint=` string for `on_conflict_do_nothing`) — following the wrong one would fail. Highest-risk edit: `identity_resolver.py:1351`, because a miss there fails silently inside a swallowing `except`; the plan requires an explicit regression test for exactly that branch.
- Section feasibility — Phase 4 (read cutover): **CONCERN** — the design work is strong: the Pattern A / Pattern B split is correct and non-obvious (a Python `@property` can never appear in a `select()` projection), and the `_row_to_dict` GDPR finding is a genuine catch (it iterates `obj.__table__.columns`, so an accessor is structurally invisible to it). But the 35-site inventory is incomplete — see G1. The exit gate is repaired and repo-wide, so the gap is gate-catchable rather than shippable.
- Section feasibility — Phase 5 (drop plaintext): **PASS** — correctly classified high-risk/destructive, correctly sequenced behind Phase 3, correctly bound to the canonical 5-JSON `vc-risk-evidence-pack` schema in this task folder's `harness/`, and correctly designed to fail loudly (AttributeError / missing column) rather than silently. The requirement that the accessor-fallback removal and the drop migration ship together is right — either alone breaks reads. Precondition 3 correctly points at the repaired sweep rather than the void 3-directory version.

Open gaps:

- **G1 — READ census (35) was never re-derived from the repaired sweep; 3 files carry unlisted plaintext reads on target tables.** `known-gap: documented as accepted this cycle — MANDATORY re-derivation item for the prereq-(d) PVL refresh`
  - `services/enricher.py` — **~14 unlisted field-reads on BOTH target tables**, and the highest-impact instance: `:218` (`if not identified.email`), `:228`, `:256` (`_enrich_pdl` — paid People Data Labs call), `:269` (`_enrich_apollo` — paid), `:273` (`_domain_enrichment`), `:290`/`:302` and `:367`/`:369`/`:376`/`:378` (`profile.linkedin_url` / `profile.twitter_handle` — feeding paid Proxycurl / TwitterAPI.io), `:978`/`:985`/`:986` (Gemini prompt context), `:979`/`:980`. **Compounding documentation defect:** `enricher.py` appears exactly twice in the entire plan — the §Scope list (line 42) and §Blast Radius WRITE sites (line 138), where it is labelled "ORM (ALREADY correct via 5b hooks)". It is absent from the READ table and absent from Phase 4's Touchpoints list. An execute-agent reading the plan would reasonably conclude this file needs no Phase 4 work, when in fact the whole enrichment waterfall reads plaintext.
  - `routers/contacts.py:131,132,134,171,175` — 5 Pattern-A reads (`iv.email`, `iv.full_name`, `identified.email`, `identified.full_name`) on `IdentifiedVisitor` instances from a joined `(Visitor, IdentifiedVisitor)` select. Unlisted.
  - `services/social_resolver.py:148,176,214` — 3 Pattern-A reads (`identified.email`, `identified.full_name`) on an `IdentifiedVisitor` passed into `resolve_social`. Unlisted.
  - **Why accepted rather than blocking:** all three files are surfaced by the plan's OWN repaired Phase-4 exit sweep (that is precisely how they were found this cycle), so the Phase-4 gate cannot pass while they remain unedited — the failure mode is a loud gate failure, not a silent plaintext leak. All are Pattern A/B shapes with no predicate, no ON CONFLICT, and no swallowing `except` involved. The plan does not EXECUTE this run, and prerequisite (d) mandates a full PVL re-run at EXECUTE time, at which point the census must be re-derived from the repaired sweep. **Required action at that refresh:** add these three files to the READ table, add `enricher.py` (and `contacts.py`, `social_resolver.py`) to Phase 4's Touchpoints, and correct the WRITE-site note so it no longer implies `enricher.py` needs no changes. Also add a READ-census *derivation* command (the plan currently has repaired derivation commands for predicates only — the READ inventory is hand-maintained, which is the same class of defect as F5 one axis over).
- **G2 — dynamic-access blind spot is wider than the plan's supplementary grep covers.** `known-gap: documented, extends the in-plan local-variable residual` — the plan's supplementary check is `grep -rn "getattr(.*\"email\"\|getattr(.*'email'" apps/api`, which is **email-only**. Live counter-example: `services/social_resolver.py:174` uses `getattr(profile, "twitter_handle", None)` and `:175` uses `getattr(profile, "github_url", None)` — these escape the main sweep (no textual `.twitter_handle`) AND the supplementary grep (not email). At the prereq-(d) refresh, widen the supplementary grep to all 4 PII fields. Unchanged residual: a read into a differently-named local, and raw SQL naming the column, still have no mechanical gate.
- **G3 — zero Hybrid gates have ever executed, in any session, against any database.** `known-gap: documented — environment-bound, prereq (b)` — AC3/AC4/AC5/AC6 carry no runtime evidence whatsoever. This is not closable by writing a test; it needs a working Docker daemon or a CI lane.
- **G4 — `## Autonomous Goal Block` is stale.** `known-gap: documented — outside this agent's write scope` — the block still reads `CURRENT GATE: BLOCKED`, still says "12 lookups" (now 15), and still names the deleted stale head `b8f3c1d92a47` in a hard-stop line. This agent's enumerated STOP-BLOCK restricts writes to the `## Validate Contract` section, so the block was deliberately left untouched. **Orchestrator action:** refresh the goal block to `CURRENT GATE: CONDITIONAL — validated-and-held`, 15 predicate sites, and drop the stale-head reference.
- **G5 — LOOKUP-table numbering and out-of-scope annexe are cosmetically inconsistent.** `known-gap: documented as a documentation nit, zero execution impact` — the table has 15 real rows but the ID column skips `#10` and uses `#14` twice; the out-of-scope annexe names `routers/privacy.py:103,109` (which no longer match any of the 4 census commands) while omitting `dependencies.py:171` and `:281` (which do match, both `WaitlistSignup`/`User`, correctly out of scope). The READ table's "35" matches neither its row-group count (31 after the self-declared 40-41 duplicate) nor its field-read count (~54); the plan itself disclaims the sum in favour of the list, so this is presentational only.
- **Verified NON-gap (recorded so a future pass does not re-flag it):** the three CRM connectors (`services/crm/salesforce.py:38,39,204`, `crm/pipedrive.py:37,38,195`, `crm/hubspot.py:43,182`) read `contact.email` / `contact.last_name` on a `CRMContact` **dataclass** (`services/crm/base.py:51`), not an ORM row. That dataclass is built by `crm/contact_mapper.py:28` from rows produced by `_get_segment_visitors` in `services/csv_exporter.py` — a read site already listed (READ rows 24-28). The CRM surface is therefore transitively covered and correctly out of scope. Likewise `services/referral_activation.py:167,172` reads `referrer.email` where `referrer` is a `User` (`select(User)` at `:164`) — correctly out of scope.

What this coverage does NOT prove:

- **The two green fully-automated gates (Phase 1 + Phase 2, 24 tests) prove only** that the backfill function encrypts/hashes correctly and idempotently in-process against seeded fixtures, and that the two `email_hash` implementations return equal values for the pinned inputs. They do **not** prove the backfill has ever touched a real table, that batching/resumability behaves against a large table, that the infinite-loop guard fires correctly under real contention, or that any of the 5 `known_hash` call sites still behave correctly end-to-end.
- **The repaired predicate census (15/15 exact) proves only** that the 4 commands and the plan's inventory agree, as static text, against the working tree at commit `5293cbc` on branch `devjulley` **with a dirty tree**. It does **not** prove any of those 15 predicates will still match after a bidx swap, that bidx NOT-NULL semantics equal plaintext NOT-NULL semantics on real data, or that no predicate is constructed dynamically at runtime and therefore invisible to grep.
- **The repaired Phase-4 exit sweep proves only** that no raw plaintext-column read survives *textually*. It does **not** catch a read into a differently-named local, `getattr(obj, "field")` (demonstrated live at `social_resolver.py:174-175`), an ORM expression assembled at runtime, or a raw SQL string naming the column.
- **AC3 is unproven at runtime.** No bidx predicate has ever been executed against a database. The unit leg (once written) will run against mocked or SQLite-shaped fixtures, which cannot prove PostgreSQL unique-constraint or `ON CONFLICT` semantics.
- **AC6 is entirely unproven.** No riskiest-site regression test exists yet for any of the three ON CONFLICT paths, and the second silent-failure path (`identity_resolver.py:1351`) has no test either. Both failure modes are, by construction, silent — swallowed to `logger.debug` — so the absence of an error signal is not evidence of correctness.
- **AC4 is unproven beyond static census, and the census itself is now known-incomplete** (G1). Nothing proves the GDPR export returns plaintext, and the `_row_to_dict` fix is designed but untested.
- **AC5 is unproven and largely unprovable by automation.** The soak-adequacy judgment is human; backup-before-drop is an operator action; and post-drop behavior can only be observed against a real migrated database.
- **The GDPR compliance claim is reasoned, not measured.** The `graph_erasure.py` NULL-bidx under-deletion is derived by reading the SQL, not by observing a failed erasure. No query has been run against any database to count how many `beam_identity_graph` rows currently have `email_bidx IS NULL`.
- **Every `file:line` in this contract is a snapshot** taken against a dirty working tree (~130 uncommitted changes, including 4 uncommitted migrations, on branch `devjulley` at `5293cbc`). This repo has an on-record incident of a concurrent session's rebase reverting uncommitted work. Anchors have drifted within a single day in this plan's own history. Re-derive at EXECUTE time; that is prerequisite (d).
- **No Layer 1 / Layer 2 parallel fan-out was executed.** This agent has no Agent tool in this environment, so all findings are from a single sequential pass. Prior cycles of this repo's PVL runs show that orchestrator-spawned adversarial verifiers find defects that single-pass validation misses; that class of check has not been applied to this plan.

Gate: CONDITIONAL (0 FAILs; 5 CONCERNs accepted as named known-gaps G1–G5 — the repaired predicate
census mechanism self-verifies exactly 15/15, all 3 assigned spot-checks confirm correct against the
live tree, the Run Disposition block is present, and the 2 new READ-axis findings are mechanically
caught by the plan's own repaired exit gate before Phase 4 can pass. Plan is held at NOT-EXECUTE.)

Accepted by: orchestrator convergence rule, autopilot run 07-08-26, plan held at NOT-EXECUTE.
Accepted concerns, each by name: G1 (READ census incomplete — 3 unlisted files incl. `enricher.py`
mislabel; gate-catchable, mandatory re-derivation item at the prereq-(d) PVL refresh), G2 (dynamic-access
blind spot wider than the email-only supplementary grep), G3 (zero Hybrid gates ever executed —
environment-bound on prereq (b)), G4 (stale `## Autonomous Goal Block` — outside this agent's write
scope, orchestrator action), G5 (LOOKUP numbering + out-of-scope annexe documentation nits).
This acceptance authorizes NO execution. EXECUTE remains gated behind all four Run-Disposition
prerequisites: (a) Phase 1 backfill RUN completed and verified by an operator, (b) Docker available for
the migration round-trip and all 8 Hybrid gates, (c) the 5-JSON high-risk evidence pack in
`harness/`, and (d) a full PVL re-run from V1 against a fresh tree — which must begin by re-deriving
the READ census from the repaired sweep and closing G1. Do NOT archive this plan: Phases 3–5 are real,
unstarted, and still necessary — plaintext PII is authoritative in production today and the un-run
backfill leaves a live GDPR erasure gap.

## Autonomous Goal Block

SESSION GOAL: Finish PII encryption-at-rest — Phases 1-2 (backfill script + blind-index hash unify) ALREADY SHIPPED and committed; the remaining goal is Phase 3 (cut 12 lookups + 3 ON CONFLICT sites to bidx), Phase 4 (cut reads to decrypt), Phase 5 (drop plaintext columns).
CURRENT GATE: BLOCKED as of 07-08-26 (see `## Validate Contract`). Routing is PLAN-supplement, NOT EXECUTE.
Charter + umbrella plan: N/A — single plan (no umbrella/phase-program structure; this is one COMPLEX plan with 5 internally-ordered phases).
Autonomy: Standard /goal autonomous execution rules apply (see process/development-protocols/orchestration.md §Autonomy Mode). CONDITIONAL findings auto-apply and proceed; BLOCKED items go to backlog + continue with remaining phases; irreversible/outward-facing actions without explicit contract instruction are a hard stop.
Hard stop conditions / safety constraints:
- Phase 3 (bidx unique constraints + ON CONFLICT repoint) MUST land and be verified before Phase 5 (drop plaintext) is even proposed for execution — do not skip-ahead under any autonomy setting.
- Phase 5 (destructive column drop) requires the 5-JSON-artifact manual evidence pack (risk-gate.json / context-snippets.json / verification.json / review-decision.json / adversarial-validation.json) reviewed and explicitly accepted by the operator BEFORE the migration runs against prod — this is a hard stop even under full autonomy (irreversible data-loss action).
- Never log PII values (structlog events log keys/ids only, per repo convention) — applies to the backfill script's per-batch logging (Phase 1).
- Do not drop the plaintext-keyed unique constraints until Phase 5 (Phase 3 adds bidx constraints in parallel; both coexist through Phase 4).
- Never re-run Phase 1 or Phase 2 as new work — both are shipped and committed (`be39585`, `991fff3`) with green tests. Re-implementing them would clobber working code.
- Never chain a new migration off the hash written in this plan body (`b8f3c1d92a47` — stale). Re-derive `alembic -c apps/api/alembic.ini heads` live at apply time; the tree currently carries 4 uncommitted migrations.
Next phase: PLAN-supplement (re-baseline F1/F2/F3) — process/general-plans/active/pii-at-rest_22-07-26/pii-at-rest_PLAN_22-07-26.md. EXECUTE is not authorized while Gate: BLOCKED. After the supplement lands, re-run PVL from V1.
Validate contract: inline in plan (`## Validate Contract` section, this file)
Execute start: BLOCKED — do not start. (Phase 1's command below is retained for reference only; that phase is already shipped.) Phase 1 fully-auto command `.venv/bin/python -m pytest tests/unit/test_backfill_pii_ciphertext.py -v` | e2e spec: none (backend-only, no e2e in blast radius) | probe scenario: Phase 1 `--dry-run` against dev DB (Hybrid, needs PG) | high-risk pack: yes — required at Phase 5 only, not Phases 1-4.
