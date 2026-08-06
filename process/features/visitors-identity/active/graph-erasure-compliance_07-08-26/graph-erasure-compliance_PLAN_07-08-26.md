---
name: plan:graph-erasure-compliance
description: "PLAN — cross-tenant beam_identity_graph erasure queue, write-boundary guard, operator lookup, and disclosure requirements"
date: 07-08-26
feature: visitors-identity
---

# PLAN — Cross-Tenant Identity Graph: Erasure & Disclosure Compliance

**Date**: 07-08-26
**Status**: **ACCEPTED — EXECUTE-READY. PVL loop CLOSED at supplement cycle 8 (07-08-26).** Gate remains `CONDITIONAL`, now **explicitly user-accepted** (see `Accepted by:` at the end of the Validate Contract) — literal `Gate: PASS` is structurally unreachable because AC-7/AC-8 need privacy counsel, not engineering, so further PVL rounds converge on nothing by construction. Cycle 7's three findings are RESOLVED, not deferred: the incomplete S12 rebrand (§2 Locked Design, Blast Radius multi-tenancy row, §4 step 2 heading, AC Coverage Map deferred paragraph) is corrected in the plan body this cycle, and F10/F11 plus the `config.py` naming hazard are carried as binding **Execute-Agent Instructions E-1, E-2, E-3**. Accepted residuals unchanged: AC-7/AC-8's permanently-CONDITIONAL content half (KG-4) and open Known Gaps KG-1…KG-9. Live re-derive this cycle: alembic head `c9f4a7b31e85` (single head) and `devjulley`@`5293cbc` — **neither moved**. EXECUTE may proceed against §0's user-sign-off bar, which this acceptance satisfies.
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
**EXECUTE requires explicit user sign-off (§0, restated at supplement cycle 1) — the original
`Gate: PASS` bar on `identity-vocab-reconcile_07-08-26` is unreachable and superseded.**

---

## 0. HARD SEQUENCING CONSTRAINT — read before anything else

> **Restated gate bar (S5, PVL supplement cycle 1).** The file-collision this constraint existed to
> prevent is **resolved in practice**: `identity-vocab-reconcile_07-08-26` is EXECUTED and its
> changes are merged on `devjulley`. VALIDATE independently source-verified every claim this plan
> makes against the post-rebase tree, and the drift audit found no conflict with the
> reconciliation's new `is_privacy_relay_ip` guard or its `_save_identified` `IntegrityError`
> handler — both sit in methods this plan never touches (`_upsert_beam_identity` is the only method
> edited here).
>
> The original bar was a literal `Gate: PASS` on that sibling plan. **That bar will never be met** —
> the user directed "keep the result, fix the plan text" rather than driving it to PASS, so it
> terminated at `Gate: CONDITIONAL, accepted`. The bar is therefore restated as:
>
> **EXECUTE on this plan requires explicit user sign-off, not a literal `Gate: PASS` on
> `identity-vocab-reconcile_07-08-26`.** No agent may grant that sign-off itself.

| Colliding plan | Status (07-08-26) | Overlap with this plan | Action |
|---|---|---|---|
| `identity-vocab-reconcile_07-08-26` | **EXECUTED — result accepted by the user. `Gate: CONDITIONAL`, accepted** (PLAN supplement cycle 9). Its changes are merged and live on `devjulley`. | Rewrites `identity_resolver.py` §3.2 (Tier 2, marked **Highest** risk in its own blast-radius table) AND `routers/visitors.py` (Tier 3) — **both files this plan edits** | **BLOCKING.** Wait for `Gate: PASS` or explicit descope. |
| `identity-program_03-08-26` Phase 1 | PLANNED, not executed | Claims `_save_identified` in `identity_resolver.py` | **NOT blocking.** `_save_identified` is the *caller*; this plan edits `_upsert_beam_identity` (the callee, a separate method). Claim recorded below so that plan can account for it. |
| `identity-coop_07-08-26` (SPEC B) | SPEC phase | Consumes the `SuppressionEntry(scope="erased")` marker this plan publishes | **Downstream.** Interface published in §7. |

**Blast-radius claim published for the two plans above:** this plan touches
`apps/api/services/identity_resolver.py` in exactly **two independently-revertible hunks**, both
inside the method `_upsert_beam_identity` (locate by name, never by line number — see the
**Line-anchor discipline** note below):

- **Hunk A (guard)** — ~6 lines at the top of the method body, before the `pg_insert`.
- **Hunk B (bidx read-path)** — see §3, Correction 1: **NO CODE CHANGE REQUIRED.** `email_bidx` is
  already written here. Hunk B collapses to a *test-only* assertion. Net: this plan modifies
  `identity_resolver.py` in **ONE hunk**, ~6 lines, inside one method. That is the minimum-collision
  scope the SPEC's Constraints section asked for.

No other line of `identity_resolver.py` is touched. `_save_identified`, `resolve()`, and §3.2 are
all untouched by this plan.

**Line-anchor discipline (S3, supplement cycle 1) — binding on every edit site in this plan.**
The `identity-vocab-reconcile` rebase invalidated every line number written at PLAN time. All edit
sites are therefore described by **content anchor** (a quoted, greppable source string + the
enclosing function). Any line number still appearing anywhere in this plan is a **dated
informational snapshot only**, paired with the command that reproduces it. EXECUTE must re-derive,
never trust the number.

| Edit site | Content anchor (authoritative) | Snapshot 07-08-26 | Reproduce with |
|---|---|---|---|
| DELETE endpoint | `@router.delete("/{site_id}/{visitor_id}/data")` → `async def delete_visitor_data` | `visitors.py:405-446` | `git grep -n 'async def delete_visitor_data' apps/api/routers/visitors.py` |
| Graph-write guard | inside `async def _upsert_beam_identity`, immediately after the `if not fp or not email:` / `return` lines and **before** `try:` | `identity_resolver.py:1264-1317` | `git grep -n '_upsert_beam_identity' apps/api/services/identity_resolver.py` |
| Stale bidx comment | the comment line `# Phase 05 (encrypt PII at rest) — added nullable, not yet read/written.` | `beam_identity.py:50` (the `email_bidx` column it precedes is `:52`) | `git grep -n 'not yet read/written' apps/api/models/beam_identity.py` |
| Upstream resolve guards (read-only context) | `if getattr(visitor, "do_not_resolve", False):` and `if await self._is_email_opted_out(visitor):` inside `resolve()` | `identity_resolver.py:548` and `:557` | `git grep -n 'do_not_resolve' apps/api/services/identity_resolver.py` |

