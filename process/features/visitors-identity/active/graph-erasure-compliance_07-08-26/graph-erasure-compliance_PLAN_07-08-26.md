---
name: plan:graph-erasure-compliance
description: "PLAN — cross-tenant beam_identity_graph erasure queue, write-boundary guard, operator lookup, and disclosure requirements"
date: 07-08-26
feature: visitors-identity
---

# PLAN — Cross-Tenant Identity Graph: Erasure & Disclosure Compliance

**Date**: 07-08-26
**Status**: ACTIVE — PLAN written, VALIDATE pending, EXECUTE blocked on §0 sequencing constraint
**Complexity**: COMPLEX
**Feature**: visitors-identity
**SPEC**: `graph-erasure-compliance_SPEC_07-08-26.md` (same task folder)

## Overview

Beam pools identity data across every customer site into one shared table, `beam_identity_graph`.
Today a per-visitor deletion request never reaches that table, so an erased person is still served
to every other Beam customer — and the public Privacy Policy and Terms both assert the opposite of
what the code does. This plan closes that gap on three fronts: an asynchronous platform-level
erasure queue that reaches the shared graph regardless of which tenant wrote the row, a structural
guard at the graph-write boundary so an erased person can never be silently re-added, and a
specified (not drafted) disclosure requirement for the legal and onboarding surfaces. Scope is
deliberately narrow — one ~6-line hunk in `identity_resolver.py` — to avoid colliding with two
other active plans rewriting that file.

**Complexity rationale (COMPLEX):** 18 touchpoints across 2 packages, 5 new files, a schema
migration, scheduler wiring, and three named high-risk classes (PII/trust-boundary, destructive
data mutation, public API contract).

**Complexity: COMPLEX** (7 new/changed backend files + migration + scheduler wiring + 3 legal/UX
surfaces; touches a high-risk class — PII erasure + multi-tenancy).

**TL;DR** — Per-visitor deletion becomes a *producer* that enqueues a platform-level erasure request
(`erasure_requests` table, new). An APScheduler sweep drains the queue: hard-deletes matching
`beam_identity_graph` rows and writes a `SuppressionEntry(scope="erased")` tombstone. One guard
clause inside `_upsert_beam_identity` consults that tombstone so the person can never be re-written.
An admin-gated lookup answers "is this person still in the graph, and who put them there." Legal
copy is specified as requirements + a greppable presence check, never drafted here.
**EXECUTE is sequenced behind `identity-vocab-reconcile_07-08-26` reaching `Gate: PASS`.**

---

## 0. HARD SEQUENCING CONSTRAINT — read before anything else

> **EXECUTE on this plan MUST NOT start until
> `process/features/visitors-identity/active/identity-vocab-reconcile_07-08-26/` reaches
> `Gate: PASS`, or is explicitly descoped by the user.**

| Colliding plan | Status (07-08-26) | Overlap with this plan | Action |
|---|---|---|---|
| `identity-vocab-reconcile_07-08-26` | PVL cycle 2 `Gate: BLOCKED`; cycle 4 contract pending | Rewrites `identity_resolver.py` §3.2 (Tier 2, marked **Highest** risk in its own blast-radius table) AND `routers/visitors.py` (Tier 3) — **both files this plan edits** | **BLOCKING.** Wait for `Gate: PASS` or explicit descope. |
| `identity-program_03-08-26` Phase 1 | PLANNED, not executed | Claims `_save_identified` in `identity_resolver.py` | **NOT blocking.** `_save_identified` is the *caller*; this plan edits `_upsert_beam_identity` (the callee, a separate method). Claim recorded below so that plan can account for it. |
| `identity-coop_07-08-26` (SPEC B) | SPEC phase | Consumes the `SuppressionEntry(scope="erased")` marker this plan publishes | **Downstream.** Interface published in §7. |

**Blast-radius claim published for the two plans above:** this plan touches
`apps/api/services/identity_resolver.py` in exactly **two independently-revertible hunks**, both
inside `_upsert_beam_identity` (currently `:995`–`:1030`):

- **Hunk A (guard)** — ~6 lines at the top of the method body, before the `pg_insert`.
- **Hunk B (bidx read-path)** — see §3, Correction 1: **NO CODE CHANGE REQUIRED.** `email_bidx` is
  already written here. Hunk B collapses to a *test-only* assertion. Net: this plan modifies
  `identity_resolver.py` in **ONE hunk**, ~6 lines, inside one method. That is the minimum-collision
  scope the SPEC's Constraints section asked for.

No other line of `identity_resolver.py` is touched. `_save_identified`, `resolve()`, and §3.2 are
all untouched by this plan.

---

## 1. Goals & Non-Goals

**Goals**

1. A per-visitor deletion request reaches the cross-tenant graph and makes the person unresolvable,
   regardless of which tenant's `source_site_id` is on the row (AC-1, AC-2).
2. Erasure is idempotent and crash-safe (AC-3).
3. The person cannot be silently re-added to the graph on their next visit to any site (AC-4).
4. The opt-out guard is enforced *at the write boundary*, not only upstream (AC-5), without
   regressing today's upstream behavior (AC-6).
5. An operator can answer "is this person still in the graph, and which sites contributed" without
   ad-hoc SQL (AC-10).
6. The disclosure gap in `privacy.html` / `terms.html` / onboarding is closed as a *requirement +
   presence check* (AC-7, AC-8, AC-9). **No legal copy is drafted by this plan.**

**Non-Goals** (from SPEC Out Of Scope, restated so EXECUTE does not drift)