Earlier drafts cited three mutually-inconsistent ranges for `_upsert_beam_identity`
(`:995-1030`, `:960-1040`, `:1264`). All three are superseded by the content anchor above.

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
| Queue substrate | New `erasure_requests` table + APScheduler sweep. **Precedent scope (S7, cycle 3): `services/referral_activation.py` is a precedent for the *advisory-lock + conditional-UPDATE idempotency* shape ONLY** — `_try_acquire_lock` / `_release_lock` / owning its own `async_session` / a single conditional `UPDATE ... WHERE <col> IS NULL` whose `rowcount == 0` means another worker won. **It is NOT a precedent for this plan's claim/reclaim state machine.** Verified 07-08-26: that file has **no `processing` state at all**, and `git grep -n "processing\|reclaim\|lease" -- apps/api` returns zero relevant hits — **no sweep in this repo has ever implemented a claim/reclaim lease.** This plan is introducing that mechanic for the first time; it must be specified here, not inherited. |
| State machine | `pending → processing → done \| failed`, with `attempts` and `processed_at`. Idempotent on crash-restart via a stale-`processing` reclaim window. **The claim commits in its own transaction, separate from the destructive work transaction (S7 — see §4a Transaction Boundary Contract, binding).** |
| Matching key | `email_bidx` (HMAC blind index) **and** `fingerprint` / `fingerprint_v3`. **No plaintext email is ever stored in the queue.** |
| Authorization | Any site may enqueue erasure for a visitor row **it owns** (`visitor_id` scoped to that site's own `Visitor`). Matching into the shared graph proceeds regardless of `source_site_id`. A per-site enqueue **volume marker** (`graph_erasure_max_per_minute`) records high-rate enqueues for forensic review — it is **not** a rate limit and enforces nothing (§4b option (b), C-14, KG-8). Requesting `site_id` is persisted for audit. |
| Tombstone | **Reuse `SuppressionEntry` with new scope `"erased"`.** No new tombstone table. It is already platform-level (no `site_id`), already keyed by `email_hash`, already the choke point the resolver consults. |
| Guard hardening | **ONE** guard clause inside `_upsert_beam_identity`: suppression lookup by blind index + defensive `do_not_resolve` re-check. Explicitly NOT a rewrite. |
| `CompanyGraphNode` | Excluded from fan-out today, but the target list is modeled as an **extensible tuple constant** (`ERASURE_TARGETS = ("beam_identity_graph",)`) so a later legal decision needs no schema change |
| Legal copy | Requirements only. WHERE it must appear + a greppable presence check. Text requires counsel. |
| One-time reconciliation | **Not pursued.** No historical deletion-request log with sufficient detail exists. Recorded as KG-2. |

---

## 3. Ground-Truth Corrections Found During Planning

These change the work. EXECUTE must read them before touching code.

**Correction 1 — `email_bidx` is NOT dormant. It is already live.**
The task brief and the model's own comment (`beam_identity.py`, the line `# Phase 05 (encrypt PII
at rest) — added nullable, not yet read/written.`; snapshot `:50`) are **both stale**. Verified in source this session:

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
(which asks for `"do_not_process"`). This is handled deliberately in §4 step 5: the sweep writes
**two** rows — `"erased"` (durable audit marker, SPEC B's interface) and `"do_not_process"` (the
scope the existing upstream check asks for).

**Both rows are written by the same raw `pg_insert(SuppressionEntry)`, using the stored `email_bidx`
directly as `SuppressionEntry.email_hash`** — same HMAC function, same key (Correction 2) — so no
re-hash and no plaintext are involved anywhere in the sweep.

> **`_cascade_suppress` is NOT and CANNOT be called by the sweep (S1, supplement cycle 1).** Earlier
> drafts claimed the sweep reuses it. That is structurally impossible.
> `_cascade_suppress(db, email: str, scope: str)` needs **plaintext throughout** — it computes
> `norm = normalize_email(email)` and then matches `func.lower(IdentifiedVisitor.email) == norm`
> and `VisitorEmail.email == norm`. Its only caller is `add_suppression()`, the one path that holds
> plaintext; there is **no ORM event listener** on `SuppressionEntry` that would fire it implicitly.
> This plan's design is deliberately plaintext-free (§2 "Matching key"; §4 step 3 "never persist
> plaintext"), so by sweep time only `email_bidx` / `fingerprint` exist. Passing a blind index in
> the `email` slot would compute `email_hash(email_bidx)` / `normalize_email(email_bidx)` on garbage
> and silently match nothing — false confidence that a cascade ran. **EXECUTE writes both tombstone
> rows via the raw insert only.**

**Which row actually delivers AC-4 (corrected, S2a).** Earlier prose credited the
`"do_not_process"` row. It does not. The write-boundary guard C-15 calls
`is_email_suppressed_any(db, email, ("erased", "do_not_process"))` — `"erased"` is **already in
that scope tuple**, so the `"erased"` row **alone** trips the guard and blocks every future
cross-tenant graph write on every site. The `"do_not_process"` row is written for a *different*
reason: it is what the **existing, unmodified** upstream `_is_email_opted_out` check (which asks
only for `"do_not_process"`) will see. Two independent hash-based checks; neither depends on
`_cascade_suppress`.

For completeness, since it bears on the coverage hole in §8 **KG-6**: `_cascade_suppress` sets
**`do_not_email` as well as `do_not_resolve`** (`do_not_email=True` on matching `IdentifiedVisitor`
rows; `do_not_resolve=True` on the corresponding `Visitor` rows). Because it never runs here,
**neither** flag is set by this plan's sweep.

**Correction 4 — ordering hazard in the producer.**
`DELETE /{site_id}/{visitor_id}/data` deletes **7** tables (snapshot 07-08-26 — re-derive from the
`for table in (...)` tuple inside `delete_visitor_data`): `resolution_logs`, `identified_visitors`,
`enrichment_profiles`, `events`, `segment_members`, `job_change_events`, `visitors`.
`job_change_events` was added by concurrent work after this plan was drafted, with an inline comment
noting it carries no FK onto `visitors` and would survive an otherwise-complete erasure unless
listed. Among these, `visitors`, `identified_visitors`, and `enrichment_profiles` Those rows hold the **only** source of the visitor's `fingerprint` and email.
**The enqueue MUST read the match keys and INSERT the queue row BEFORE the DELETE loop runs.**
Enqueuing after would always produce an empty-keyed, useless request. This is checklist item C-11
and is the single most likely EXECUTE mistake.

---

## 4. Architecture — Data Flow (prose, per plan contract)

**Producer path (synchronous, inside the existing DELETE request):**

1. `_verify_site_access(db, site_id, user)` — unchanged; enforces `Site.user_id == user.id`.
2. **Per-site enqueue volume-marker check** (`graph_erasure_max_per_minute`) — **a forensic marker,
   not a throttle.** It records `throttle_flagged=True` on the enqueued row and nothing else. It
   NEVER gates, delays, or rejects the request, never excludes the flagged row from processing, and
   the tenant's own local DELETE loop (step 5) always runs (S8 cycle 3, re-scoped by S12 cycle 5 —
   see §4b and C-14).
3. **Collect match keys BEFORE deletion** (Correction 4): `SELECT fingerprint, fingerprint_v3 FROM
   visitors`, plus emails from `identified_visitors.email` and `visitor_emails.email`, all scoped
   `site_id = :sid AND visitor_id = :vid`. Convert each email to `email_hash(email)` immediately;
   **never persist plaintext.**
4. `INSERT INTO erasure_requests (...) VALUES (..., status='pending')`. Wrapped in try/except that
   logs a warning and continues — a missing table or transient failure must never break the
   tenant-facing deletion (matches the endpoint's existing per-table try/except posture).
5. Existing DELETE loop runs unchanged (7 tables as of 07-08-26 — see Correction 4; the count is
   incidental, C-11's rule is "enqueue before **any** delete statement runs").
6. Response is **uniform** (see §5 Public Contracts): always `{"status":"deleted", ...,
   "erasure_request": {"id": ..., "status": "queued"}}` whether or not any graph row exists.

**Sweep path (asynchronous, APScheduler interval job):**

1. `_try_acquire_lock` on `pg_try_advisory_lock(hashtext('beam_graph_erasure'))` — this specific
   helper IS validly copied from `referral_activation.py` (see §2 for the precedent's exact,
   narrow scope).
2. Reclaim stale rows: `UPDATE erasure_requests SET status='pending' WHERE status='processing' AND
   updated_at < now() - interval N` (crash recovery). **This step is only reachable because the
   claim in step 3 commits separately — see §4a Boundary 1.**
3. Claim one row at a time: `UPDATE erasure_requests SET status='processing', attempts=attempts+1,
   updated_at=now() WHERE id=:id AND status='pending' RETURNING ...`. `rowcount == 0` → another
   worker has it; skip. **COMMIT IMMEDIATELY and capture the `RETURNING` values into locals
   (§4a Boundary 1).**
4. **Tombstones are written BEFORE the deletes, inside one work transaction (§4a Boundary 2).**
   For each target in `ERASURE_TARGETS`: `DELETE FROM beam_identity_graph WHERE email_bidx = ANY(:b)
   OR fingerprint = ANY(:f) OR fingerprint_v3 = ANY(:f)`. **No `source_site_id` filter** — this is
   AC-2's mechanism.
5. (Ordering note: steps 4 and 5 execute as **5-then-4** per §4a Boundary 2 — tombstone INSERT
   first, then the DELETEs, in one transaction with no intervening commit. Listed in this order
   here only to keep the AC narrative readable.) Write tombstones: for each stored `email_bidx`, `pg_insert(SuppressionEntry).values(
   email_hash=<the stored bidx>, scope="erased", reason="graph_erasure",
   requested_by=None).on_conflict_do_nothing(...)`, plus the `"do_not_process"` row via the
   **same raw insert** (see C-08). `_cascade_suppress` is never called — it requires plaintext
   (S1, Correction 3).
   **Note:** the stored `email_bidx` *is* a valid `SuppressionEntry.email_hash` — same function, same
   key — so no plaintext is needed at sweep time. This is why the queue can be plaintext-free.
6. `status='done'`, `processed_at=now()`, commit. **On exception → §4a Boundary 3's three-step
   rollback-then-fresh-UPDATE sequence (NOT a same-transaction status write — that would be
   discarded by the rollback).**
7. **Operator visibility (S7 item 4; extended by S11, cycle 5).** Each sweep pass emits one
   structlog line `erasure_queue_health` carrying `pending_count`, `processing_count`,
   `failed_count`, `oldest_pending_age_hours` (computed `now() - MIN(created_at) WHERE status IN
   ('pending','processing')`), and **`oldest_failed_age_hours`** (computed `now() -
   MIN(created_at) WHERE status = 'failed'`) — counts and ages only, **no PII**. The line is
   emitted at `warning` when EITHER `oldest_pending_age_hours > graph_erasure_stale_alert_hours`
   (default `168` = 7 days, well inside GDPR's ~1-month window) **OR `failed_count > 0`**. This is
   checklist item **C-09c**. Operator-reachable read path is **C-20a**.

   > **S11 (cycle 5) — the `failed` blind spot this closes, stated precisely.** The cycle-4
   > SUPPLEMENT REQUEST reported that the health surface "never reads `failed`". That is
   > **partly inaccurate and is corrected here rather than applied blindly**: `failed_count` was
   > already in C-09c's payload and `failed` was already in C-20a's response since cycle 3. What
   > was genuinely missing — and is what actually made the failure silent — is that `failed` was
   > **counted but never alerted, never aged, and never asserted by any gate**: the `warning`
   > trigger keyed only on `oldest_pending_age_hours`, whose `WHERE status IN
   > ('pending','processing')` clause structurally excludes `failed`, so a queue consisting
   > entirely of permanently-failed rows emitted at `info` forever. Combined with C-13's
   > unconditional `200` (the caller was already told the erasure was accepted), a permanently
   > failed erasure was a GDPR-reportable non-erasure that reached **no** operator signal and was
   > invisible to both PVL and EVL. The three additions above (failed age, `failed_count > 0`
   > warning trigger, and the T-U9b gate) close it. Proportionality is unchanged: still one
   > structlog line plus one queryable surface, **no alerting stack**.

   > **S11 — required operator response (a signal with no defined response is half a fix).** When
   > `failed_count > 0`: (1) read the affected rows' `last_error` via C-20a's admin surface or the
   > CLI fallback — `last_error` is PII-sanitized by C-09, so it is safe to read; (2) fix the
   > underlying cause; (3) **re-enqueue by resetting those rows to `status='pending'` with
   > `attempts=0`** — the sweep will re-claim them on its next pass and the operation is idempotent
   > (T-I4), so re-running a partially-completed erasure is safe; (4) if the cause cannot be fixed,
   > the erasure has **not** been performed and the affected data subject's request is unfulfilled
   > — that is a compliance event, not a backlog item, and must be escalated to the user, not
   > silently left in `failed`. Document this four-step response verbatim in the phase report
   > alongside C-20a's check command (**C-20a**).

### §4a — Transaction Boundary Contract (S7, cycle 3 — BINDING on EXECUTE)

The sweep's crash-safety was previously asserted only by analogy. That analogy is void (see §2
"Queue substrate"). The boundary is therefore specified explicitly here. **EXECUTE must implement
exactly this; neither of the two ambiguous readings below is acceptable.**

**Boundary 1 — the claim is its own committed transaction.**
`UPDATE erasure_requests SET status='processing', attempts=attempts+1, updated_at=now()
WHERE id=:id AND status='pending' RETURNING id, attempts, email_bidx_list, fingerprint_list, targets`
→ **`await db.commit()` IMMEDIATELY, before any destructive statement runs.** Capture the
`RETURNING` row into local Python variables at this point — they are the only state that survives
the work transaction's rollback.

Why this is mandatory (both failure readings, stated so EXECUTE cannot pick the wrong one):

- **If the claim shared one transaction with the work** (the literal `referral_activation.py`
  one-commit-per-row shape), a crash mid-row would roll back the `status='processing'` claim *and*
  the `attempts` increment. The row reverts to `pending` with `attempts` unchanged, so
  `attempts >= graph_erasure_max_attempts` **can never trip**, the stale-`processing` reclaim step
  is **dead code**, and a request failing identically forever is byte-for-byte indistinguishable
  from one never attempted. That is a silent infinite retry on a GDPR deadline.
- **Committing the claim separately** is what makes the reclaim window meaningful — and it is why
  Boundary 3 below is required, not optional.

> **✅ INNOVATE OUTCOME APPLIED (S13–S16, PVL supplement cycle 6, 07-08-26) — the cycle-5 `⏸ PENDING
> INNOVATE` marker is cleared.** The parallel INNOVATE review of Boundary 2's enforcement mechanism
> is complete. Verdict, now binding below:
>
> 1. **(S13)** The `async with db.begin():` wrapper is **reclassified from "EXECUTE-agent
>    recommendation / defense-in-depth" to a BINDING checklist requirement**, carrying the same
>    weight as every other rule in §4a. See C-08 and C-08a. This is a status change to guidance the
>    plan already contained — not new architecture.
> 2. **(S14)** `T-U8` / `T-U8b` are rewritten to assert **call sequence and call count on the mocked
>    session** (exactly one `db.commit()` across the whole work-transaction path, strictly after both
>    the tombstone INSERT and the graph DELETE, never between them). A mock genuinely *can* prove
>    "the code never issues an early commit"; it was simply never being asked to. The prior
>    DB-state-shaped assertions were vacuous in the `-m unit` tier (`tests/conftest.py`: "Unit tests:
>    no DB, no network — use mocks").
> 3. **(S15)** The still-missing proof — a live two-connection fault-injection gate against real
>    Postgres — is recorded as its own Known Gap **KG-9**, explicitly distinct from T-U8/T-U8b so no
>    future reader mistakes the unit gates for having proven real Postgres atomicity.
> 4. **(S16)** One residual library assumption is recorded for cheap EXECUTE-time confirmation (see
>    C-08's SQLAlchemy note) rather than as a blocking feasibility probe.
>
> **Rejected by INNOVATE — do not reintroduce:** `begin_nested()` / savepoints (wrong primitive —
> gives recoverability, not atomicity *enforcement*, and a stray `commit()` inside collapses the
> outer transaction anyway); ORM mapper events (structurally inapplicable — both statements are raw
> SQL by design per the `_upsert_beam_identity` precedent, so mapper events never fire); a DB trigger
> (the DELETE's `WHERE` is an OR across `email_bidx` / `fingerprint` / `fingerprint_v3`, so some
> deleted rows carry no `email_bidx` to join a trigger on).
>
> **Deferred, noted only — do NOT design or schedule it here:** a periodic **self-healing
> reconciliation** pass comparing `status='done'` erasure requests against `suppression_list`
> presence would permanently close the *deleted-but-not-tombstoned* direction, because the
> `erasure_requests` row retains its match keys even after reaching `done`. Recorded for whoever
> revisits this area; it is not on any checklist and is not part of this plan.

**Boundary 2 — the destructive work is one transaction, tombstone-first.**
Inside a single work transaction, in this order:

1. **Tombstone INSERT first** — both `SuppressionEntry` rows (`"erased"` + `"do_not_process"`) via
   the single `pg_insert(...).on_conflict_do_nothing(...)`.
2. **Then** `DELETE FROM beam_identity_graph ...` for each target.
3. `await db.commit()`.

**Ordering rationale (S7 item 3, explicit):** the two operations MUST share one transaction, so
under normal operation the ordering is invisible. The ordering is specified for the **partial-commit
pathology** anyway, because a shared transaction is a claim EXECUTE could quietly break by adding an
intermediate `commit()`. Tombstone-first is the safe direction: *tombstoned-but-not-yet-deleted* is
a benign state (the person is already unresolvable and unwritable via C-15's guard; the next sweep
attempt completes the delete). The inverse — *deleted-but-not-tombstoned* — is the harmful state:
the graph rows are gone, nothing records the erasure, and the person is **silently re-addable** on
their next visit to any site. **EXECUTE must not introduce any commit between step 1 and step 2.**

> **VALIDATE cycle-4 precision note (does not change the binding rule above).** Traced mechanically:
> under a genuine single shared transaction (no intervening commit at all), statement order between
> tombstone-INSERT and graph-DELETE cannot by itself produce a durable half-done state, because
> nothing is durable until the final `commit()` — a crash or exception before that commit rolls back
> both statements regardless of which was issued first. The harmful *deleted-but-not-tombstoned*
> state is reachable only if EXECUTE does **two** things at once: (a) commits the DELETE durably
> **before** the tombstone INSERT is durably committed, which in practice means introducing an
> intermediate commit **and** having the DELETE be the side that lands first. Adding an intermediate
> commit strictly *after* the tombstone INSERT (order otherwise unchanged) yields the **benign**
> tombstoned-but-not-deleted state at worst, not the named harmful one — see T-U8 catchability note
> in the Validate Contract §"Design-call findings" for what this means for gate coverage and why a
> code-level `async with db.begin():` wrapper was originally offered as EXECUTE-agent guidance —
> **superseded at supplement cycle 6 (S13): that wrapper is now a BINDING checklist requirement**
> (C-08, C-08a), not optional defense-in-depth.

**Boundary 3 — the failure path re-issues a FRESH update after rollback.**
On exception inside the work transaction:

1. `await db.rollback()` — this discards the work, and **only** the work (the claim is already
   committed by Boundary 1).
2. Open a **new** statement using the `attempts` value captured from the claim's `RETURNING` row
   (the ORM object is expired by the rollback — re-read or use the captured scalar, never the
   stale attribute):
   `UPDATE erasure_requests SET status = :terminal, last_error = :sanitized, updated_at = now()
   WHERE id = :id`, where `:terminal` is `'failed'` when `captured_attempts >= max_attempts`, else
   `'pending'`.
3. `await db.commit()` that update.

**Omitting this re-issue is the failure mode this boundary exists to prevent:** without it the row
wedges at `status='processing'` for the full `graph_erasure_stale_processing_minutes` window on
every single failure, converting each transient error into a 30-minute stall on a ~1-month legal
clock. This is checklist item **C-09b** and carries its own proving gate (T-U7).

### §4b — Enqueue Volume Marker Semantics (S8 cycle 3; **re-scoped by S12, cycle 5** — BINDING on EXECUTE)

> **S12 (cycle 5) — DECISION: option (b), honest forensics. `graph_erasure_max_per_minute` is a
> volumetric abuse RECORD, not a throttle. It prevents nothing, and this plan now says so plainly
> instead of implying otherwise.**
>
> **The mismatch this resolves (cycle-4 verifier, confirmed in source 07-08-26).**
> `throttle_flagged` was written (C-01, this section, C-14) and displayed (C-20a's
> `throttle_flagged_count`), but the sweep's claim query C-08 is
> `... WHERE id=:id AND status='pending'` with **no `throttle_flagged` filter** — so a flagged row
> executed its irreversible cross-tenant `DELETE FROM beam_identity_graph` identically to an
> unflagged one. The cited precedent does not work that way: `rate_limiter.py::site_ceiling_tripped()`
> ties flag-but-store to real **exclusion** in its own docstring ("still stored, just marked
> `is_flagged_abuse` so it is **excluded downstream**"), and `is_flagged_abuse`/`is_abuse_flagged`
> genuinely filter (`FILTER (WHERE NOT is_flagged_abuse)` clauses in
> `services/visitor_aggregator.py`) and genuinely gate `is_emailable_identity()` at three call sites
> (`services/campaign_sender.py:316`, `services/csv_exporter.py:87`,
> `routers/campaigns.py:733` — all re-verified live this cycle). The prior text copied the
> precedent's cosmetic shape while omitting the one property that gave it security value.
>
> **Why (b) and not (a) real exclusion.** Option (a) — hold flagged rows back from the claim query
> pending explicit operator release — was considered and **rejected**, for three reasons:
> 1. On a GDPR clock with no ops rotation (solo-founder codebase), "held pending manual release" is
>    functionally indistinguishable from "dropped" — which is the exact liability §4b was written to
>    avoid ("dropping the enqueue would silently fail to erase a person who asked to be forgotten").
>    It would also collide directly with S11: held rows would age silently in `pending`, which is
>    precisely the blind spot S11 just closed.
> 2. It buys ~no security. The named attack is **KG-7**: two HTTP requests, far inside 60/min. A
>    burst limiter cannot see a single precision request, so exclusion-on-trip would not close
>    KG-7 and would not close KG-8 either — both need the cumulative/authorization work already
>    scoped forward.
> 3. It would introduce a *new* irreversible-inaction failure mode (a real erasure request wedged
>    behind an operator who never looks) to defend against an attack it demonstrably cannot detect.
>
> **What (b) obliges this plan to say plainly (done below and in C-14/KG-8):** the mechanism
> **records** volumetric abuse for after-the-fact review and **does not prevent it**. No text in
> this plan may describe it as an abuse control, a limit, or a defense.

**The volume marker gates NOTHING. It must never gate the tenant's own local deletion, and — per
S12 — it must never gate the cross-tenant enqueue or the sweep's processing of it either.**

Two independent reasons, both source-verified 07-08-26:

- **(a) Gating the whole request is a functional regression on a GDPR-critical endpoint.**
  `DELETE /{site_id}/{visitor_id}/data` (anchor: `async def delete_visitor_data`) has **no rate
  limiter today** — confirmed by direct read. A tenant running a legitimate bulk cleanup (purging
  stale test visitors, or honoring a batch of their *own* users' deletion requests) past the limit
  would get a hard `429` **and their own local rows would never be deleted.** A feature added to
  strengthen compliance would weaken it.
- **(b) It contradicts the precedent it cites.** `services/rate_limiter.py::site_ceiling_tripped()`
  is explicit in its own docstring: *"Deliberately NOT a slowapi `@limit` decorator: a decorator
  hard-rejects with 429, while the locked design for a ceiling trip is Option C (flag-but-store) —
  the request is still answered … and still stored"*, and `routers/events.py` repeats it: *"a
  tripped signal NEVER rejects the request."* Only the body-size guard (P1) hard-rejects, "because
  that is a different failure class."

**Locked behavior on trip (S12-clarified):** the local DELETE loop proceeds unchanged and the
response is the normal `200`. The enqueue is **written anyway, with `status='pending'` and a
`throttle_flagged=True` marker column**, and a `logger.warning("erasure_enqueue_throttled",
site_id=..., visitor_id=visitor_id[:8])` is emitted. **The sweep then claims and processes that row
exactly as it claims any other — C-08's claim query has no `throttle_flagged` filter and MUST NOT
grow one. The flag is forensic metadata only; it changes no execution path anywhere.** Proving
gate: **T-I10 (new, S12 cycle 5)**, which asserts a flagged row is in fact claimed and processed —
previously *no gate anywhere* asserted a flagged row's subsequent claim/processing behavior, so the
security-relevant half of this design was unverified on the plan's own terms.

**Queued-but-flagged, NOT dropped — rationale.** Dropping the enqueue would silently fail to erase
a person who asked to be forgotten, which is the exact liability this SPEC exists to close;
flag-but-store matches the repo's own Option C precedent and keeps the abuse signal reviewable.
The response shape is unchanged, so this does not violate C-13's existence-oracle rule (the flag is
never surfaced to the caller).

> **VALIDATE cycle-4 confirmation, re-scoped by S12: `throttle_flagged` has a real downstream
> reader, it is not a dead column — but that reader is a *reporting* surface, not a control.**
> C-20a's queue-health `throttle_flagged_count` is the sole consumer: narrower than, but the same
> shape as, the `source_site_id` precedent (written everywhere, read by exactly one delete
> cascade). Under S12 this is **the correct and complete extent of the column's job**: it exists to
> be read by a human reviewing volume after the fact. Any future change that makes
> `throttle_flagged` alter execution is a design change requiring a fresh decision, not an
> implementation detail.

> **Residual (S8, disclosed; widened by S12 — NOT closed by this plan): there is no erasure abuse
> control at all.** The marker is per-minute only, has no cumulative daily/lifetime cap, no anomaly
> review, and — per S12 — **no enforcement of any kind**: a flagged request is executed exactly like
> an unflagged one. A patient attacker staying under 60/min can enqueue tens of thousands of
> irreversible cross-tenant erasures per day, and an *impatient* one who trips the marker is
> likewise not stopped, merely recorded. This is **deferred and disclosed, not silently omitted** —
> recorded as **KG-8** with a backlog stub. Do not read this mechanism as an abuse control of any
> description.

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
| 4 | `apps/api/routers/visitors.py` — fn `delete_visitor_data` (snapshot `:405-446`; anchor per §0) | becomes a producer: collect keys → enqueue → existing DELETE loop | edit |
| 5 | `apps/api/services/identity_resolver.py` — fn `_upsert_beam_identity` (snapshot `:1264-1317`; anchor per §0) | **ONE hunk**, ~6-line guard clause. Nothing else. | edit |
| 6 | `apps/api/services/suppression.py` | add `"erased"` to `VALID_SCOPES`; add `is_email_suppressed_any()`; keep `is_email_suppressed()` as a thin delegate | edit (additive) |
| 7 | `apps/api/models/suppression.py` | docstring: document `"erased"` scope | edit (docstring) |
| 8 | `apps/api/models/beam_identity.py` — comment `not yet read/written` (snapshot `:50`; anchor per §0) | fix stale "not yet read/written" comment (Correction 1) | edit (comment) |
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

> **Observation (S4, NOT fixed here): `visitor_emails` is NOT deleted by this endpoint** — today or
> after this change (confirmed absent from the 7-table tuple; model
> `apps/api/models/visitor_email.py`). A visitor's first-party-captured plaintext email therefore
> survives an otherwise-"complete" per-visitor erasure **in the visitor's own tenant**. This
> predates the plan and is outside this SPEC's scope (cross-tenant graph + disclosure surfaces
> only). Backlog pointer only: `visitor-emails-erasure-gap_NOTE_07-08-26.md` (added to C-30).

**Read-for-context (not modified):** `apps/api/services/referral_activation.py` (**advisory-lock +
conditional-UPDATE idempotency shape ONLY — it has no `processing` state and is NOT a state-machine
precedent; see §2 and §4a**),
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
> introduced by a privacy feature. **The only new failure mode is `404`** (unknown/foreign
> `site_id`, per multi-tenancy rule — never `403`). **This endpoint returns no `429`** — the
> per-site enqueue throttle is flag-but-store: it gates the cross-tenant enqueue only, never the
> request or the tenant's own local DELETE (S8, §4b).

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
| Multi-tenancy | Site A erasing a row Site B wrote | Site A may only enqueue for a `visitor_id` it owns; response reveals nothing about Site B; requesting `site_id` audit-logged. **No rate/volume control mitigates this risk** — `graph_erasure_max_per_minute` is a forensic marker that enforces nothing (§4b option (b), KG-8), and own-visitor scoping itself is bypassable via a client-supplied `_fp` (KG-7). Both residuals are disclosed, not closed. |

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
| KG-6 | **Other tenants' pre-existing `IdentifiedVisitor` rows are never touched by erasure.** The graph-write half of the cross-tenant promise is real — `_upsert_beam_identity` is the sole write path into `beam_identity_graph`, and C-15's guard stops every future write on every site. But rows another tenant *already holds* are reachable only via `_cascade_suppress`'s plaintext matching, which this plaintext-free sweep structurally cannot perform (S1). **Scenario:** Person P is identified on Site A and, independently, already has an `IdentifiedVisitor` row on Site B from Site B's own paid-provider lookup weeks earlier, currently sitting in Site B's active outreach segment. P requests erasure at Site A. The sweep hard-deletes the `beam_identity_graph` rows and writes both tombstones — but nothing ever sets `do_not_email`/`do_not_resolve` on Site B's existing row. **Site B keeps sending campaign email to P and keeps resolving P on return visits, after P's erasure was accepted and reported complete.** That is the exact harm the SPEC exists to close. | Closing it needs either a plaintext-bearing erasure path (contradicting this plan's plaintext-free queue constraint) or a different matching key on `IdentifiedVisitor`/`VisitorEmail` (e.g. a blind-index column those tables do not have today). **That design is deliberately NOT attempted here.** Scoping recommendation: a **Phase 2 / follow-up plan** — NOT an in-scope fix for this plan, and NOT a SPEC out-of-scope item, since the SPEC's intent covers this harm. Surface for the user's scoping decision; do not silently drop. | `cross-tenant-identified-visitor-erasure-gap_NOTE_07-08-26.md` |
| KG-7 | **The erasure authorization model is mitigated, not structurally prevented (S9, cycle 3).** C-11/C-14 require the requesting site to own the `visitor_id` — they do **not** require that the fingerprint on that visitor row was genuinely produced by the target person's browser. Verified in source: `routers/events.py` accepts a **client-supplied `_fp`** on every ingest event with no server-side re-derivation, signature, or session binding. **Scenario:** an attacker sends one crafted ingest event carrying a victim's fingerprint from their own site (creating a `Visitor` row they legitimately own), then calls `DELETE /{their_site}/{that_visitor}/data`. C-11 collects the spoofed fingerprint and the sweep's `DELETE FROM beam_identity_graph WHERE fingerprint = ANY(:f)` — **no `source_site_id` filter, by design (AC-2)** — erases the victim's real, paid-for graph row. Cost: two HTTP requests, far inside `graph_erasure_max_per_minute`. The throttle is a burst limiter, useless against a single precision request; the audit trail is forensic only, and per C-13's existence-oracle rule the victim is never notified. The SPEC's own Risk §2 names this and requires it be "explicitly designed against in PLAN" — this plan **discloses** it rather than closing it. | Closing it needs either server-side fingerprint corroboration (dwell/session-history minimums before a visitor becomes erasure-eligible) or a different authorization model entirely — product/security judgment, not an engineering-only fix, and out of scope here. **No fix is attempted; this is scoped, not designed.** | `graph-erasure-authorization-spoofing-gap_NOTE_07-08-26.md` |
| KG-8 | **No erasure abuse control of any kind (S8 cycle 3; widened by S12 cycle 5).** `graph_erasure_max_per_minute` is per-minute only **and, per §4b option (b), enforces nothing**: a request that trips it is marked `throttle_flagged=True` and then claimed, processed, and executed identically to any other — the marker is a forensic record for after-the-fact human review, not a defense. So both a patient attacker (staying under 60/min, enqueuing tens of thousands of irreversible cross-tenant erasures per day) **and** a fast one (tripping the marker and being merely logged) proceed unimpeded. Compounds KG-7. | A cumulative daily/lifetime cap plus an anomaly-review surface is a separate design decision (what threshold, what happens on trip, who reviews) and would need the same product/security judgment as KG-7. **Deferred explicitly, not silently omitted.** | `graph-erasure-cumulative-cap_NOTE_07-08-26.md` |
| KG-9 | **No live fault-injection proof of Boundary 2's atomicity (S15, cycle 6 — distinct from T-U8/T-U8b).** T-U8 and T-U8b prove *code shape* only: that the implementation issues no intervening `commit()` (see the code-shape note above the AC map). **Nothing in this plan proves the real-Postgres half.** The missing gate: against a real Postgres, kill or fail the connection *between* the tombstone INSERT and the graph DELETE inside the work transaction, with a **second connection** asserting that either both rows are durable or neither is. No such mid-transaction fault-injection pattern exists anywhere in `tests/integration/` today, so this needs new test infra, not just a new test. **Do not read T-U8/T-U8b as covering this.** | Docker-gated (needs a disposable Postgres plus a second observing connection), and it requires a fault-injection harness this repo has never had — same posture as every other Hybrid gate in this plan. Deferred explicitly, not silently omitted; the code-shape gates plus Postgres's own ACID guarantees are the accepted interim argument. | `graph-erasure-boundary2-live-fault-injection_NOTE_07-08-26.md` |
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
| Enqueue **volume marker** (S12 — not a throttle) | `graph_erasure_max_per_minute` | `60` | Same *shape* as `site_ingest_limit_per_minute`, but **weaker by design (§4b option (b)): it never rejects the request, never blocks the tenant's own local DELETE, and — unlike the `is_flagged_abuse` precedent — never excludes the flagged row downstream.** A tripped marker sets `throttle_flagged=True` and nothing else; the row is still claimed and processed (T-I10). Generous; tune from observed volume. **Not an abuse control of any kind — see KG-8.** |

Also: `graph_erasure_sweep_interval_minutes: int = 5`, `graph_erasure_max_attempts: int = 5`,
`graph_erasure_stale_processing_minutes: int = 30`,
`graph_erasure_stale_alert_hours: int = 168` (S7 item 4 — age at which `erasure_queue_health` logs
at `warning`; 7 days, deliberately well inside GDPR's ~1-month response window so a stuck queue is
visible with weeks of slack).

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
  `"pending"`; `attempts` Integer default 0; `throttle_flagged` Boolean NOT NULL default `False` (S8/§4b, S12 —
  set when the per-minute enqueue **volume marker** tripped; the enqueue is still written **and is
  still claimed and processed normally**. Forensic metadata for C-20a's `throttle_flagged_count`
  only — **it must never appear in a WHERE clause on any execution path**); `last_error` Text nullable (**must never contain PII —
  truncate to 500 chars and strip email-shaped substrings**); `processed_at`/`created_at`/`updated_at`
  DateTime(tz). Constants: `ERASURE_TARGETS = ("beam_identity_graph",)`,
  `ERASURE_STATUSES = ("pending","processing","done","failed")`.
- **C-02** Indexes: `idx_erasure_requests_status_created` on `(status, created_at)`;
  `idx_erasure_requests_site` on `requesting_site_id`.
- **C-03** (AC-1) Generate the migration. **Run `alembic -c apps/api/alembic.ini heads` LIVE and chain
  `down_revision` onto whatever it reports — do NOT hardcode a head.** Concurrent programs
  repeatedly advance the head. **Snapshot 07-08-26: 63 migration files, single head
  `c9f4a7b31e85` (`add_ws2_agent_operated_flag`), no fork** — reproduce with
  `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads`. Treat that value as
  already stale; re-run `heads` immediately before generating, and again before applying. (Note for
  anyone parsing the revision graph by hand instead: `d4c7b2a9e6f1` and `f7c2e9a4b1d3` carry
  multi-line merge tuples that a naive regex misreads as extra heads.) Offline validation MUST use an explicit range
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
  verbatim in shape; `_LOCK_KEY = "beam_graph_erasure"`. **Copy NOTHING ELSE from that file.** Its
  transaction shape (one `db.commit()` per row, after all work succeeds) is the WRONG shape here —
  it has no `processing` state and no lease. The claim/work/failure boundaries are specified in
  **§4a** and are binding.
- **C-08** (AC-1,2) — **S12 note (cycle 5): the claim query is
  `... WHERE id=:id AND status='pending'` and MUST NOT gain a `throttle_flagged` filter.** Flagged
  rows are claimed and processed identically to unflagged rows, by design (§4b option (b)); proving
  gate T-I10.
  `run_graph_erasure_sweep()`: stale reclaim → conditional-UPDATE claim
  **→ `await db.commit()` the claim on its own, capturing the `RETURNING` values into locals
  BEFORE any destructive statement (§4a Boundary 1; proving gate T-U6)** → **tombstone writes
  FIRST, then** per-target
  delete (`DELETE FROM beam_identity_graph WHERE email_bidx = ANY(:b) OR fingerprint = ANY(:f) OR
  fingerprint_v3 = ANY(:f)`, **no `source_site_id` filter**) → tombstone writes (`"erased"` +
  `"do_not_process"`, both via `pg_insert(...).on_conflict_do_nothing(index_elements=["email_hash",
  "scope"])` using the **stored `email_bidx` directly as `email_hash`** — no plaintext available or
  needed) → `status='done'`, `processed_at=now()`. **BINDING (S13, supplement cycle 6 — reclassified from
  guidance): Boundary 2's tombstone-then-delete pair MUST be implemented inside a single explicit
  `async with db.begin():` block (or an equivalent single-transaction context manager), never as two
  bare statements plus a trailing `commit()`. This makes "no intervening commit" structurally obvious
  at the call site rather than prose-only, and it is what T-U8/T-U8b's call-sequence assertions are
  written against.** Proving gates: T-U8 + T-U8b (call-sequence, unit tier) and — for real Postgres
  atomicity, which those gates do NOT prove — **KG-9** (§8).
  - **SQLAlchemy residual to confirm cheaply at EXECUTE (S16, cycle 6 — NOT a blocking probe).**
    This repo pins `sqlalchemy[asyncio]==2.0.35` (`requirements.txt:7`). INNOVATE flagged, without
    empirically probing it, that calling `AsyncSession.begin()` **immediately after a commit with no
    intervening statements** should cleanly open a new transaction rather than raise an autobegin
    conflict — this is documented SQLAlchemy 2.0 behavior and confidence is high, but it is
    unverified in this repo. EXECUTE confirms it with a ~5-line throwaway scratch script (open
    session → `await db.commit()` → `async with db.begin():` → trivial `SELECT 1`) before wiring the
    real sweep. If it raises, the fix is a plain `await db.begin()` guard, not a design change.
- **C-08a** (AC-3, §4a Boundary 2) Tombstone INSERT and the `beam_identity_graph` DELETEs share
  **one** work transaction with **no intervening commit**, tombstone-first. *Deleted-but-not-
  tombstoned* leaves the person silently re-addable and is the state this ordering exists to
  prevent. **The `async with db.begin():` wrapper in C-08 is BINDING for this pair (S13, cycle 6).**
  Proving gates: **T-U8 and T-U8b (rewritten at cycle 6 as call-sequence/call-count assertions on the
  mocked session — see Verification Evidence)**. Those gates prove *code shape only*; real Postgres
  atomicity under a mid-statement fault is **KG-9**, an open Known Gap.
- **C-09** (AC-3) Failure path, step 1 of 3: `await db.rollback()`. This discards the work only —
  the claim and its `attempts` increment are already committed by C-08. Sanitize `last_error`
  (truncate 500 chars, strip email-shaped substrings). Sweep must never raise out of the job.
- **C-09b** (AC-3, §4a Boundary 3) — **REQUIRED, easily missed.** Failure path, steps 2-3: after the
  rollback, issue a **FRESH** `UPDATE erasure_requests SET status=:terminal, last_error=:sanitized,
  updated_at=now() WHERE id=:id` using the `attempts` value **captured from the claim's `RETURNING`
  row** (the ORM object is expired by the rollback — never read the stale attribute), then commit
  it. `:terminal` = `'failed'` when `captured_attempts >= graph_erasure_max_attempts`, else
  `'pending'`. Omitting this wedges the row at `status='processing'` for the full
  `graph_erasure_stale_processing_minutes` window on every failure. Proving gate: **T-U7**.
- **C-09c** (S7 item 4 + **S11 cycle 5** — operator visibility) At the end of every sweep pass emit
  one structlog line `erasure_queue_health` with `pending_count`, `processing_count`,
  `failed_count`, `oldest_pending_age_hours` (= `now() - MIN(created_at) WHERE status IN
  ('pending','processing')`), and **`oldest_failed_age_hours`** (= `now() - MIN(created_at) WHERE
  status = 'failed'`; `None`/omitted when `failed_count == 0`). Counts and ages only — **no PII, no
  email, no bidx**. Emit at `warning` level when **either**
  `oldest_pending_age_hours > settings.graph_erasure_stale_alert_hours` **or `failed_count > 0`**
  (S11 — a permanently-failed erasure is the *worst* silent outcome, not a lesser one: the caller
  already received an unconditional `200` per C-13 while the graph row is retained. It must never
  be reachable only at `info`). Proving gates: T-U9 **and T-U9b (new, S11 cycle 5)**.
- **C-10** (AC-10) `lookup_graph_identity(db, *, email=None, fingerprint=None)` → dict matching C2.
  Matches by `email_hash(email)` against `email_bidx`, or by `fingerprint`/`fingerprint_v3`. Also
  reports whether an `"erased"` tombstone exists for that hash.

**Phase D — producer**

- **C-11** (AC-1) — **ORDERING-CRITICAL, see Correction 4.** In `routers/visitors.py`
  `delete_visitor_data`: after `_verify_site_access` and **BEFORE** the existing DELETE loop (7
  tables as of 07-08-26 — the count is incidental; the rule is "before **any** delete statement"),
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
- **C-14** (AC-1, S8/§4b, **re-scoped by S12 cycle 5**) — **SCOPE-CRITICAL.** Per-site enqueue
  **volume marker** `graph_erasure_max_per_minute` **gates nothing.** It **MUST NOT** return `429`,
  MUST NOT short-circuit the handler, MUST NOT be placed before the DELETE loop as a request gate,
  and — per S12 — **MUST NOT be turned into a filter on C-08's claim query or on any other
  execution path.** On trip: still write the `erasure_requests` row with `throttle_flagged=True`,
  log `logger.warning("erasure_enqueue_throttled", site_id=..., visitor_id=visitor_id[:8])`, and
  let the local DELETE loop and the normal `200` response proceed untouched. The sweep then
  processes that row normally.

  **Naming discipline (S12, binding):** this is **not** a throttle and **not** an abuse control.
  It **records** volumetric abuse for after-the-fact human review and **prevents nothing**. The
  `is_flagged_abuse` precedent it was originally modelled on *does* enforce exclusion downstream;
  this one deliberately does not, because exclusion on a GDPR erasure queue would create a worse
  failure (a real erasure wedged behind manual release — see §4b's rejection of option (a)) while
  still failing to stop the actual named attack (KG-7, a single precision request). EXECUTE must
  not describe it as a limit in code comments, log messages, or the phase report.

  Hard-rejecting here would additionally be a functional regression: this endpoint has **no limiter
  today**, so a tenant's legitimate bulk cleanup would start failing to delete their **own** local
  rows. Log requesting `site_id` on every enqueue (audit). Proving gates: **T-I8** (the request is
  never rejected) **and T-I10** (the flagged row is nonetheless claimed and processed).

**Phase E — write-boundary guard (the single `identity_resolver.py` hunk)**

- **C-15** (AC-5,6) In `_upsert_beam_identity`, immediately after the existing
  `if not fp or not email: return` line and **before** the `try:` block:
  re-check `getattr(visitor, "do_not_resolve", False)` and
  `await is_email_suppressed_any(self.db, email, ("erased", "do_not_process"))`; on either, log
  `graph_write_blocked` with `visitor_id=visitor.visitor_id[:8]` **and no email/PII**, then `return`.
  ~6 lines. **Touch nothing else in this file.**
- **C-16** (Correction 1) Fix the stale comment in `models/beam_identity.py` — locate by content
  (`git grep -n 'not yet read/written' apps/api/models/beam_identity.py`; snapshot `:50`) — `email_bidx` /
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
- **C-20a** (S7 item 4 — operator visibility read path) Behind the same admin gate as C-20, expose
  the queue-health counters: preferred as `GET /privacy/erasure-queue-health` returning
  `{pending, processing, failed, oldest_pending_age_hours, oldest_failed_age_hours,
  throttle_flagged_count}` — **counts and
  ages only, never a request row, never a bidx or fingerprint**. **`oldest_failed_age_hours` is
  the S11 (cycle 5) addition; it must be reconciled with C-09c's log payload so the two surfaces
  never disagree about what `failed` looks like.** If C-20's discovery branch lands
  on the CLI fallback, put the same query in `scripts/graph_identity_lookup.py --queue-health`
  instead. Proportionate to a solo-founder codebase: a queryable surface plus C-09c's log line —
  **do not build an alerting stack.** Document the check (command + what "stuck" looks like) in the
  phase report — **and, per S11, document the four-step `failed_count > 0` operator response
  verbatim from §4 step 7 alongside it.** Proving gate: T-I9 **(strengthened at VALIDATE cycle 4 to also assert
  `throttle_flagged_count` — see T-I9 in Verification Evidence).**
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
- **C-30** Write the backlog stubs named in §8 (KG-1…KG-9) **plus** the S4 observation stub
  `visitor-emails-erasure-gap_NOTE_07-08-26.md` into
  `process/features/visitors-identity/backlog/`. That is **ten** stubs (seven → nine at supplement
  cycle 3 with +KG-7/+KG-8; → ten at cycle 6 with **+KG-9**, whose stub
  `graph-erasure-boundary2-live-fault-injection_NOTE_07-08-26.md` is **already written** — C-30 need
  only verify its presence).

---

## Execute-Agent Instructions (from PVL cycles 7–8 — binding on EXECUTE)

These are corrections carried forward as EXECUTE-time instructions rather than another PLAN →
VALIDATE round-trip, per the E-8/E-9 precedent in the sibling plan
`identity-vocab-reconcile_07-08-26`. They are plan-text and test-spec defects, not design defects —
the design has been stable since PVL cycle 3. **They override the literal wording of the
Verification Evidence rows they name.**

### E-1 — T-U8 / T-U8b MUST NOT assert on `db.commit()` for Boundary 2

**Status of the finding:** empirically proven, twice, by two independent review passes that each ran
real code against the pinned `sqlalchemy[asyncio]==2.0.35` (`requirements.txt:7`).

**Ground truth.** `AsyncSession.begin()` is a **synchronous** method returning an
`AsyncSessionTransaction`, whose `__aexit__` calls `self._sync_transaction().__exit__(...)`. It
**never** calls `AsyncSession.commit()`. Three executed probes:

1. A plain `AsyncMock()` makes `db.begin()` return a coroutine, so `async with db.begin():` raises
   `TypeError` before any assertion runs.
2. With a faithful mock, the **correct** (C-08-binding) implementation records **zero**
   `db.commit()` calls — so "exactly one commit" **fails on correct code and passes on the broken**
   bare-statements-plus-trailing-`commit()` shape. Inverted from its purpose.
3. Hand-wiring `__aexit__` to call `db.commit()` is the only way the correct shape passes, but then
   both shapes produce identical `mock_calls` — the gate cannot distinguish the two things it exists
   to distinguish.

**The instruction.** For §4a **Boundary 2**, T-U8 and T-U8b MUST assert on:

- `db.begin.call_count` (exactly one work-transaction scope opened);
- `db.begin.return_value.__aexit__` — its call count **and** its exception info (`exc_type is None`
  on the happy path; the raised exception on the failure path);
- `db.execute.call_args_list` **ordering** — the tombstone `pg_insert` issued strictly before the
  `beam_identity_graph` DELETE, with nothing between them.

They MUST **NOT** assert on `db.commit()` for this boundary at all. (T-U6's Boundary-1 claim-commit
assertion is a different transaction and is unaffected — keep it.)

**Mocking-precedent warning — read before writing the test.** This pattern has **no precedent in
this repo.** `tests/unit/test_identity_signals.py`, `test_company_graph.py`, and
`test_agent_marker.py` all mock a flat `db.commit = AsyncMock()`; **none** mocks a context manager.
Repo-wide, `db.begin()` / `session.begin()` has **zero** hits under `tests/` and exactly one in
production (`apps/api/main.py:92` — an `AsyncEngine`, a different class). The mock must therefore be
**built deliberately** (a `MagicMock` whose `begin()` returns an object with `AsyncMock`
`__aenter__` / `__aexit__`), **not** copied from an existing test.

**Propagation:** the one-line correction has been applied to the interim-argument paragraph of
`process/features/visitors-identity/backlog/graph-erasure-boundary2-live-fault-injection_NOTE_07-08-26.md`
(KG-9's stub), which previously repeated the refuted `commit()`-count claim.

### E-2 — T-I10's source assertion MUST be narrowed to the claim query

As written, T-I10 asserts `git grep -n throttle_flagged apps/api/services/graph_erasure.py` returns
nothing. But Touchpoint 3 places `enqueue_erasure()` in that same file, and C-01 / C-14 **require**
it to write `throttle_flagged=True` on trip. Correct code therefore makes that grep match, and the
gate false-fails.

**The instruction.** The real claim is narrower: *the sweep's claim query does not filter on
`throttle_flagged`*. Scope the assertion to the claim-query function / SQL statement (e.g. read the
claim-query function body, or grep within its line range) — **never** to the whole file.

### E-3 — `graph_erasure_max_per_minute` MUST carry an inline "not a cap" comment

The S12 rebrand (§4b option (b), C-14, C-01, KG-8) makes this setting a **forensic volume marker**,
not an enforced limit. The setting name still reads like a cap.

**The instruction.** When adding `graph_erasure_max_per_minute` to `apps/api/config.py`, attach an
inline comment stating, in substance: *this is the threshold for a forensic volume marker, NOT an
enforced cap — exceeding it sets `throttle_flagged=True` for after-the-fact review and changes no
execution path; the request is never rejected and the flagged row is claimed and processed
identically (C-14, §4b, KG-8).* Without it a future reader will assume the 61st request fails, which
C-14 binds it MUST NOT.

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
| **T-U6** (S7/§4a Boundary 1) claim-commit boundary: after `run_graph_erasure_sweep()` raises inside the destructive work (patched to throw), assert the row's `status` is NOT `'pending'`-with-unchanged-`attempts` — i.e. the `attempts` increment **survived** the work rollback, proving the claim committed separately. Same unit command. | Fully-Automated | AC-3 |
| **T-U7** (S7/§4a Boundary 3, C-09b) failure-path re-issue: force an exception in the work transaction; assert the row lands in `'pending'` (attempts < max) or `'failed'` (attempts >= max) — **never left at `'processing'`** — and that `last_error` contains no email-shaped substring. | Fully-Automated | AC-3 |
| **T-U8** (S7/§4a Boundary 2, C-08a, C-08 wrapper — **rewritten S14 cycle 6; assertion target SUPERSEDED by Execute-Agent Instruction E-1, cycle 8 — assert on `db.begin` / `__aexit__` / `db.execute` ordering, NEVER on `db.commit()`**) **commit call-count and ordering, happy path.** Drive one full successful sweep row against a mocked `AsyncSession` (the `-m unit` tier is mock-only per `tests/conftest.py`). Assert on the mock's recorded call sequence: (a) **exactly one** `commit()` occurs across the whole work-transaction path (the separate Boundary-1 claim commit is asserted independently by T-U6 and excluded from this count); (b) that commit occurs **strictly after** both the tombstone `pg_insert` and the `beam_identity_graph` DELETE have been issued; (c) **no** `commit()` appears between them. A mock can legitimately prove "the code never issues an early commit" — that is a code-shape property, and it is the property this gate exists for. Same unit command. | Fully-Automated | AC-3, AC-4 |
| **T-U8b** (**rewritten S14 cycle 6; assertion target SUPERSEDED by Execute-Agent Instruction E-1, cycle 8 — condition (a) `zero commits` is void; assert `__aexit__` exception info instead. Conditions (b)/(c) stand.**) **commit call-count and ordering, failure path.** Same mocked-session setup, but patch the `beam_identity_graph` DELETE to raise. Assert: (a) **zero** work-transaction `commit()` calls were recorded before the raise; (b) the recorded sequence shows the tombstone INSERT issued **before** the DELETE (ordering per Boundary 2); (c) the handler's recovery path is `rollback()` followed by the Boundary-3 fresh UPDATE, never a work-transaction commit. Together with T-U8 this proves the code cannot durably land the DELETE while the tombstone is unlanded — *by never issuing an intervening commit*. Same unit command. | Fully-Automated | AC-3, AC-4 |
| **T-U9** (S7 item 4, C-09c) queue-health signal: seed one `pending` row with `created_at` older than `graph_erasure_stale_alert_hours`; run the sweep; assert an `erasure_queue_health` record is emitted at `warning` with a correct `oldest_pending_age_hours` and containing **no** email/bidx/fingerprint value. | Fully-Automated | AC-3 (operator visibility) |
| **T-U9b** (NEW, S11 cycle 5 — C-09c) queue-health **`failed` visibility**: with the queue-count query returning `failed_count >= 1` and `pending`/`processing` both empty (mock the count query — this stays in the `-m unit` tier, which per `tests/conftest.py` is mock-only, so the assertion is on the *emitted log record*, not on persisted DB state), run the sweep pass and assert the `erasure_queue_health` record is emitted at **`warning`** (not `info`) and carries a correct `failed_count` and `oldest_failed_age_hours`, with **no** email/bidx/fingerprint value. This is the gate whose absence made a permanently-failed erasure — already reported to the caller as a `200` success — invisible to every operator, to PVL, and to EVL. Same unit command. | Fully-Automated | AC-3 (operator visibility) |
| **T-I1** seed `BeamIdentityNode` for a visitor's fingerprint → `DELETE /{site}/{visitor}/data` → run sweep → assert graph row gone after commit. `.venv/bin/python3.11 -m pytest tests/integration/test_graph_erasure_flow.py -m integration -q` (precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis`) | Hybrid | AC-1 |
| **T-I2** seed graph row with `source_site_id = site_B`; delete from `site_A`'s endpoint for a fingerprint-matching visitor; run sweep; assert identity no longer resolvable. | Hybrid | AC-2 |
| **T-I3** **existence-oracle uniformity**: call the delete endpoint twice — once for a visitor WITH a graph row, once for a visitor WITHOUT — and assert the two response bodies are shape-identical (same keys, same `status`, same HTTP code) and neither leaks a match count. | Hybrid | AC-1 (CAUTION #1) |
| **T-I4** call the delete endpoint twice in sequence + run the sweep twice; assert second call `200`, no exception, graph state unchanged from after the first. | Hybrid | AC-3 |
| **T-I5** **blast-radius pin**: seed 3 graph rows (target identity, an unrelated identity on the same site, an unrelated identity on another site); erase the target; assert exactly ONE row deleted and the other two intact. | Hybrid | AC-1, AC-2 (destructive-class mitigation) |
| **T-I6** after erasure completes, call `resolve()` for the same visitor/fingerprint under conditions that would normally write to the graph; assert no row reappears. | Hybrid | AC-4 (sequential case; race is KG-1) |
| **T-I7** `GET /privacy/graph-identity?email=...` against a seeded row returns `exists=true`, correct `row_count`, correct `contributing_site_ids`; and returns `403`/`404` for a non-admin caller. | Hybrid | AC-10 |
| **T-I8** (S8/§4b, C-14) **throttle non-regression — hard gate**: exceed `graph_erasure_max_per_minute` for a site, then call `DELETE /{site}/{visitor}/data`; assert HTTP `200` (never `429`), assert the visitor's **local rows are actually deleted** across all 7 tables, and assert the `erasure_requests` row exists with `throttle_flagged=True`. Also assert the response body is shape-identical to an unthrottled call (C-13). | Hybrid | AC-1 (+ no-regression on today's unlimited endpoint) |
| **T-I9** (S7 item 4, C-20a) operator read path: seed a stuck `pending` row **and, separately, a row with `throttle_flagged=True`**; call the admin-gated queue-health surface (or the CLI fallback); assert it reports the stuck row's age, **assert `throttle_flagged_count` equals the number of seeded throttle-flagged rows (VALIDATE cycle 4 addition — closes F9 below; previously this field was returned but never asserted)**, **assert (S11 cycle 5) a seeded `status='failed'` row is reflected in both `failed` and `oldest_failed_age_hours`** — this is the DB-truth half that T-U9b's mocked unit tier cannot prove — and returns counts only — no bidx, fingerprint, or email in the payload; and returns `403`/`404` for a non-admin caller. | Hybrid | AC-3, AC-10 |
| **T-I10** (NEW, S12 cycle 5 — §4b, C-08, C-14) **flagged-row processing parity — the previously unverified half**: seed an `erasure_requests` row with `throttle_flagged=True` and `status='pending'` alongside an otherwise identical row with `throttle_flagged=False`, plus a matching `beam_identity_graph` row for each; run the sweep; assert **both** rows reach `status='done'`, **both** graph rows are deleted, and both tombstone pairs are written — i.e. the flag altered no execution path. Also assert C-08's claim query source contains no `throttle_flagged` reference — **scoped to the claim-query function/statement ONLY, per Execute-Agent Instruction E-2 (cycle 8); the whole-file grep originally specified here is unsatisfiable by correct code, since `enqueue_erasure()` lives in the same file and MUST write that column.** Before cycle 5 **no gate anywhere asserted a flagged row's subsequent claim/processing behavior**, so §4b's locked design was unproven on its own terms. Same integration command/precondition as T-I1. | Hybrid | AC-1, AC-3 |
| **T-R1** existing regression suite still green: `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` and `.venv/bin/python3.11 -m pytest tests/ -m integration -q` — with specific attention to `tests/unit/test_agent_origin_exclusion.py` and any `test_company_resolver.py` / suppression tests. | Fully-Automated | AC-6 |
| **T-M1** migration offline validation: `alembic -c apps/api/alembic.ini upgrade <observed-head>:head --sql` (explicit range — see C-03) both directions. Live round-trip on a disposable Postgres is Docker-gated → KG-5. | Hybrid | AC-1 (schema) |
| **T-A1** presence check: `grep -l "cross-tenant identity" apps/web/public/beam/privacy.html apps/web/public/beam/terms.html` returns both files, plus the onboarding component. | Fully-Automated | AC-7, AC-8, AC-9 (presence only) |
| **T-A2** `cd apps/web && npm run test:e2e -- onboarding.spec.ts` — assert `[data-testid="cross-tenant-disclosure"]` is visible on the pixel-install step. Use `await expect(locator).toBeVisible({ timeout: 15_000 })`, never `waitForTimeout` + `isVisible` (canonical Playwright rule). | Fully-Automated | AC-9 (presence half) |
| **T-P1** human/agent content review of privacy.html + terms.html + onboarding copy against §10 C-22/C-23/C-24 requirements. **Counsel review is a hard SPEC constraint and is NOT satisfied by this probe.** | Agent-Probe | AC-7, AC-8, AC-9 (content half) |
| **T-P2** log-inspection probe: run the full flow at DEBUG and confirm no structlog record contains a plaintext email, full name, or ciphertext — only `visitor_id[:8]`, site ids, and counts. | Agent-Probe | Business Guardrail #3 / SPEC PII constraint |

> **Code-shape vs. atomicity — read this before citing T-U8/T-U8b (S14, cycle 6).** T-U8 and T-U8b
> are **code-shape gates, not proof of real Postgres atomicity.** They prove exactly one thing: the
> implementation never issues an early/intervening `commit()`. The safety argument is a chain —
> "the code never issues an early commit" **plus** "Postgres provides real ACID atomicity within one
> transaction" ⇒ *deleted-but-not-tombstoned* is unreachable — and these gates prove only the first
> link. Conflating the two is precisely the reasoning error that produced the original Boundary-2
> gap. The second link is unverified here: no gate in this plan injects a fault *between* the two
> statements against a real Postgres with a second connection observing committed state. That
> missing proof is **KG-9** (§8), and it is deliberately distinct from T-U8/T-U8b.

> **Coverage-claim correction (S2b).** This plan does **not** deliver "the erased person is never
> re-identified across other tenants" in full. It delivers: (a) hard deletion of the shared
> `beam_identity_graph` rows, and (b) a permanent block on all future graph writes for that person
> on every site. It does **not** reach `IdentifiedVisitor` rows other tenants already hold — see
> §8 **KG-6** for the concrete harm scenario. Any prose in this plan, its reports, or any
> user-facing erasure confirmation claiming unqualified cross-tenant erasure must be read against
> KG-6.

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
test("T-U6 erasure claim commits separately from destructive work", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: T-U6")
})
test("T-U7 failure path re-issues fresh status update after rollback, never wedges at processing", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: T-U7")
})
test("T-U8 exactly one work commit, issued strictly after both tombstone insert and graph delete", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: T-U8")
})
test("T-U8b delete raises: zero work commits recorded, tombstone issued before delete, rollback then fresh update", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: T-U8b")
})
test("T-U9 erasure_queue_health emits age and counts with no PII", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: T-U9")
})
test("T-U9b erasure_queue_health warns on failed_count > 0 and reports oldest_failed_age_hours", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: T-U9b")
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
| AC-1 graph erasure reaches shared graph | C-01…C-03, C-07…C-09, C-11…C-14 | T-I1, T-I3, T-I5, T-I8, T-I10, T-M1 | Covered |
| AC-2 works cross-tenant (`source_site_id` ≠ requester) | C-08 (no site filter), C-11 | T-I2, T-I5 | Covered |
| AC-3 idempotent + crash-safe | C-01 (state machine), C-08, C-08a, C-09, C-09b, C-09c | T-U5, T-U6, T-U7, T-U8, T-U8b, T-U9, T-U9b, T-I4, T-I9, T-I10 | Covered. Transaction boundaries are specified in §4a (S7) — the earlier `referral_activation.py` analogy was void (that file has no `processing` state). Operator visibility added via C-09c/C-20a, and extended by **S11 (cycle 5)** so a permanently-`failed` erasure is aged, warned on, and gate-asserted (T-U9b/T-I9) rather than counted-but-silent. **§4a Boundary 2 resolved at cycle 6 (S13–S16): the `async with db.begin():` wrapper is now binding, and T-U8/T-U8b are call-sequence gates a mock can actually prove. This row's coverage claim is no longer provisional.** Scope of that coverage is bounded and stated: T-U8/T-U8b prove code shape only; real-Postgres mid-transaction atomicity is the open **KG-9**, which keeps this criterion's crash-safety claim honest rather than overstated. |
| AC-4 no silent re-creation **into the cross-tenant graph** | C-04…C-06, C-08 (dual tombstone), C-15 | T-U2, T-I6 | **PARTIAL.** Covered for the graph-write path, sequential case (the `"erased"` row alone trips C-15's scope tuple). NOT covered: other tenants' pre-existing `IdentifiedVisitor` rows → **KG-6**. Race window → KG-1. |
| AC-5 guard at write boundary | C-15 | T-U1, T-U2 | Covered |
| AC-6 no regression of existing guard | C-05 (signature preserved) | T-U3, T-R1 | Covered |
| AC-7 privacy.html | C-22, C-25, C-26 | T-A1 (presence), T-P1 (content) | **CONDITIONAL** — counsel, KG-4 |
| AC-8 terms.html | C-23, C-25, C-26 | T-A1, T-P1 | **CONDITIONAL** — counsel, KG-4 |
| AC-9 onboarding disclosure | C-24, C-25, C-29 | T-A2 (presence), T-P1 (content) | Covered (presence); content CONDITIONAL |
| AC-10 operator lookup | C-10, C-20, C-21 | T-I7, T-I9 | Covered; endpoint-vs-script is a C-20 discovery branch |

**Deferred with reason:** SPEC Open Q2 (`CompanyGraphNode`) → KG-3. Open Q4 (historical
reconciliation) → KG-2, verified not actionable. Open Q1 (authorization model) → **partially
mitigated, NOT resolved** (S9, cycle 3). C-11/C-14 deliver own-visitor scoping + an enqueue volume marker +
audit log. Own-visitor scoping is a real (though `_fp`-bypassable) control; the volume marker and
the audit log are **forensic records only and mitigate nothing** (§4b option (b), KG-8). None of
them is structural prevention: a client-supplied `_fp` accepted at ingest with no server-side corroboration makes a
single crafted request sufficient to erase another tenant's graph row. See **KG-7** (and **KG-8**
for the missing cumulative cap). Earlier drafts read "resolved"; that was an overclaim.

---

## Phase Completion Rules

This is a single-phase plan (not a phase program), so "phase completion" means plan completion.

| Status | Bar |
|---|---|
| `CODE DONE` | All checklist items C-01…C-30 applied; code compiles; unit lane green. **Not** a completion state on its own. |
| `EVL GREEN` | Every Fully-Automated gate (T-U1…T-U5, T-U6…T-U9, T-U8b, T-U9b, T-R1, T-A1, T-A2) exits 0, AND every Hybrid gate (T-I1…T-I10, T-M1) has been run with its precondition satisfied and recorded with its exact command and outcome. |
| `✅ VERIFIED` | Requires explicit user confirmation. `EVL GREEN` **plus** both Agent-Probe gates (T-P1, T-P2) recorded with an explicit judgment, **plus** every open Known Gap (KG-1…KG-9) written as a backlog stub (C-30, ten stubs). |
| **Blocked from `✅ VERIFIED`** | AC-7 and AC-8 content correctness stay **CONDITIONAL** until qualified privacy counsel reviews the copy (hard SPEC constraint, KG-4). The plan may reach `✅ VERIFIED` for the engineering ACs while AC-7/AC-8 content remains CONDITIONAL — this split must be stated explicitly in the phase report, never elided. |

Additional hard rules:

- The plan may **not** be archived while §0's sequencing constraint is unresolved.
- No gate may be marked PASS on a Known-Gap basis. A Known-Gap keeps its criterion CONDITIONAL and
  requires a backlog stub.
- The migration is **offline-validated only** until a live round-trip runs (KG-5); do not claim
  schema verification beyond that.

---

## Test Infra Improvement Notes

- **(S15, cycle 6) Mid-transaction fault injection with a second observing connection does not exist
  in this repo.** `tests/integration/` has no pattern for killing/failing a connection between two
  statements inside one transaction while a second connection asserts committed state. Building it
  once would unblock **KG-9** here and would be reusable by any future plan asserting a real
  multi-statement atomicity property. Scoped as infra work, not a test.
- (nothing else identified yet — update during vc-test-coverage-plan / EVL)
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
   `services/identity_resolver.py` (fns `resolve()` — `do_not_resolve` guard snapshot `:548`,
   `_is_email_opted_out` call snapshot `:557` — and `_upsert_beam_identity`, snapshot `:1264-1317`;
   anchors per §0), `routers/visitors.py` fn `delete_visitor_data` (snapshot `:405-446`), `routers/privacy.py`, `jobs/scheduler.py`, `config.py`.
5. **Next step for a fresh agent:** **PVL supplement cycle 6 (S13–S16) applied 07-08-26 — the
   §4a Boundary 2 INNOVATE outcome is now IN the plan and the ⏸ marker is cleared. Read §4a's
   "INNOVATE OUTCOME APPLIED" block, C-08's binding `async with db.begin():` requirement + its
   SQLAlchemy scratch-confirmation note, the rewritten T-U8/T-U8b call-sequence gates, the
   code-shape-vs-atomicity note above the AC map, and new KG-9 before touching the sweep.**
   Historical: PVL supplement cycle 3 applied (S7–S10, 07-08-26) on top of
   cycle 1 (S1–S6, re-confirmed correct at cycle 2). **Cycle 4 re-validate (this pass) found 0 FAIL
   and 2 new fixable-defect CONCERNs (F8, F9 — both cheap test-table additions, already folded into
   this plan's Verification Evidence as T-U8b and the T-I9 strengthening) and confirmed S7–S10 landed
   correctly with no regression.** **Cycle-3 additions to read before EXECUTE: §4a (transaction
   boundary contract — binding, three boundaries, replaces the void `referral_activation.py`
   state-machine analogy — plus the cycle-4 precision note on what the "no intervening commit" rule
   actually protects against), §4b (enqueue throttle is flag-but-store and must NEVER `429` the
   request or block the local DELETE), and KG-7/KG-8 (authorization is *partially mitigated*, not
   resolved).** **Do NOT enter EXECUTE** until the restated §0 bar is met — explicit user sign-off
   (a literal `Gate: PASS` on `identity-vocab-reconcile_07-08-26` will never occur; it terminated
   EXECUTED / `Gate: CONDITIONAL, accepted`). Every line number in this plan is a dated snapshot —
   re-derive from the §0 content anchors before editing anything. On resume, re-read §3 (Corrections) first: `email_bidx` is
   already live, the hash chain is already consistent, `_cascade_suppress` is **never** called by
   the sweep (S1), and C-11's ordering (enqueue **before** the DELETE loop) is the single most
   likely implementation mistake. Read §8 **KG-6** before writing any report or user-facing message
   describing this plan's cross-tenant coverage.

---

## Supplement Cycle 5 Record (S11, S12) — plan-agent, 07-08-26

Scope fence honored: **only** S11 and S12 were touched. §4a's Boundary-2 enforcement mechanism,
T-U6…T-U9, T-U8b, the platform queue architecture, C-13's existence-oracle contract, C-11's
ordering, the blind-index design, the default-ON flag, AC-7/AC-8's permanent CONDITIONAL,
KG-6/KG-7's deferral, and S1–S10 are all unchanged.

| Item | Sections edited | Outcome |
|---|---|---|
| **S11** — `failed` invisible on the queue-health surface | §4 step 7, C-09c, C-20a, T-U9b (new), T-I9 (extended), AC-3/AC-1 matrix rows, Phase Completion Rules | **Premise partly corrected, then fixed.** `failed_count` was *already* in C-09c and `failed` *already* in C-20a since cycle 3 — the SUPPLEMENT REQUEST's "never reads `failed`" is inaccurate as stated and is recorded as such rather than applied blindly. The real defect: `failed` was counted but **never aged, never alerted, never gate-asserted** — the `warning` trigger keyed solely on `oldest_pending_age_hours`, whose `WHERE status IN ('pending','processing')` clause structurally excludes `failed`. Added `oldest_failed_age_hours`, a `failed_count > 0` warning trigger, T-U9b (unit, log-record assertion — deliberately not a unit-tier DB assertion, per cycle-4's conftest finding), a T-I9 extension for the DB-truth half, and a four-step operator response (read sanitized `last_error` → fix cause → re-enqueue by resetting to `pending`/`attempts=0`, safe because erasure is idempotent per T-I4 → escalate as a compliance event if unfixable). |
| **S12** — `throttle_flagged` written and displayed but never acted on | §4b (heading + decision block + locked behavior + residual), C-14, C-01, C-08, KG-8, T-I10 (new), AC-1/AC-3 matrix rows, Phase Completion Rules | **Chose option (b), honest forensics.** Behavior is unchanged (flagged rows still execute); the *description* is corrected so the plan no longer implies a control that does not exist. Option (a) real exclusion was considered and rejected in-plan for three stated reasons: on a solo-founder GDPR clock "held pending operator release" ≈ "dropped" (the exact liability §4b exists to avoid, and it would collide with S11's newly-closed aging blind spot); it cannot close KG-7, whose attack is two requests far inside 60/min; and it would introduce a new irreversible-inaction failure mode to defend against an attack it cannot detect. Added T-I10 asserting a flagged row is claimed, processed, and deleted identically to an unflagged one — cycle 4 found **no gate anywhere** asserted this, leaving the security-relevant half unverified on the plan's own terms. |

**Live re-derive (this cycle, 07-08-26):** alembic head `c9f4a7b31e85` — **UNCHANGED**, single head.
`git rev-parse --short devjulley` → `5293cbc` — **UNCHANGED**. Neither moved.

**Open for re-validate (as written at cycle 5):** (1) S12's option-(b) choice is a design call made
inside supplement latitude and should be confirmed or overturned by validate; (2) §4a Boundary 2's
INNOVATE outcome must be reconciled into this plan before EXECUTE. **Item (2) is RESOLVED at
supplement cycle 6 (S13–S17) — see the Supplement Cycle 6 Record below; AC-3's coverage claim is no
longer provisional.** Item (1) remains open.


## Supplement Cycle 6 Record (S13–S17) — plan-agent, 07-08-26

Applies the completed parallel INNOVATE decision on §4a Boundary 2. Scope fence honored: **only**
S13–S17 were touched. §4a Boundaries 1 and 3 and their gates (T-U6/T-U7), §4b and C-14/C-01/C-08's
cycle-5 volume-marker semantics, the platform queue architecture, C-13's existence-oracle contract,
C-11's ordering, the blind-index design, the user-approved default-ON flag, AC-7/AC-8's permanent
CONDITIONAL, KG-6/KG-7/KG-8's deferral, and S1–S12 are all unchanged.

| Item | Sections edited | Outcome |
|---|---|---|
| **S13** — wrapper status | §4a precision note, C-08, C-08a | `async with db.begin():` reclassified from an optional EXECUTE-agent defense-in-depth recommendation to a **binding** checklist requirement. Wording/status change to content the plan already carried; no new architecture. The superseded phrasing is struck in the historical cycle-4 contract with an explicit `[SUPERSEDED …]` marker rather than silently deleted. |
| **S14** — unit gates made non-vacuous | T-U8, T-U8b (Verification Evidence), their TDD stubs, new code-shape note | Both rewritten to assert **call sequence and call count on the mocked session**: exactly one work-transaction `commit()`, strictly after both the tombstone INSERT and the graph DELETE, never between; failure path asserts zero work commits before the raise plus rollback-then-fresh-UPDATE. A mock genuinely can prove "the code never issues an early commit". Added one explicit statement beside the table that these are **code-shape gates, not proof of real Postgres atomicity** — the chain is "code never commits early" + "Postgres provides ACID" — because conflating the two is exactly what produced the original gap. |
| **S15** — missing proof named | new §8 **KG-9**, C-30 (nine → ten stubs), Phase Completion Rules (KG-1…KG-9), Test Infra Improvement Notes, backlog stub written | Live two-connection fault-injection gate recorded as its own Known Gap, **explicitly distinct from T-U8/T-U8b** so nobody later reads the unit gates as having proven it. Docker-gated, same posture as every other Hybrid gate; needs new fault-injection infra this repo has never had, recorded under Test Infra Improvement Notes. Stub: `process/features/visitors-identity/backlog/graph-erasure-boundary2-live-fault-injection_NOTE_07-08-26.md`. |
| **S16** — library residual | C-08 sub-bullet | SQLAlchemy `2.0.35` confirmed pinned at `requirements.txt:7`. `AsyncSession.begin()` immediately after a commit with no intervening statements is recorded as a **cheap ~5-line EXECUTE-time scratch confirmation**, not a blocking feasibility probe (high confidence, documented 2.0 behavior, unverified in this repo); named fallback if it raises is a plain `await db.begin()` guard, not a design change. |
| **S17** — marker cleared + deferred note | §4a marker block, AC-3 row, status line | The cycle-5 pending-INNOVATE marker is removed; AC-3's coverage claim un-provisioned with its scope stated (code shape covered, real-Postgres atomicity = KG-9). One low-cost line added recording the **deferred self-healing reconciliation** idea (periodic `done`-vs-`suppression_list` comparison, viable because `erasure_requests` retains match keys after `done`) — noted only, not designed, on no checklist. |

**Rejected by INNOVATE, recorded so they are not reintroduced:** `begin_nested()`/savepoints (wrong
primitive), ORM mapper events (both statements are raw SQL by design — events never fire), DB trigger
(the DELETE's `WHERE` is an OR across `email_bidx`/`fingerprint`/`fingerprint_v3`, so some deleted
rows have no `email_bidx` to join on).

**Live re-derive (this cycle, 07-08-26):** alembic head `c9f4a7b31e85` — **UNCHANGED**, single head.
`git rev-parse --short devjulley` → `5293cbc` — **UNCHANGED**. Neither moved.

**Open for re-validate:** S12's option-(b) choice (carried from cycle 5, still unconfirmed) and this
cycle's S14 claim that call-sequence assertions on a mock are a legitimate proof of the code-shape
half. KG-9 is a disclosed gap, not a defect to fix in-plan.

---

## Validate Contract

Status: CONDITIONAL
Date: 07-08-26
date: 2026-08-07
generated-by: outer-pvl
supersedes: 07-08-26 (outer-pvl) — cycle 6 supplement (S13-S17) applied between contracts

**PVL cycle:** 7 (re-validation of supplement cycle 6's S13–S17 items, per `results.tsv` rows 0-6).

**Fan-out disclosure:** this vc-validate-agent instance has no Agent tool grant, so the designed
Layer-1 (4 dimension agents) / Layer-2 (per-section feasibility agents) parallel fan-out from
`vc-validate-findings` could not be spawned as separate subagents. All Layer-1 and Layer-2 roles
below were run as a single sequential pass by this agent, substituted with direct source
verification (git grep, live `alembic heads`, the plan-artifact validator script, and — new this
cycle — a live empirical `AsyncMock`/SQLAlchemy 2.0.35 experiment against the two items the cycle-6
plan-agent flagged for judgment) rather than parallel dimension/section agents. One external
adversarial verifier was reported running in parallel this cycle on the same two design calls
(S14's mock-assertion claim and S12's honest-forensics claim); this agent had no channel to that
verifier's output and could not cross-check it directly — agreement/disagreement should be
reconciled by whoever consumes both reports.

Parallel strategy: sequential (single-agent synthesis; no Agent tool available)
Rationale: fan-out infrastructure unavailable in this session; substituted with a live empirical
test of S14's mock-assertion claim (the one genuinely testable claim in this cycle — a Python
runtime experiment, not prose reasoning) plus targeted re-verification of every S13-S17 claim and a
regression re-check of S1-S12.

### Supplement cycle 6 (S13-S17) verification — each checked independently against the plan body

| Item | Claim to verify | Landed in plan body? | Correct? |
|---|---|---|---|
| S13 | `async with db.begin():` reclassified from EXECUTE-agent recommendation to BINDING checklist requirement in C-08/C-08a; superseded cycle-4 wording struck with an explicit `[SUPERSEDED …]` marker, not silently deleted | **YES** — §4a precision note carries the full `[SUPERSEDED at supplement cycle 6, S13: …]` block verbatim; C-08 states "**BINDING (S13, supplement cycle 6 — reclassified from guidance)**"; C-08a states "The `async with db.begin():` wrapper in C-08 is BINDING for this pair (S13, cycle 6)". `git grep -n "not a new hard requirement"` on the live plan returns nothing — the pre-cycle-6 phrasing does not survive anywhere. | **YES** |
| S14 | T-U8/T-U8b rewritten as call-sequence/call-count assertions on a mocked session; framed as legitimately provable because "a mock can prove the code never issues an early commit" | **YES, text landed** — Verification Evidence T-U8/T-U8b, their TDD stubs, the code-shape-vs-atomicity note, all present as described | **NO — see Design-call finding F10 below.** The claim that *this specific* assertion (`db.commit()` call count) is what a mock can prove is empirically false once C-08's binding wrapper is in the picture. |
| S15 | New §8 KG-9, C-30 nine→ten stubs, Phase Completion Rules KG-1…KG-9, Test Infra Improvement Notes entry, backlog stub written | **YES** — §8 KG-9 row present with full scenario; C-30 states "That is **ten** stubs"; Phase Completion Rules `✅ VERIFIED` row says "every open Known Gap (KG-1…KG-9)"; Test Infra Improvement Notes has the fault-injection-infra entry; **backlog stub confirmed on disk**: `process/features/visitors-identity/backlog/graph-erasure-boundary2-live-fault-injection_NOTE_07-08-26.md` (3657 bytes, correct frontmatter, content matches the plan's KG-9 description). Note: the stub's own "Interim accepted argument" section repeats S14's now-refuted claim about T-U8/T-U8b — see F10, this stub will need a one-line correction alongside the plan-text fix. | **YES, structurally landed — content needs the F10 correction propagated into it at the next supplement.** |
| S16 | `sqlalchemy[asyncio]==2.0.35` pinned at `requirements.txt:7`; residual recorded as ~5-line EXECUTE-time scratch confirmation, not a blocking probe | **YES** — `requirements.txt:7` reads exactly `sqlalchemy[asyncio]==2.0.35` (re-confirmed live this cycle); C-08 sub-bullet text matches | **YES.** (Note, not a defect: this cycle's own live experiment against that exact pinned version independently confirms `AsyncSession.begin()`-after-commit poses no autobegin-conflict concern — the empirical test in F10 opened/used `db.begin()` cleanly against the installed 2.0.35 package. S16's "high confidence" framing is validated in passing.) |
| S17 | Cycle-5 `⏸ PENDING INNOVATE` marker cleared; AC-3 coverage claim un-provisioned; deferred self-healing-reconciliation idea noted only, no design, no checklist entry | **YES** — `git grep -n "PENDING INNOVATE"` on the live plan returns nothing; AC-3's AC Coverage Map row states "**This row's coverage claim is no longer provisional**"; §4a carries the one-paragraph deferred-reconciliation note with no checklist item attached | **Text landed as claimed, but see F10 — "no longer provisional" is itself premature: it is accurate for B1/B3 (T-U6/T-U7, unaffected by F10) but overstated for B2, whose proving gates (T-U8/T-U8b) do not yet prove what they claim.** |

### Design-call findings (the two items the cycle-6 plan-agent flagged for validate judgment)

**F10 (CONCERN, fixable defect) — T-U8/T-U8b's proving mechanism is empirically wrong as specified;
same self-confident-reasoning failure class as F5/F6/F7/F8/F9, tested rather than accepted this
time.**

The task framing asked precisely the right question: can an `AsyncMock`-based test distinguish
`async with db.begin():` wrapping both statements from two bare statements plus a trailing
`commit()`? **Tested live against this repo's pinned `sqlalchemy[asyncio]==2.0.35`, not reasoned
from memory:**

1. Read `AsyncSession.begin()` source directly
   (`.venv/lib/python3.11/site-packages/sqlalchemy/ext/asyncio/session.py`): it is a **plain
   synchronous method** (`def begin(self) -> AsyncSessionTransaction`, not `async def`) that
   returns `AsyncSessionTransaction(self)`.
2. Read `AsyncSessionTransaction`: `commit()` calls `await greenlet_spawn(self._sync_transaction().commit)`
   — the **underlying sync `SessionTransaction`'s own commit**, not `AsyncSession.commit()`.
   `__aexit__` calls `await greenlet_spawn(self._sync_transaction().__exit__, type_, value, traceback)`
   — again routing through the sync transaction object, never through `AsyncSession.commit()`.
3. Ran a live experiment:
   ```python
   db = AsyncMock(spec=AsyncSession)
   async with db.begin():
       await db.execute('stmt1')
       await db.execute('stmt2')
   # db.commit.call_count == 0
   # db.begin.return_value.__aexit__.call_count == 1
   ```
   Confirmed: `db.begin` auto-mocks as a plain `MagicMock` (not `AsyncMock`) because `begin` is not
   a coroutine function on the real class; `async with db.begin():` succeeds because `MagicMock`
   auto-configures `__aenter__`/`__aexit__` as async-capable in this Python version — **and
   `db.commit.call_count` is `0`** for exactly the code shape C-08 mandates.

**Consequence for T-U8 (happy path):** its assertion (a) "**exactly one** `commit()` occurs across
the whole work-transaction path" — read the natural way (`db.commit.assert_called_once()`, the only
public "commit" surface on the session mock a test author would reach for) — **fails against a
correct, C-08-binding-compliant implementation** (0 calls, not 1) and **only passes against the
broken bare-statements-plus-trailing-`await db.commit()` shape** T-U8 exists to reject. This is the
inverse of the gate's purpose.

**Consequence for T-U8b (failure path):** condition (a) "**zero** work-transaction `commit()` calls
recorded before the raise" is **vacuously true under both shapes** once the DELETE is patched to
raise — neither the correct wrapped code nor the broken bare-statements code reaches its `commit()`
line when the statement immediately before it raises. This sub-assertion catches nothing regardless
of implementation. T-U8b's conditions (b) (INSERT issued before DELETE, via `db.execute.call_args_list`
ordering) and (c) (rollback-then-fresh-update recovery path, via `db.rollback` and the Boundary-3
UPDATE) remain sound — `db.execute` and `db.rollback` ARE coroutine methods on the real class and
mock/assert correctly regardless of the wrapper. Only the commit-count sub-assertions are broken.

**This is not a defect in C-08's design** (the binding `async with db.begin():` wrapper is the
correct, and only, structural way to make "no intervening commit" obvious at the call site — S13's
decision stands). **It is a defect in what T-U8/T-U8b were told to assert.** Recommended fix
(mechanical, no new test infra, same file/command):