- Co-op opt-in, contribution/consumption ledger, reciprocity (SPEC B).
- `CompanyGraphNode` erasure (see §8 Known Gap KG-3).
- Drafting final legal sentences.
- Visitor-facing self-serve "forget me" form.
- One-time reconciliation of historical rows (see §8 Known Gap KG-2).
- Any change to `retention.py`.

---

## 2. Locked Design (from INNOVATE — do not re-decide during EXECUTE)

| Item | Decision |
|---|---|
| Queue substrate | New `erasure_requests` table + APScheduler sweep, mirroring `services/referral_activation.py` (advisory lock + conditional UPDATE + interval job) |
| State machine | `pending → processing → done \| failed`, with `attempts` and `processed_at`. Idempotent on crash-restart via a stale-`processing` reclaim window |
| Matching key | `email_bidx` (HMAC blind index) **and** `fingerprint` / `fingerprint_v3`. **No plaintext email is ever stored in the queue.** |
| Authorization | Any site may enqueue erasure for a visitor row **it owns** (`visitor_id` scoped to that site's own `Visitor`). Matching into the shared graph proceeds regardless of `source_site_id`. Rate-limited per site. Requesting `site_id` is persisted for audit. |
| Tombstone | **Reuse `SuppressionEntry` with new scope `"erased"`.** No new tombstone table. It is already platform-level (no `site_id`), already keyed by `email_hash`, already the choke point the resolver consults. |
| Guard hardening | **ONE** guard clause inside `_upsert_beam_identity`: suppression lookup by blind index + defensive `do_not_resolve` re-check. Explicitly NOT a rewrite. |
| `CompanyGraphNode` | Excluded from fan-out today, but the target list is modeled as an **extensible tuple constant** (`ERASURE_TARGETS = ("beam_identity_graph",)`) so a later legal decision needs no schema change |
| Legal copy | Requirements only. WHERE it must appear + a greppable presence check. Text requires counsel. |
| One-time reconciliation | **Not pursued.** No historical deletion-request log with sufficient detail exists. Recorded as KG-2. |

---

## 3. Ground-Truth Corrections Found During Planning

These change the work. EXECUTE must read them before touching code.

**Correction 1 — `email_bidx` is NOT dormant. It is already live.**
The task brief and the model's own comment (`beam_identity.py:52` "added nullable, not yet
read/written") are **both stale**. Verified in source this session:

- `identity_resolver.py:_upsert_beam_identity` already sets
  `email_bidx=email_hash(email)` and `email_ciphertext=encrypt_pii(email)` on every insert.
- `identity_resolver.py:_graph_node_by_email` already **reads** `email_bidx`
  (index `ix_beam_identity_graph_email_bidx`).

**Consequence:** the planned "activate the dormant column" work **disappears**. The plan is
*smaller* than briefed, and the `identity_resolver.py` blast radius shrinks to one hunk (see §0).
EXECUTE must NOT add a dual-write — it already exists. A checklist item corrects the stale docstring.

**Correction 2 — the blind-index key chain is already consistent. VERIFIED, not assumed.**
CAUTION item #2 in the brief (silent hash divergence) is **resolved as verified-consistent**. All
four call sites route through the single function `apps/api/services/pii_crypto.py:66 email_hash()`
= `HMAC-SHA256(PII_HMAC_KEY, normalize_email(email))`:

| Consumer | Call site | Same fn? |
|---|---|---|
| `beam_identity_graph.email_bidx` | `identity_resolver.py:_upsert_beam_identity` | yes |
| `identity_signals.email_bidx` | `identity_signals.py:138`, `:171` | yes |
| `suppression_list.email_hash` | `services/suppression.py` (`is_email_suppressed`, `add_suppression`, `remove_suppression`) | yes |
| ORM hooks | `pii_encryption_hooks.py` | yes (imports `pii_crypto`) |

There is exactly one hash implementation. **The divergence risk is structural-zero today.** It is
still made an explicit regression test (T-U4) so a future second implementation cannot be introduced
silently.

**Correction 3 — the existing scope-matching semantics constrain the tombstone design.**
`is_email_suppressed(db, email, scope)` matches `scope IN (requested_scope, "all")`. So a bare
`scope="erased"` row would **not** be seen by the existing upstream `_is_email_opted_out` check
(which asks for `"do_not_process"`). This is handled deliberately in §4 step S3: the sweep writes
**two** rows — `"erased"` (durable audit marker, SPEC B's interface) and `"do_not_process"` (reuses
the existing `_cascade_suppress`, which sets `do_not_resolve=True` on the person's `Visitor` rows
**across all sites** — this is what actually delivers AC-4 for other tenants).

**Correction 4 — ordering hazard in the producer.**
`DELETE /{site_id}/{visitor_id}/data` deletes `visitors`, `identified_visitors`, and
`enrichment_profiles`. Those rows hold the **only** source of the visitor's `fingerprint` and email.
**The enqueue MUST read the match keys and INSERT the queue row BEFORE the DELETE loop runs.**
Enqueuing after would always produce an empty-keyed, useless request. This is checklist item C-11
and is the single most likely EXECUTE mistake.

---

## 4. Architecture — Data Flow (prose, per plan contract)

**Producer path (synchronous, inside the existing DELETE request):**

1. `_verify_site_access(db, site_id, user)` — unchanged; enforces `Site.user_id == user.id`.
2. Per-site rate-limit check (`graph_erasure_max_per_minute`). Over limit → `429`.
3. **Collect match keys BEFORE deletion** (Correction 4): `SELECT fingerprint, fingerprint_v3 FROM
   visitors`, plus emails from `identified_visitors.email` and `visitor_emails.email`, all scoped
   `site_id = :sid AND visitor_id = :vid`. Convert each email to `email_hash(email)` immediately;
   **never persist plaintext.**
4. `INSERT INTO erasure_requests (...) VALUES (..., status='pending')`. Wrapped in try/except that
   logs a warning and continues — a missing table or transient failure must never break the
   tenant-facing deletion (matches the endpoint's existing per-table try/except posture).
5. Existing 6-table DELETE loop runs unchanged.
6. Response is **uniform** (see §5 Public Contracts): always `{"status":"deleted", ...,
   "erasure_request": {"id": ..., "status": "queued"}}` whether or not any graph row exists.

**Sweep path (asynchronous, APScheduler interval job):**

1. `_try_acquire_lock` on `pg_try_advisory_lock(hashtext('beam_graph_erasure'))` — copied from
   `referral_activation.py`.
2. Reclaim stale rows: `UPDATE erasure_requests SET status='pending' WHERE status='processing' AND
   updated_at < now() - interval N` (crash recovery).
3. Claim one row at a time: `UPDATE erasure_requests SET status='processing', attempts=attempts+1
   WHERE id=:id AND status='pending' RETURNING *`. `rowcount == 0` → another worker has it; skip.
4. For each target in `ERASURE_TARGETS`: `DELETE FROM beam_identity_graph WHERE email_bidx = ANY(:b)
   OR fingerprint = ANY(:f) OR fingerprint_v3 = ANY(:f)`. **No `source_site_id` filter** — this is
   AC-2's mechanism.
5. Write tombstones: for each stored `email_bidx`, `pg_insert(SuppressionEntry).values(
   email_hash=<the stored bidx>, scope="erased", reason="graph_erasure",
   requested_by=None).on_conflict_do_nothing(...)`, plus the `"do_not_process"` row via the same
   direct-insert path followed by `_cascade_suppress`-equivalent behavior (see C-08).
   **Note:** the stored `email_bidx` *is* a valid `SuppressionEntry.email_hash` — same function, same
   key — so no plaintext is needed at sweep time. This is why the queue can be plaintext-free.
6. `status='done'`, `processed_at=now()`. On exception → rollback, `status='failed'` after
   `graph_erasure_max_attempts`, else back to `pending`.

**Guard path (write boundary):** `_upsert_beam_identity` re-checks `do_not_resolve` and calls the
new `is_email_suppressed_any(db, email, ("erased", "do_not_process"))` before its `pg_insert`.
Returns early with a structlog line carrying **no PII** (visitor id prefix only).

---

## Touchpoints

| # | File | Change | New? |
|---|---|---|---|
| 1 | `apps/api/models/erasure_request.py` | `ErasureRequest` model + `ERASURE_TARGETS` + status constants | **NEW** |
| 2 | `apps/api/migrations/versions/<gen>_add_erasure_requests.py` | create table + 2 indexes | **NEW** |
| 3 | `apps/api/services/graph_erasure.py` | `enqueue_erasure()`, `run_graph_erasure_sweep()`, `lookup_graph_identity()` | **NEW** |
| 4 | `apps/api/routers/visitors.py` (`delete_visitor_data`, `:403-439`) | becomes a producer: collect keys → enqueue → existing DELETE loop | edit |
| 5 | `apps/api/services/identity_resolver.py` (`_upsert_beam_identity`, `:995`) | **ONE hunk**, ~6-line guard clause. Nothing else. | edit |
| 6 | `apps/api/services/suppression.py` | add `"erased"` to `VALID_SCOPES`; add `is_email_suppressed_any()`; keep `is_email_suppressed()` as a thin delegate | edit (additive) |
| 7 | `apps/api/models/suppression.py` | docstring: document `"erased"` scope | edit (docstring) |
| 8 | `apps/api/models/beam_identity.py` (`:52`) | fix stale "not yet read/written" comment (Correction 1) | edit (comment) |
| 9 | `apps/api/jobs/scheduler.py` | register `_graph_erasure_sweep_job` interval job | edit |
| 10 | `apps/api/config.py` | new settings block (see §6) | edit |
| 11 | `apps/api/routers/privacy.py` | `GET /privacy/graph-identity` operator lookup (admin-gated) | edit |
| 12 | `apps/api/schemas/` (privacy schemas) | `GraphIdentityLookupOut` response model | edit/new |
| 13 | `apps/web/public/beam/privacy.html` | disclosure section (requirement — copy by counsel) | edit |
| 14 | `apps/web/public/beam/terms.html` | qualify "you own your data" (requirement — copy by counsel) | edit |
| 15 | onboarding/pixel-install surface (`apps/web/src/app/onboarding/**`) | disclosure element with `data-testid="cross-tenant-disclosure"` | edit |
| 16 | `tests/unit/test_graph_erasure.py` | new unit tests | **NEW** |
| 17 | `tests/integration/test_graph_erasure_flow.py` | new integration tests | **NEW** |
| 18 | `apps/web/e2e/onboarding.spec.ts` | add AC-9 presence assertion | edit |

**Read-for-context (not modified):** `apps/api/services/referral_activation.py` (sweep pattern),
`apps/api/services/pii_crypto.py`, `apps/api/routers/sites.py:281-286` (existing graph delete),
`apps/api/models/visitor_email.py`.

---

## Public Contracts

**C1 — `DELETE /api/v1/visitors/{site_id}/{visitor_id}/data` (changed, backward-compatible)**

Response gains one field. The `deleted` dict is unchanged.

```json
{"status":"deleted","visitor_id":"...","deleted":{...},
 "erasure_request":{"id":"<uuid>","status":"queued"}}
```

> **EXISTENCE-ORACLE RULE (hard, non-negotiable — see checklist C-13).** This response MUST be
> byte-shape-identical whether or not a matching `beam_identity_graph` row exists. It MUST NOT
> report a match count, a "found" boolean, a differing `status`, a differing HTTP code, or a
> measurably different latency band. All graph work is async in the sweep. A synchronous
> "found and erased" answer would turn this endpoint into a probe letting any tenant test whether
> an arbitrary email/fingerprint exists in the shared graph — i.e. a cross-tenant PII disclosure
> introduced by a privacy feature. New failure modes are `429` (rate limit) and `404`
> (unknown/foreign `site_id`, per multi-tenancy rule — never `403`).

**C2 — `GET /api/v1/privacy/graph-identity` (NEW, platform-operator only)**

Query: `?email=<plaintext>` or `?fingerprint=<hash>` (exactly one required).
Response `GraphIdentityLookupOut`:

```json
{"exists": true, "row_count": 2,
 "contributing_site_ids": ["site_a","site_b"],
 "erased_tombstone": false,
 "matched_by": "email"}
```

> **AUTHORIZATION (hard).** This endpoint IS an existence oracle by design — that is its purpose for
> AC-10 — so it MUST NOT be reachable by an ordinary tenant. It is gated to platform operators only.
> EXECUTE checklist item C-14 requires *discovering* the repo's existing admin dependency (candidates
> to inspect: `routers/costs.py`, `routers/request_logs.py`, `routers/feature_requests.py`). If no
> admin dependency exists, **fall back to a CLI script** (`scripts/graph_identity_lookup.py`) and do
> **not** ship the HTTP route. Shipping this route tenant-reachable is a FAIL condition.

**C3 — `SuppressionEntry(scope="erased")` (NEW platform semantic)** — see §7.

**C4 — `ERASURE_TARGETS: tuple[str, ...] = ("beam_identity_graph",)`** — the extensible fan-out
target list. Adding `"company_graph"` later is a one-constant change, no schema migration.

**C5 — `suppression.is_email_suppressed_any(db, email, scopes)`** — additive; existing
`is_email_suppressed(db, email, scope)` keeps its exact signature and behavior by delegating.

---

## 7. Interface Published To SPEC B (`identity-coop_07-08-26`)

> **SPEC B MUST exclude `SuppressionEntry` rows with `scope="erased"` from contribution and
> consumption counting.** An erased identity is not a contribution the source site should get credit
> for, and is not a consumable asset for any site. Concretely: any co-op ledger query over
> `beam_identity_graph` must `LEFT JOIN`/`NOT EXISTS` against
> `suppression_list WHERE scope='erased' AND email_hash = beam_identity_graph.email_bidx`
> (the two columns are the same HMAC — see Correction 2). Counting erased rows would let a site earn
> co-op credit for people who asked to be forgotten.

---

## Blast Radius

**Scope:** 18 files (5 new). Packages: `apps/api` (13), `apps/web` (4), `tests` (2 new + 1 edited).

**Risk class: HIGH — three named classes present.**

| Class | Where | Mitigation |
|---|---|---|
| PII / privacy / trust-boundary | queue, tombstone, lookup endpoint | plaintext-free queue; blind index only; structlog keys/ids only; existence-oracle rule (C1); admin gate (C2) |
| Destructive data mutation | `DELETE FROM beam_identity_graph` with no `source_site_id` filter | conditional-UPDATE claim + advisory lock; idempotent; integration test asserts blast radius is exactly the matching identity (T-I5) |
| Public API contract change | C1, C2 | C1 additive-only; C2 new + admin-gated |
| Multi-tenancy | Site A erasing a row Site B wrote | Site A may only enqueue for a `visitor_id` it owns; response reveals nothing about Site B; per-site rate limit; requesting `site_id` audit-logged |

**Backwards compatibility:** C1 is additive. New table only. `is_email_suppressed` signature
preserved. `_upsert_beam_identity` gains a guard that is a no-op for every non-suppressed visitor —
the free-reuse mechanism is untouched for everyone who has not asked to be erased (SPEC Constraint).

**Rollback:** the sweep is the only destructive actor and is kill-switchable via
`graph_erasure_sweep_enabled=false` (no restart-unsafe state). Deleted graph rows are **not**
recoverable — that is intentional (they are the thing being erased) and is why T-I5 pins the blast
radius. Reverting the code leaves the `erasure_requests` table as a harmless orphan.

**Known gaps (carried forward, each keeps its gate CONDITIONAL — none is a silent PASS):**

| ID | Gap | Why deferred | Backlog stub |
|---|---|---|---|
| KG-1 | True race: a `resolve()` mid-flight at the exact instant the sweep commits could re-write a row | Closing needs a distributed lock or re-check-after-write; the observed risk is re-visit-after-deletion (sequential), which IS covered by the guard | `graph-erasure-race-window_NOTE_07-08-26.md` |
| KG-2 | One-time reconciliation of pre-existing graph rows against historical deletion requests | Verified: no historical deletion-request log with sufficient detail exists to cross-reference (SPEC Open Q4). Not actionable. | `graph-erasure-historical-reconciliation_NOTE_07-08-26.md` |
| KG-3 | `CompanyGraphNode` erasure path | Needs a legal read (SPEC Open Q2). `ERASURE_TARGETS` makes it a one-line change once decided. | `company-graph-erasure-legal-read_NOTE_07-08-26.md` |
| KG-4 | AC-7/AC-8 content correctness | Legal judgment; counsel review is a hard SPEC constraint. Only presence is mechanically checkable. | `privacy-copy-counsel-review_NOTE_07-08-26.md` |
| KG-5 | Migration live round-trip | Docker-gated; joins the 13 already pending live-apply | existing pending-migration note |

---

## 9. Feature-Flag Posture (decided explicitly, deviating from precedent — with argument)

Repo precedent is **default OFF** for new operator-gated behavior (`agent_detection_enabled`,
`site_ingest_limit_enabled`, `cadence_bot_flag_enabled`, `promotion_sweep_enabled`).

**Decision: the erasure mechanism ships default ON. This is a deliberate, argued deviation.**

| Component | Flag | Default | Argument |
|---|---|---|---|
| Producer (enqueue) | none | always on | A compliance fix behind an OFF flag ships a fix that does nothing. Deploy-order risk is neutralized by the try/except wrapper (C-11) — a missing table logs a warning and the tenant-facing delete still succeeds. Railway auto-applies migrations on boot anyway. |
| Write-boundary guard | none | always on | It is a *refusal to write*. Failing closed is strictly safer than the status quo and cannot break a non-suppressed visitor. |
| Sweep | `graph_erasure_sweep_enabled` | **`True`** | Precedent flags default OFF because they gate NEW risky *behavior*. This gates the **removal** of data Beam has promised to delete — defaulting OFF means silently retaining it, which is the exact liability this SPEC exists to close. The flag exists as an **operator kill-switch**, not as a rollout gate. |
| Operator lookup | `graph_identity_lookup_enabled` | **`False`** | This one IS an existence oracle. Precedent applies in full — off until an admin gate is confirmed. |
| Rate limit | `graph_erasure_max_per_minute` | `60` | Same shape as `site_ingest_limit_per_minute`. Generous; tune from observed volume. |

Also: `graph_erasure_sweep_interval_minutes: int = 5`, `graph_erasure_max_attempts: int = 5`,
`graph_erasure_stale_processing_minutes: int = 30`.

**Mock mode:** this feature makes **zero external calls** — it is DB-only. `MOCK_EXTERNAL_APIS=true`
therefore needs no new branch. C-19 asserts the whole flow runs green under mock mode with no
network egress.

---

## 10. Implementation Checklist

> Ordered for execution. Every item names its SPEC AC. Do not reorder C-11 vs the DELETE loop.

**Phase A — model + migration**

- **C-01** (AC-1,2,3) Create `apps/api/models/erasure_request.py`: `ErasureRequest` — `id` UUID pk;
  `requesting_site_id` String(50) NOT NULL; `visitor_id` String(64) NOT NULL; `email_bidx_list`
  `ARRAY(String(64))` nullable; `fingerprint_list` `ARRAY(String(64))` nullable; `targets`
  `ARRAY(String(50))` NOT NULL default `list(ERASURE_TARGETS)`; `status` String(20) NOT NULL default
  `"pending"`; `attempts` Integer default 0; `last_error` Text nullable (**must never contain PII —
  truncate to 500 chars and strip email-shaped substrings**); `processed_at`/`created_at`/`updated_at`
  DateTime(tz). Constants: `ERASURE_TARGETS = ("beam_identity_graph",)`,
  `ERASURE_STATUSES = ("pending","processing","done","failed")`.
- **C-02** Indexes: `idx_erasure_requests_status_created` on `(status, created_at)`;
  `idx_erasure_requests_site` on `requesting_site_id`.
- **C-03** (AC-1) Generate the migration. **Run `alembic -c apps/api/alembic.ini heads` LIVE and chain
  `down_revision` onto whatever it reports — do NOT hardcode a head.** 13 migrations are pending
  live-apply and concurrent programs have repeatedly advanced the head. Re-run `heads` immediately
  before applying. Offline validation MUST use an explicit range
  (`alembic upgrade <observed-head>:head --sql`) — `upgrade head --sql` fails mid-chain because
  `b7d3e9f1a4c2_add_ad_connections.py` calls `sa.inspect(bind)`, unsupported against alembic's
  offline `MockConnection`.

**Phase B — suppression tombstone**

- **C-04** (AC-4,5) `services/suppression.py`: add `"erased"` to `VALID_SCOPES`.
- **C-05** (AC-5) `services/suppression.py`: add
  `async def is_email_suppressed_any(db, email, scopes: tuple[str, ...]) -> bool` —
  `SuppressionEntry.scope.in_([*scopes, "all"])`. Rewrite `is_email_suppressed` as a one-line
  delegate. **Signature and behavior of `is_email_suppressed` must not change** (AC-6).
- **C-06** `models/suppression.py`: document `"erased"` in the class docstring —
  `"erased" — graph erasure tombstone; blocks any future cross-tenant graph write`.

**Phase C — sweep service**

- **C-07** (AC-1,2,3) Create `apps/api/services/graph_erasure.py`. Copy the `_try_acquire_lock` /
  `_release_lock` / `async_session`-owning structure from `services/referral_activation.py`
  verbatim in shape; `_LOCK_KEY = "beam_graph_erasure"`.
- **C-08** (AC-1,2) `run_graph_erasure_sweep()`: stale reclaim → conditional-UPDATE claim → per-target
  delete (`DELETE FROM beam_identity_graph WHERE email_bidx = ANY(:b) OR fingerprint = ANY(:f) OR
  fingerprint_v3 = ANY(:f)`, **no `source_site_id` filter**) → tombstone writes (`"erased"` +
  `"do_not_process"`, both via `pg_insert(...).on_conflict_do_nothing(index_elements=["email_hash",
  "scope"])` using the **stored `email_bidx` directly as `email_hash`** — no plaintext available or
  needed) → `status='done'`, `processed_at=now()`.
- **C-09** (AC-3) Failure path: rollback; `attempts >= graph_erasure_max_attempts` → `'failed'`,
  else back to `'pending'`. Sanitize `last_error`. Sweep must never raise out of the job.
- **C-10** (AC-10) `lookup_graph_identity(db, *, email=None, fingerprint=None)` → dict matching C2.
  Matches by `email_hash(email)` against `email_bidx`, or by `fingerprint`/`fingerprint_v3`. Also
  reports whether an `"erased"` tombstone exists for that hash.

**Phase D — producer**

- **C-11** (AC-1) — **ORDERING-CRITICAL, see Correction 4.** In `routers/visitors.py`
  `delete_visitor_data`: after `_verify_site_access` and **BEFORE** the existing 6-table DELETE loop,
  collect match keys (`visitors.fingerprint`, `visitors.fingerprint_v3`,
  `identified_visitors.email`, `visitor_emails.email`, all scoped to `site_id`+`visitor_id`), hash
  every email via `pii_crypto.email_hash` **immediately**, and call `enqueue_erasure(...)`. Enqueuing
  after the DELETE loop yields an empty-keyed, useless request.
- **C-12** (AC-1) Wrap the enqueue in `try/except` → `logger.warning("erasure_enqueue_failed", ...)`
  and continue. The tenant-facing delete must never break. Matches the endpoint's existing
  per-table try/except posture.
- **C-13** (AC-1, existence-oracle CAUTION #1) — **HARD GATE.** The response shape must be identical
  regardless of graph state: always `erasure_request: {id, status:"queued"}`. No match count, no
  boolean, no differing status/HTTP code, no synchronous graph read anywhere in the request path.
  Enforced by test T-I3.
- **C-14** (AC-1) Per-site rate limit `graph_erasure_max_per_minute` → `429` on exceed. Log requesting
  `site_id` on every enqueue (audit).

**Phase E — write-boundary guard (the single `identity_resolver.py` hunk)**

- **C-15** (AC-5,6) In `_upsert_beam_identity`, immediately after the existing
  `if not fp or not email: return` line and **before** the `try:` block:
  re-check `getattr(visitor, "do_not_resolve", False)` and
  `await is_email_suppressed_any(self.db, email, ("erased", "do_not_process"))`; on either, log
  `graph_write_blocked` with `visitor_id=visitor.visitor_id[:8]` **and no email/PII**, then `return`.
  ~6 lines. **Touch nothing else in this file.**
- **C-16** (Correction 1) Fix the stale comment at `models/beam_identity.py:52` — `email_bidx` /
  `email_ciphertext` ARE read and written today. Comment-only; no behavior change. Add NO dual-write.

**Phase F — wiring + operator surface**

- **C-17** `jobs/scheduler.py`: register `_graph_erasure_sweep_job` as an `interval` job at
  `settings.graph_erasure_sweep_interval_minutes`, guarded by `graph_erasure_sweep_enabled`, with an
  explicit `misfire_grace_time` matching the sibling jobs (capacity-hardening Phase 4c convention).
- **C-18** `config.py`: add the settings block from §9 with an inline comment block explaining the
  deliberate default-ON deviation and the kill-switch semantics (match the commenting style of the
  `site_ingest_limit_enabled` block).
- **C-19** (mock mode) Confirm zero external calls; assert the flow is green under
  `MOCK_EXTERNAL_APIS=true` (DB-only feature — no new mock branch required).
- **C-20** (AC-10) `routers/privacy.py`: `GET /graph-identity`, gated by
  `graph_identity_lookup_enabled` **and** an admin dependency. **First discover** the repo's existing
  admin gate — inspect `routers/costs.py`, `routers/request_logs.py`, `routers/feature_requests.py`.
  **If no admin dependency exists, do NOT ship the HTTP route** — implement
  `scripts/graph_identity_lookup.py` instead and record the substitution in the phase report.
  Tenant-reachability of this route is a FAIL.
- **C-21** (AC-10) Add `GraphIdentityLookupOut` Pydantic response model. Return exactly the C2 fields;
  never return `email`, `full_name`, or any ciphertext.

**Phase G — disclosure (requirements only, no copy drafted here)**

- **C-22** (AC-7) `apps/web/public/beam/privacy.html`: add a section that must state, in plain
  language, (a) that identifications made on one Beam customer's site may be reused on other Beam
  customers' sites, (b) what fields are pooled (email, name, city/region/country, fingerprint),
  (c) how to request erasure, (d) a link to the subprocessor/DPA surface if one is added. The
  existing unqualified "we do not share visitor data with third parties" sentence (`:128`) must be
  qualified or removed. **Copy requires privacy counsel — do not publish without review (hard SPEC
  constraint).**
- **C-23** (AC-8) `apps/web/public/beam/terms.html:130-131`: qualify "you own the data you bring to
  Beam" so it does not contradict the shared graph. Same counsel constraint.
- **C-24** (AC-9) Onboarding/pixel-install surface: add a visible plain-language notice with
  `data-testid="cross-tenant-disclosure"` shown **before or during** the pixel-install step.
- **C-25** (AC-7,8,9) Make presence greppable — each of the three surfaces must contain the literal
  marker string `cross-tenant identity` so T-A1 can assert presence mechanically. Presence is NOT
  correctness (KG-4).
- **C-26** Confirm whether `next.config.mjs` rewrites already serve the edited static HTML (they do
  for `/`) — verify no new route wiring is needed for privacy/terms.

**Phase H — tests + backlog**

- **C-27** Write `tests/unit/test_graph_erasure.py` (T-U1…T-U4).
- **C-28** Write `tests/integration/test_graph_erasure_flow.py` (T-I1…T-I6).
- **C-29** Add the AC-9 presence assertion to `apps/web/e2e/onboarding.spec.ts`.
- **C-30** Write the five backlog stubs named in §8 into
  `process/features/visitors-identity/backlog/`.

---

## Verification Evidence

Runner note: `.venv/bin/pytest` has a **broken shebang** in this repo (points to a pre-move path).
Always use `.venv/bin/python3.11 -m pytest`.

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| **T-U1** `_upsert_beam_identity` called directly with `Visitor(do_not_resolve=True)` writes no row and raises nothing; assert log record contains no email substring. `.venv/bin/python3.11 -m pytest tests/unit/test_graph_erasure.py -m unit -q` | Fully-Automated | AC-5 |
| **T-U2** `_upsert_beam_identity` called directly with an email carrying a `scope="erased"` `SuppressionEntry` writes no row. Same command. | Fully-Automated | AC-5, AC-4 |
| **T-U3** `is_email_suppressed(db, e, "do_not_process")` returns identical results before/after the `is_email_suppressed_any` refactor, for scopes `all` / `do_not_process` / `do_not_email` / no-entry. | Fully-Automated | AC-6 |
| **T-U4** blind-index consistency: `pii_crypto.email_hash(e)` equals the value written to `beam_identity_graph.email_bidx`, `identity_signal.email_bidx`, and `suppression_list.email_hash` for the same input — i.e. exactly one hash implementation exists (Correction 2 regression pin). | Fully-Automated | AC-1, AC-4 (key-consistency CAUTION #2) |
| **T-U5** sweep state machine is pure-testable: claim on a non-`pending` row is a no-op; `attempts` increments; `>= max_attempts` → `failed`. | Fully-Automated | AC-3 |
| **T-I1** seed `BeamIdentityNode` for a visitor's fingerprint → `DELETE /{site}/{visitor}/data` → run sweep → assert graph row gone after commit. `.venv/bin/python3.11 -m pytest tests/integration/test_graph_erasure_flow.py -m integration -q` (precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis`) | Hybrid | AC-1 |
| **T-I2** seed graph row with `source_site_id = site_B`; delete from `site_A`'s endpoint for a fingerprint-matching visitor; run sweep; assert identity no longer resolvable. | Hybrid | AC-2 |
| **T-I3** **existence-oracle uniformity**: call the delete endpoint twice — once for a visitor WITH a graph row, once for a visitor WITHOUT — and assert the two response bodies are shape-identical (same keys, same `status`, same HTTP code) and neither leaks a match count. | Hybrid | AC-1 (CAUTION #1) |
| **T-I4** call the delete endpoint twice in sequence + run the sweep twice; assert second call `200`, no exception, graph state unchanged from after the first. | Hybrid | AC-3 |
| **T-I5** **blast-radius pin**: seed 3 graph rows (target identity, an unrelated identity on the same site, an unrelated identity on another site); erase the target; assert exactly ONE row deleted and the other two intact. | Hybrid | AC-1, AC-2 (destructive-class mitigation) |
| **T-I6** after erasure completes, call `resolve()` for the same visitor/fingerprint under conditions that would normally write to the graph; assert no row reappears. | Hybrid | AC-4 (sequential case; race is KG-1) |
| **T-I7** `GET /privacy/graph-identity?email=...` against a seeded row returns `exists=true`, correct `row_count`, correct `contributing_site_ids`; and returns `403`/`404` for a non-admin caller. | Hybrid | AC-10 |
| **T-R1** existing regression suite still green: `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` and `.venv/bin/python3.11 -m pytest tests/ -m integration -q` — with specific attention to `tests/unit/test_agent_origin_exclusion.py` and any `test_company_resolver.py` / suppression tests. | Fully-Automated | AC-6 |
| **T-M1** migration offline validation: `alembic -c apps/api/alembic.ini upgrade <observed-head>:head --sql` (explicit range — see C-03) both directions. Live round-trip on a disposable Postgres is Docker-gated → KG-5. | Hybrid | AC-1 (schema) |
| **T-A1** presence check: `grep -l "cross-tenant identity" apps/web/public/beam/privacy.html apps/web/public/beam/terms.html` returns both files, plus the onboarding component. | Fully-Automated | AC-7, AC-8, AC-9 (presence only) |
| **T-A2** `cd apps/web && npm run test:e2e -- onboarding.spec.ts` — assert `[data-testid="cross-tenant-disclosure"]` is visible on the pixel-install step. Use `await expect(locator).toBeVisible({ timeout: 15_000 })`, never `waitForTimeout` + `isVisible` (canonical Playwright rule). | Fully-Automated | AC-9 (presence half) |
| **T-P1** human/agent content review of privacy.html + terms.html + onboarding copy against §10 C-22/C-23/C-24 requirements. **Counsel review is a hard SPEC constraint and is NOT satisfied by this probe.** | Agent-Probe | AC-7, AC-8, AC-9 (content half) |
| **T-P2** log-inspection probe: run the full flow at DEBUG and confirm no structlog record contains a plaintext email, full name, or ciphertext — only `visitor_id[:8]`, site ids, and counts. | Agent-Probe | Business Guardrail #3 / SPEC PII constraint |

**Vacuous-green note:** every SPEC AC has at least one Fully-Automated or Hybrid proving gate.
AC-7/AC-8 carry a Hybrid presence check + Agent-Probe content review; their content half stays
**CONDITIONAL** pending counsel (KG-4) and is never marked PASS on the presence check alone.

**TDD stubs (Fully-Automated rows only — for the validate-contract, not written to disk in PLAN):**

```
test("T-U1 direct _upsert_beam_identity call with do_not_resolve writes no graph row", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: T-U1")
})
test("T-U2 direct _upsert_beam_identity call with erased tombstone writes no graph row", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: T-U2")
})
test("T-U3 is_email_suppressed behavior unchanged after is_email_suppressed_any refactor", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: T-U3")
})
test("T-U4 exactly one blind-index hash implementation across all four consumers", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: T-U4")
})
test("T-U5 erasure sweep state machine is idempotent on re-claim", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: T-U5")
})
test("T-A1 cross-tenant identity disclosure marker present in all three surfaces", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: T-A1")
})
test("T-A2 onboarding shows cross-tenant-disclosure element", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: T-A2")
})
```

---

## Acceptance Criteria

Every acceptance criterion is inherited verbatim from the SPEC (AC-1 … AC-10). The table below maps
each one to its implementing checklist items, its proving gates, and its current coverage status. A
criterion is only satisfiable when its named gates are green; criteria marked **CONDITIONAL** cannot
reach PASS on a presence check alone.

### AC Coverage Map

| SPEC AC | Checklist items | Gates | Status |
|---|---|---|---|
| AC-1 graph erasure reaches shared graph | C-01…C-03, C-07…C-09, C-11…C-14 | T-I1, T-I3, T-I5, T-M1 | Covered |
| AC-2 works cross-tenant (`source_site_id` ≠ requester) | C-08 (no site filter), C-11 | T-I2, T-I5 | Covered |
| AC-3 idempotent | C-01 (state machine), C-08, C-09 | T-U5, T-I4 | Covered |
| AC-4 no silent re-creation | C-04…C-06, C-08 (dual tombstone), C-15 | T-U2, T-I6 | Covered (sequential); race = KG-1 |
| AC-5 guard at write boundary | C-15 | T-U1, T-U2 | Covered |
| AC-6 no regression of existing guard | C-05 (signature preserved) | T-U3, T-R1 | Covered |
| AC-7 privacy.html | C-22, C-25, C-26 | T-A1 (presence), T-P1 (content) | **CONDITIONAL** — counsel, KG-4 |
| AC-8 terms.html | C-23, C-25, C-26 | T-A1, T-P1 | **CONDITIONAL** — counsel, KG-4 |
| AC-9 onboarding disclosure | C-24, C-25, C-29 | T-A2 (presence), T-P1 (content) | Covered (presence); content CONDITIONAL |
| AC-10 operator lookup | C-10, C-20, C-21 | T-I7 | Covered; endpoint-vs-script is a C-20 discovery branch |

**Deferred with reason:** SPEC Open Q2 (`CompanyGraphNode`) → KG-3. Open Q4 (historical
reconciliation) → KG-2, verified not actionable. Open Q1 (authorization model) → **resolved** by
INNOVATE and implemented as C-11/C-14 (own-visitor scoping + rate limit + audit log).

---

## Phase Completion Rules

This is a single-phase plan (not a phase program), so "phase completion" means plan completion.

| Status | Bar |
|---|---|
| `CODE DONE` | All checklist items C-01…C-30 applied; code compiles; unit lane green. **Not** a completion state on its own. |
| `EVL GREEN` | Every Fully-Automated gate (T-U1…T-U5, T-R1, T-A1, T-A2) exits 0, AND every Hybrid gate (T-I1…T-I7, T-M1) has been run with its precondition satisfied and recorded with its exact command and outcome. |
| `✅ VERIFIED` | Requires explicit user confirmation. `EVL GREEN` **plus** both Agent-Probe gates (T-P1, T-P2) recorded with an explicit judgment, **plus** every open Known Gap (KG-1…KG-5) written as a backlog stub (C-30). |
| **Blocked from `✅ VERIFIED`** | AC-7 and AC-8 content correctness stay **CONDITIONAL** until qualified privacy counsel reviews the copy (hard SPEC constraint, KG-4). The plan may reach `✅ VERIFIED` for the engineering ACs while AC-7/AC-8 content remains CONDITIONAL — this split must be stated explicitly in the phase report, never elided. |

Additional hard rules:

- The plan may **not** be archived while §0's sequencing constraint is unresolved.
- No gate may be marked PASS on a Known-Gap basis. A Known-Gap keeps its criterion CONDITIONAL and
  requires a backlog stub.
- The migration is **offline-validated only** until a live round-trip runs (KG-5); do not claim
  schema verification beyond that.

---

## Test Infra Improvement Notes

- (none identified yet — update during vc-test-coverage-plan / EVL)
- Watch: `tests/conftest.py` Redis-isolation hardening is an open item in
  `post-docker-gate-followups_NOTE_24-07-26.md`; the integration lane here does not use Redis, so it
  should be unaffected, but confirm during EVL.

---

## Resume and Execution Handoff

1. **Selected plan file:**
   `process/features/visitors-identity/active/graph-erasure-compliance_07-08-26/graph-erasure-compliance_PLAN_07-08-26.md`
2. **Last completed phase/step:** PLAN written (07-08-26). No VALIDATE run yet. No code written.
3. **Validate-contract status:** pending — `vc-validate-agent` has not run.
4. **Supporting context loaded:** `process/context/all-context.md`,
   `process/context/tests/all-tests.md`, the SPEC in this task folder, and source-verified reads of
   `models/beam_identity.py`, `models/suppression.py`, `services/suppression.py`,
   `services/pii_crypto.py`, `services/identity_signals.py`, `services/referral_activation.py`,
   `services/identity_resolver.py` (`:149-179`, `:480-520`, `:960-1040`),
   `routers/visitors.py:403-439`, `routers/privacy.py`, `jobs/scheduler.py`, `config.py`.
5. **Next step for a fresh agent:** run VALIDATE (PVL) on this plan. **Do NOT enter EXECUTE** until
   §0's sequencing constraint is satisfied — `identity-vocab-reconcile_07-08-26` must reach
   `Gate: PASS` or be explicitly descoped. On resume, re-read §3 (Corrections) first: `email_bidx` is
   already live, the hash chain is already consistent, and C-11's ordering (enqueue **before** the
   DELETE loop) is the single most likely implementation mistake.

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