- Drop the `db.commit()`-based assertions from T-U8/T-U8b entirely for the Boundary-2 work-transaction
  path (Boundary 1/3's `db.commit()` assertions in T-U6/T-U7 are unaffected — those boundaries use
  plain `await db.commit()`, not the wrapper, and mock correctly today).
- T-U8 (happy path): assert `db.begin.call_count == 1`; assert
  `db.begin.return_value.__aexit__.call_count == 1` with no exception info passed (proves the block
  exited cleanly, i.e. committed via the wrapper); assert `db.commit.call_count == 0` for this code
  path (proves no redundant/early manual commit was issued alongside the wrapper); assert ordering
  via `db.execute.call_args_list` (tombstone INSERT precedes the DELETE).
- T-U8b (failure path): same setup, patch the DELETE call to raise; assert
  `db.begin.return_value.__aexit__` was invoked **with** exception info (proves the wrapper's own
  exception-path exit ran); assert `db.execute.call_args_list` still shows INSERT-before-DELETE;
  assert the code's outer failure handler (C-09/C-09b) then calls `db.rollback()` followed by a
  fresh `db.execute` (the Boundary-3 UPDATE) and `db.commit()` exactly once (Boundary 3's own commit,
  already covered by T-U7 — restate here only if it must be re-asserted in the same test).
- Update the KG-9 backlog stub's "Interim accepted argument" paragraph in the same supplement pass —
  it currently repeats S14's now-superseded framing ("a mock genuinely can prove 'the code never
  issues an early commit'") without qualifying which mock target that applies to.

**Category: fixable defect, mechanical, same file/command, no design change, no new test infra.**
Requires one more supplement cycle (7) before AC-3/AC-4's "no longer provisional" claim (S17) is
actually true for Boundary 2.

**F11 (CONCERN, minor, fixable defect) — T-I10's source-grep assertion is scoped wider than the
constraint it is meant to enforce.**

T-I10 asserts "C-08's claim query source contains no `throttle_flagged` reference (`git grep -n
throttle_flagged apps/api/services/graph_erasure.py` returns nothing)". The binding constraint
(C-01, C-08, C-14) is narrower: `throttle_flagged` "must never appear in a WHERE clause on any
execution path" — i.e. it must never *filter*, not that the string must never appear in the file.
C-20a's `throttle_flagged_count` queue-health counter is a legitimate, required, non-filtering
*read* of that column, and the natural place to implement its counting query (service layer, same
file as the sweep and the claim query, per this codebase's own layering convention) is
`graph_erasure.py` itself — the Touchpoints table does not rule this out (it only names three
functions for that file, but Phase F's C-20a work is not explicitly assigned a home). If EXECUTE
places the health-counter query there, T-I10's whole-file grep would **false-fail against a
correct implementation**, or force an artificially awkward file split to dodge the grep.
**Fix:** narrow the grep to the specific claim-query statement or function (e.g. isolate the
`run_graph_erasure_sweep` claim `UPDATE ... WHERE id=:id AND status='pending'` line/block before
grepping, or assert the exact claim-query string literal directly rather than scanning the whole
file). **Category: fixable defect, minor, one-line test-spec correction.**

### S12 re-confirmation (independent, this cycle)

Re-checked S12's option-(b) "honest forensics" choice directly against the live plan text and found
it internally consistent, with no contradicting language anywhere:

- C-01: `throttle_flagged` "must never appear in a WHERE clause on any execution path" — present, unedited.
- C-08: claim query "MUST NOT gain a `throttle_flagged` filter" — present, unedited.
- C-14: repeats the same naming discipline ("not a throttle and not an abuse control... records...
  and prevents nothing") — present, unedited.
- KG-8: accurately states what the mechanism gives up — "both a patient attacker... and a fast one...
  proceed unimpeded" — no overclaim found.
- T-I10 (aside from the F11 grep-scope issue above) correctly specifies the behavioral half: seed a
  flagged row and an unflagged row, assert both reach `done` and both graph rows are deleted — this
  is the right scenario to prove "the flag altered no execution path," which cycle 4 found **no gate
  anywhere** previously asserted.

No FAIL found on S12. F11 is the only defect surfaced, and it is in the gate's *auxiliary*
source-grep assertion, not in the behavioral assertion or the design itself.

### Regression check — S1-S12 content anchors and claims, re-verified this cycle

| Item | Prior verdict | This cycle | Evidence |
|---|---|---|---|
| S1-S6 | Correct (cycles 1-2) | **Unchanged, not re-traced line-by-line this cycle (no plan-text edit touched them since cycle 3)** | — |
| S3 content-anchor discipline | Correct, byte-exact (every prior cycle) | **Re-confirmed byte-exact this cycle** | `git grep -n 'async def delete_visitor_data'` → `visitors.py:406` (decorator `:405`); `_upsert_beam_identity` def → `:1264`; stale bidx comment → `beam_identity.py:50`; `do_not_resolve` → `:548`. All match. |
| S4 7-table DELETE list, `job_change_events` | Correct | **Re-read live this cycle** | `sed -n '400,450p' apps/api/routers/visitors.py` — all 7 tables present in the literal tuple, with the `job_change_events` inline comment verbatim as the plan describes. |
| S7-S10 | Confirmed correct at cycle 4 | **Unchanged, no plan-text edit touched them since cycle 4** | — |
| S11, S12 | Applied at cycle 5 | **S12 independently re-confirmed above; S11 unchanged, no plan-text edit touched it since cycle 5** | — |
| Live alembic head | `c9f4a7b31e85`, single head (every cycle since 1) | **Re-derived live this cycle: `c9f4a7b31e85 (head)` — UNCHANGED** | `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` |
| `devjulley` tip | `5293cbc` (every cycle since 1) | **Re-derived live this cycle: `5293cbc` — UNCHANGED** | `git rev-parse --short devjulley` |
| Plan validator | 0 fail / 0 warn (every cycle) | **0 fail / 0 warn, 1435 lines** | `node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs` |
| `sqlalchemy[asyncio]==2.0.35` pin | Claimed at S16 | **Re-confirmed live this cycle** | `requirements.txt:7` |

No regression found. No line number, content anchor, or prior supplement item was found altered
outside the scope S13-S17 declared.

### Gate executability check

T-U6, T-U7, T-U9, T-U9b, T-I8, T-I9, T-I10, T-A1, T-A2, T-R1, T-M1 all remain genuinely executable as
written — each names a concrete patch point and a concrete assertion, and none of this cycle's
findings touch them. **T-U8/T-U8b are executable as commands (the same `.venv/bin/python3.11 -m
pytest tests/unit/test_graph_erasure.py -m unit -q` invocation runs fine) but are NOT executable as
*proof* of the property they claim** — the assertions inside them, as specified, do not exercise
what §4a needs proven. This is a sharper failure mode than "not yet executable" (cycle 4's T-U8
asymmetry, or the original conftest-tier mismatch this plan avoided by design) — it is "executable,
green-or-red on the wrong signal."

### Layer 1 dimensions

| Layer 1 dimensions | Status | Notes |
|---|---|---|
| Infra fit | PASS | Unchanged; alembic head + admin-gate precedent re-confirmed live this cycle. |
| Test coverage | CONCERN | F10 (T-U8/T-U8b proving-mechanism defect, moderate) and F11 (T-I10 grep scope, minor) found this cycle. No vacuous-green violation in the "zero gate assigned" sense — every AC still has a *named* Fully-Automated/Hybrid gate — but T-U8/T-U8b's specified assertion does not currently prove what AC-3/AC-4 need it to prove for Boundary 2. |
| Breaking changes | PASS | Unchanged — C1 additive, C2 admin-gated, `is_email_suppressed` signature preserved. |
| Security surface | PASS | Unchanged from cycle 4/6; S12 re-confirmed consistent this cycle (see above); no new security finding. |

### Layer 2 sections

| Layer 2 sections | Status | Notes |
|---|---|---|
| §0 — Hard Sequencing Constraint | PASS | Unchanged; `identity-vocab-reconcile` row 9 status unchanged, `devjulley` unmoved. |
| Phase A — model + migration | PASS | Unchanged; live `alembic heads` re-confirms `c9f4a7b31e85`. |
| Phase B — suppression tombstone | PASS | Unchanged. |
| §4a / Phase C — sweep service | CONCERN | F10 — Boundary 2's proving gates (T-U8/T-U8b) need their assertion target rewritten; Boundaries 1/3 (T-U6/T-U7) unaffected and sound. |
| §4b / Phase D — producer / throttle | CONCERN → largely resolved this cycle | S12 re-confirmed sound; F11 is a minor test-spec scoping fix, not a design or behavior issue. |
| Phase E — write-boundary guard | PASS | Unchanged, byte-exact re-verified this cycle. |
| Phase F — wiring + operator surface | PASS | Unchanged; C-20a's home for the health-counter query is the source of F11, not a defect in the surface itself. |
| Phase G — disclosure | PASS (structurally CONDITIONAL by design) | Unchanged, KG-4 permanent. |
| Phase H — tests + backlog | PASS | Unchanged; KG-9 backlog stub confirmed present on disk this cycle; its "Interim accepted argument" paragraph needs the F10 correction propagated at the next supplement. |

**Totals: 0 FAILs / 2 CONCERNs (F10 test-coverage/proving-mechanism defect, F11 test-coverage minor
scoping defect) / 7 PASSes.**

Net-gate vacuous-green check: every developed behavior still has a *named* Fully-Automated or
Hybrid gate assigned — no behavior rests on Known-Gap alone as its only coverage. F10 does not
remove gate coverage; it identifies that one named gate's assertion, as currently specified, does
not prove the property it is assigned to prove. This is recorded as a CONCERN (fixable, mechanical),
not reclassified as a coverage gap, because the fix does not remove any test — it corrects what the
existing test asserts.

**→ Net Gate: CONDITIONAL**

0 FAILs. F10 and F11 require a plan-text-only supplement (rewrite T-U8/T-U8b's assertions per the
recommended fix above; narrow T-I10's grep scope; propagate the correction into the KG-9 backlog
stub). Neither requires new test infrastructure, a design change, or an INNOVATE pass — S13's
binding-wrapper decision and S12's honest-forensics decision both stand. **This plan's literal
`Gate: PASS` stays structurally unreachable** (AC-7/AC-8, KG-4, counsel-gated) — unchanged from
every prior cycle and consistent with `identity-vocab-reconcile_07-08-26`'s own terminal state.

**Fixable-defect vs documentable-gap split (for the user's next decision):**

| Item | Category | Status |
|---|---|---|
| F10 (T-U8/T-U8b assertion target empirically wrong for the binding C-08 wrapper) | Fixable defect | **New this cycle** — requires supplement cycle 7 (plan-text rewrite of two Verification Evidence rows + their TDD stubs + a one-line correction to the KG-9 backlog stub) |
| F11 (T-I10 grep scoped to whole file, not the claim query) | Fixable defect, minor | **New this cycle** — one-line narrowing, same supplement pass |
| AC-7/AC-8 content correctness (KG-4) | Documentable gap, permanent by design | Requires privacy counsel review — not fixable by any supplement cycle |
| KG-6 (other tenants' pre-existing `IdentifiedVisitor` rows) | Documentable gap, scoped to Phase 2 | Requires a follow-up plan/product decision — not in scope here |
| KG-7 (authorization spoofing, partially mitigated) | Documentable gap, product/security judgment | Requires an authorization-model decision — not in scope here |
| KG-8 (no cumulative erasure cap) | Documentable gap, product/security judgment | Requires an abuse-threshold decision — not in scope here |
| KG-9 (no live two-connection fault-injection proof) | Documentable gap, Docker-gated | Unchanged from cycle 6; the interim argument's supporting text needs the F10 correction, but the gap itself is unaffected |
| KG-1, KG-2, KG-3, KG-5 | Documentable gaps, previously accepted | Unchanged |

### Test gates (5-column table) — see Verification Evidence section above; T-U8/T-U8b flagged by F10

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-3 | claim commits separately from destructive work | Fully-Automated | T-U6 | A |
| AC-3 | failure path re-issues fresh status update, never wedges at `processing` | Fully-Automated | T-U7 | A |
| AC-3/AC-4 | Boundary-2 happy path: work transaction commits exactly once, after both statements | Fully-Automated | T-U8 | **A — BLOCKED on F10 supplement: assertion target (`db.commit()` call count) does not hold for the binding C-08 implementation; must be rewritten to assert on `db.begin`/`db.begin().__aexit__`/`db.execute` ordering before this row can be trusted** |
| AC-3/AC-4 | Boundary-2 failure path: no durable half-done state | Fully-Automated | T-U8b | **A — BLOCKED on F10 supplement: condition (a) is vacuous as specified; conditions (b)/(c) are sound** |
| AC-3 | queue-health signal emits age/counts with no PII | Fully-Automated | T-U9 | A |
| AC-1 (+throttle non-regression) | throttled enqueue still deletes all 7 local tables, never `429`s | Hybrid | T-I8 | A |
| AC-3/AC-10 | queue-health read path reports stuck-row age, `throttle_flagged_count`, and `failed`/`oldest_failed_age_hours` correctly | Hybrid | T-I9 | A |
| AC-1/AC-3 | flagged row claimed and processed identically to unflagged | Hybrid | T-I10 | **A — F11 supplement recommended: narrow the source-grep assertion scope before this row is fully trustworthy; the behavioral half of the gate is sound as specified** |

`gap-resolution` legend: A = proven now once code exists (gate is specified and executable; not yet
run — PLAN-phase, no code written). Rows flagged above are "A, conditional on the F10/F11 supplement
landing" rather than unconditional A.

C-4 reconciliation: `strategy:` column carries only Fully-Automated / Hybrid / Agent-Probe. No
Known-Gap value appears in this table — all listed behaviors have a proving strategy, not a residual.

Dimension findings:
- Infra fit: PASS — unchanged, re-confirmed live (alembic head, git tip, plan validator).
- Test coverage: CONCERN — F10 (moderate, T-U8/T-U8b assertion target) and F11 (minor, T-I10 grep
  scope) found this cycle via live empirical testing, not prose reasoning; both are mechanical,
  plan-text-only fixes with no new infra and no design change.
- Breaking changes: PASS — unchanged.
- Security surface: PASS — S12 re-confirmed consistent; no new security finding this cycle.

Open gaps:
- graph-erasure-authorization-spoofing-gap_NOTE_07-08-26.md (KG-7): known-gap: documented as NEW
  PLAN REQUIRED — unchanged from cycle 3/5/6. Not yet written to disk (C-30 EXECUTE checklist item).
- graph-erasure-cumulative-cap_NOTE_07-08-26.md (KG-8): known-gap: documented as NEW PLAN REQUIRED —
  unchanged. Not yet written to disk (C-30 EXECUTE checklist item).
- graph-erasure-race-window_NOTE_07-08-26.md (KG-1): known-gap: documented as NEW PLAN REQUIRED —
  unchanged. Not yet written to disk.
- graph-erasure-historical-reconciliation_NOTE_07-08-26.md (KG-2): known-gap: documented as NEW PLAN
  REQUIRED — unchanged, verified not actionable. Not yet written to disk.
- company-graph-erasure-legal-read_NOTE_07-08-26.md (KG-3): known-gap: documented as NEW PLAN
  REQUIRED — unchanged. Not yet written to disk.
- privacy-copy-counsel-review_NOTE_07-08-26.md (KG-4): known-gap: documented as NEW PLAN REQUIRED —
  unchanged, permanent (requires counsel). Not yet written to disk.
- (existing pending-migration note, KG-5): unchanged — live round-trip Docker-gated.
- cross-tenant-identified-visitor-erasure-gap_NOTE_07-08-26.md (KG-6): unchanged, correctly scoped
  forward to a Phase 2 plan.
- **graph-erasure-boundary2-live-fault-injection_NOTE_07-08-26.md (KG-9): CONFIRMED ON DISK this
  cycle** (`ls process/features/visitors-identity/backlog/` — 3657 bytes, correct frontmatter,
  content matches §8's description). **Its "Interim accepted argument" paragraph repeats S14's
  now-superseded claim and needs a one-line correction at the next supplement (see F10).**
- visitor-emails-erasure-gap_NOTE_07-08-26.md (S4 observation): unchanged, out-of-scope observation,
  backlog pointer only.
- Note: nine of the ten C-30 backlog stub files (all except KG-9's) still do not exist on disk —
  writing them remains an EXECUTE checklist item (C-30), not a PLAN/VALIDATE artifact. Confirmed
  this cycle via `ls process/features/visitors-identity/backlog/`.

What this coverage does NOT prove:
- No code exists yet (PLAN phase) — none of T-U1…T-U9/T-U8b/T-I1…T-I10/T-M1 have actually been run.
  This VALIDATE pass proves the plan's *claims about current source* are accurate as of 07-08-26
  and that most specified gates are well-formed and executable once code exists. It does NOT prove
  the new code will behave correctly — that is EVL's job after EXECUTE.
- This cycle's F10 finding IS a live empirical result (a real `AsyncMock`/`sqlalchemy==2.0.35`
  Python experiment was run, not prose reasoning about mock behavior) — but it is a test of the
  **mocking library's interaction with the real SQLAlchemy async API**, not a test of this plan's
  actual (not-yet-written) implementation code. It proves the *test as specified* cannot prove what
  it claims; it does not by itself prove anything about EXECUTE's eventual implementation.
- No live Postgres transaction was opened, committed, or rolled back this cycle (Docker unavailable)
  — KG-9's gap is unaffected and unchanged by this cycle's findings.
- The external adversarial verifier reported running in parallel this cycle was not observable from
  this agent's context — its findings on the same two design calls have not been cross-checked
  against this contract. Whoever consumes both should reconcile explicitly rather than assume
  agreement; if the verifier reaches a different conclusion on S14, prefer whichever conclusion is
  backed by a reproducible experiment (per this cycle's own instruction: "test it against how
  `AsyncMock` and `async with` actually interact").
- Live `alembic heads` (`c9f4a7b31e85`) and `devjulley`@`5293cbc` are current as of this session's
  run only; no live-DB migration apply or round-trip was performed (Docker unavailable — KG-5,
  unchanged environmental gap, not a plan defect).

Gate: CONDITIONAL
Accepted by: **USER — accepted this session (PVL cycle 8, 07-08-26).** The orchestrator presented
the cycle-7 findings and a three-option menu — (a) accept the CONDITIONAL gate and proceed to EXECUTE
with the findings carried as execute-agent instructions, (b) run another supplement + validate cycle,
(c) stop and switch to other work. The user chose **(a)**, replying with the single character `a`.
The acceptance is therefore made **on the basis of the orchestrator's reported findings, not a
personal review of the plan or of the code by the user.**

The acceptance covers the remaining CONDITIONAL items: **(a)** AC-7/AC-8's content half, permanently
CONDITIONAL by design pending privacy counsel (KG-4); and **(b)** the open Known Gaps **KG-1 … KG-9**
as documented — out-of-plan / out-of-environment residuals, including KG-9's Docker-gated live
fault-injection gap. §0's bar is likewise satisfied by this explicit sign-off in place of the
structurally unreachable literal `Gate: PASS` on `identity-vocab-reconcile_07-08-26`.

Cycle-7's three findings (F10, F11, and the incomplete S12 rebrand) are **not** accepted as
residuals — they are **resolved** this cycle: the four rebrand contradictions were corrected in the
plan body, and the two test-spec defects are carried as binding **Execute-Agent Instructions E-1,
E-2, E-3** (see that section above).

**PVL loop closed at cycle 8** (`loop_status: HALTED_ACCEPTED`). Literal `Gate: PASS` is
structurally unreachable for this plan — AC-7/AC-8 need privacy counsel, not engineering — so
further PVL rounds converge on nothing by construction. Same terminal shape as the sibling plan
`identity-vocab-reconcile_07-08-26`.
