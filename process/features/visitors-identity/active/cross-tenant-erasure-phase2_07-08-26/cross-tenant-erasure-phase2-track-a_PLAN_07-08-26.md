---
name: plan:cross-tenant-erasure-phase2-track-a
description: "PLAN (Track A) — standing write-boundary guard on _save_identified (AC-5) + cross-tenant audit-lookup extension (AC-4); Track B cascade deferred"
date: 07-08-26
feature: visitors-identity
---

# PLAN — Cross-Tenant Erasure Phase 2, Track A

**TL;DR:** One guard + one read-only audit extension. `_save_identified` currently inserts an
`IdentifiedVisitor` with a freshly-discovered email and **zero** suppression check — that is the
whole hole. Add the same `is_email_suppressed_any(db, email, GRAPH_WRITE_BLOCKING_SCOPES)` check
already proven at `_upsert_beam_identity`, plus extend the operator lookup to report which tenants
hold the erased person. No migration, no schema change, no other tenant's row mutated.

**Date**: 07-08-26
**Status**: ACTIVE — VALIDATE cycle 0 `Gate: CONDITIONAL` (6 CONCERN); PVL supplement cycle 1 applied (S1–S5); **VALIDATE cycle 2 `Gate: CONDITIONAL`** (0 FAIL / 3 CONCERN, all 6 cycle-0 items independently re-verified sound) — awaiting PVL supplement cycle 2
**Complexity**: SIMPLE
**Feature**: visitors-identity

## Overview / Context

Phase 1 (`graph-erasure-compliance_07-08-26`) is LIVE in production: it erases a person from the
shared `beam_identity_graph` and blocks all future graph writes. It does **not** stop a *per-tenant*
`IdentifiedVisitor` row from being created for that person at some other site. Track A closes that
one hole with a standing write-time guard, and extends the operator audit lookup so it can answer
"which tenants currently hold this erased person". Track B — mutating other tenants' *existing* rows
— is out of scope and blocked on SPEC Open Questions #1/#3/#4.

Context loaded for this plan: `process/context/all-context.md` (router),
`process/context/tests/all-tests.md`, `process/features/visitors-identity/_GUIDE.md`, and the
SPEC at `cross-tenant-erasure-phase2_SPEC_07-08-26.md`.

## Complexity Rationale

Classified **SIMPLE**. Why: 7 production files touched after the S1/S2 supplement (was 4), ~70 net lines, no new module, no schema/migration, no new endpoint,
no external call, no flag surface beyond one optional kill-switch. COMPLEX would be inflation — this
is one guard structurally identical to an existing, live, reviewed one plus a read-only query
extension.

---

## Scope

| In (Track A) | Out (Track B — deferred) |
|---|---|
| AC-5 — standing write-time guard blocking a *new* `IdentifiedVisitor` for an erased person at any tenant, across **all three** creation paths (resolver, manual Identify, CSV import) | AC-1/2/3/7/8 — the cascade that **mutates other tenants' existing rows** |
| AC-4 — audit lookup: which tenants currently hold the erased person | Suppression-vs-deletion outcome choice |
| AC-6 — regression: `_cascade_suppress` / ordinary suppression path unchanged | Notification to Site B |
| AC-9 — no PII in the new log lines | `EnrichmentProfile` reach (SPEC OQ6) |

**Track B blocking conditions (do not start until all three are answered by product/legal):**
SPEC Open Question **#1** (does Site A's request authorize mutating Site B's own data?), **#3**
(suppress vs delete), **#4** (notification model). Track A ships independently of all three because
it never touches another tenant's existing row — it only refuses to create a *new* one.

---

## What Track A actually changes (verified against the live tree, 07-08-26, `443ad5e`)

**Verified fact 1 — half the problem is already closed.** `IdentityResolver._is_email_opted_out`
(anchor: `git grep -n "True if any email captured for this visitor is on the suppression" -- apps/api/services/identity_resolver.py`)
already calls `is_email_suppressed(db, email, "do_not_process")` over every `VisitorEmail` the site
holds, and `resolve()` gates on it upfront. Phase 1's sweep writes a `do_not_process` tombstone
alongside `erased` (`_TOMBSTONE_SCOPES` in `graph_erasure.py`). So a visitor whose email the site
**already captured** is protected today, for free. No change needed there.

**Verified fact 2 — the hole.** `_save_identified`
(anchor: `git grep -n "async def _save_identified" -- apps/api/services/identity_resolver.py`)
is the path taken when the provider waterfall returns a **freshly discovered** email the site never
had. Reading the full body: it normalizes+lowercases the email, runs `validate_email`, runs the
name↔email consistency check, runs the same-site email dedup query, then constructs
`IdentifiedVisitor(...)`. **There is no suppression check anywhere in that span.** A paid provider
discovering an erased person's email for the first time at some other site is completely open.

**Verified fact 3 — the proven guard shape to copy.** `_upsert_beam_identity`
(anchor: `git grep -n "Write-boundary erasure guard" -- apps/api/services/identity_resolver.py`)
does exactly this, live:

```
if getattr(visitor, "do_not_resolve", False) or await is_email_suppressed_any(
    self.db, email, GRAPH_WRITE_BLOCKING_SCOPES
):
    logger.info("graph_write_blocked", visitor_id=visitor.visitor_id[:8])
    return
```

Confirmed helper signature in `apps/api/services/suppression.py`:
`async def is_email_suppressed_any(db: AsyncSession, email: str, scopes: tuple[str, ...]) -> bool`
— matches on `SuppressionEntry.email_hash == email_hash(email)` and `scope.in_([*scopes, "all"])`.
Confirmed constant in `apps/api/services/graph_erasure.py`:
`GRAPH_WRITE_BLOCKING_SCOPES: tuple[str, ...] = ("erased", "do_not_process")`.

**Verified fact 4 — the `email_bidx` backfill precondition does NOT apply to Track A.**
`is_email_suppressed_any` re-hashes the **plaintext email supplied at write time** via
`pii_crypto.email_hash()` (HMAC-SHA256 over `normalize_email(email)`, deterministic, one
implementation) and compares against `SuppressionEntry.email_hash`. It never reads
`IdentifiedVisitor.email_bidx`. Historical-row `email_bidx` completeness — and
`apps/api/scripts/backfill_pii_ciphertext.py`, which has never been run — is a **Track B**
precondition only (Track B's cascade joins historical rows on `email_bidx`). **Do not block Track A
on it.**

---

## Hard guardrails

| ID | Guardrail |
|---|---|
| G1 | **Match on email hash only, never `fingerprint`.** Phase 1 KG-7 is open: the client-supplied `_fp` is uncorroborated, so a fingerprint-keyed guard would let a crafted ingest event target a stranger's data. `is_email_suppressed_any` is email-hash-only by construction — do not add a fingerprint branch. |
| G2 | No plaintext email, name, or ciphertext in any new log line. Visitor id prefix (`[:8]`) + site id + counts only. |
| G3 | No new existence oracle. The audit extension (AC-4) is added to the **already platform-operator-gated** `/privacy/graph-identity` route, which is double-gated (`settings.graph_identity_lookup_enabled` default OFF → 404, plus `require_admin`). It is never tenant-reachable. |
| G4 | Do not touch `_cascade_suppress`, `add_suppression`, or `remove_suppression`. AC-6 requires the ordinary suppression path be byte-identical. |
| G5 | Do not mutate any other tenant's existing row. That is Track B. Track A only refuses a new insert. |
| G6 | Do not re-open Phase 1 locked decisions: platform-level queue, plaintext-free queue, §4a transaction contract, existence-oracle contract, default-ON sweep, KG-7/KG-8 deferral. |

---

## Touchpoints

| File | Change | Anchor (`git grep -n "<text>" -- <file>`) |
|---|---|---|
| `apps/api/services/identity_resolver.py` | Insert erasure guard in `_save_identified` | `"async def _save_identified"` |
| `apps/api/routers/visitors.py` | Insert erasure guard in `manual_identify_visitor` (**S1**) | `"# Upsert identified visitor"` |
| `apps/api/services/contact_importer.py` | Bulk erasure pre-filter in `import_contacts` (**S1**) | `"async def import_contacts"` |
| `apps/api/services/resolution_runner.py` | Add missing `await db.rollback()` in the per-visitor except handler (**S2**, pre-existing bug) | `"resolve_visitor_error"` |
| `apps/api/services/graph_erasure.py` | Extend `lookup_graph_identity()` return with per-tenant holder lists | `"async def lookup_graph_identity"` |
| `apps/api/schemas/privacy.py` | Add 2 fields to `GraphIdentityLookupOut` | `"class GraphIdentityLookupOut"` |
| `apps/api/config.py` | Add `identity_write_erasure_guard_enabled: bool = True` kill-switch | `"graph_identity_lookup_enabled"` (place adjacent) |
| `tests/unit/test_graph_erasure.py` | New unit cases (code-shape / mocked) | existing file |
| `tests/integration/test_graph_erasure_flow.py` | New integration cases (DB-truth) | existing file |

Read-only for context (not modified): `apps/api/services/suppression.py`,
`apps/api/services/pii_crypto.py`, `apps/api/routers/privacy.py`, `apps/api/routers/visitors.py`,
`apps/api/models/suppression.py`, `tests/conftest.py`.

**No migration.** Track A adds no column, table, index, or constraint. Last known alembic head is
`d1a6c4e93f27` and is **irrelevant to this plan** — nothing here advances it. (Live re-derivation via
`alembic -c apps/api/alembic.ini heads` was not run: the sandbox blocks `.venv` execution. Stated
rather than guessed. If a later reviewer believes a migration is needed, that means scope has drifted
into Track B — stop and re-plan.)

---

## Blast Radius

**Real collision surface (re-checked live, not inherited from the SPEC snapshot):**

| Workstream | State | Collides with Track A? |
|---|---|---|
| `graph-erasure-compliance_07-08-26` (Phase 1) | **LIVE in production.** `origin/main` == `443ad5e`, migration `d1a6c4e93f27` applied, `graph_erasure_sweep_enabled` defaults `True` — the sweep is running now. | **Yes, by dependency, not by conflict.** Track A *consumes* Phase 1's `GRAPH_WRITE_BLOCKING_SCOPES` and `SuppressionEntry(scope="erased")` tombstone. It edits a different function in the same file (`_save_identified`, not `_upsert_beam_identity`) and a different function in `graph_erasure.py` (`lookup_graph_identity`, not the sweep). No overlapping hunk. |
| `identity-vocab-reconcile_07-08-26` | EXECUTED, merged into `main`. Rewrote `identity_resolver.py` §3.2 and `routers/visitors.py`. | **No — already absorbed.** Its rewrite is what the current tree shows; every anchor above was read from post-merge `443ad5e`. Track A does not touch `routers/visitors.py` at all. |
| `identity-coop_07-08-26` | PLAN'd, VALIDATE **BLOCKED**. Consumes the same `scope="erased"` tombstone for co-op ledger exclusion. | **Read-only overlap.** Both read the tombstone; neither writes it. If identity-coop later adds its own guard to `_save_identified`, the two must be merged into one check — flag at that plan's PVL, not here. |

**Because `identity_resolver.py` has been rewritten three times in the last week, every edit site in
this plan is named by content anchor with a reproducing `git grep`. Do not use line numbers.**

> **⚠ LIVE DRIFT NOTICE (recorded at PVL supplement cycle 1).** The branch moved: `devjulley` is now
> **`3072e89`**, not the `443ad5e` this plan was written against, and **the worktree is no longer
> clean**. Uncommitted changes exist in `apps/api/config.py`, `apps/api/main.py`,
> `apps/api/models/site.py`, and — critically — **`apps/api/services/identity_resolver.py`**, plus two
> untracked new files `apps/api/{models,services}/identity_coop.py`. This is the `identity-coop`
> workstream, which the table above still lists as "PLAN'd, VALIDATE BLOCKED" — **that row is stale**;
> the work is in progress on disk.
>
> Assessed at supplement time: **no hunk conflict with Track A.** The coop diff touches `resolve()`'s
> tail and `_upsert_beam_identity` (whose return type changed `None` → `bool`); Track A edits
> `_save_identified`. All three Touchpoints anchors re-verified as still resolving exactly once
> against the dirty tree. **But EXECUTE must re-check this before editing** — if identity-coop lands
> its own guard in `_save_identified`, the two checks must be merged into one, per the original
> read-only-overlap note above.

**Risk class:** privacy/compliance + identity write path. Not auth, not billing, not schema, not
public API (the touched endpoint is admin-only and flag-gated OFF). Files: 4 production + 2 test.

---

## Public Contracts

| Contract | Change | Compatibility |
|---|---|---|
| `IdentityResolver._save_identified(...)` | Return type unchanged (`IdentifiedVisitor \| None`). New early `return None` branch when the email is erasure-suppressed. Callers already handle `None` (three existing `return None` branches: validation reject, name↔email mismatch, no-identity-data). | Additive, non-breaking |
| `GET /api/v1/privacy/graph-identity` → `GraphIdentityLookupOut` | Two **additive optional** fields: `tenant_holder_site_ids: list[str]` and `tenant_holder_row_count: int`. Existing fields untouched. | Additive. Route stays admin-only + `graph_identity_lookup_enabled` gated (404 when off). |
| `graph_erasure.lookup_graph_identity()` | Returns two extra dict keys. Sole caller is `routers/privacy.py`. | Additive |
| `settings.identity_write_erasure_guard_enabled` | New, defaults `True` (guard ON). | New |

**Existence-oracle check (G3):** the new fields are on a route that is *already* a deliberate
existence oracle for platform operators only, double-gated. No tenant-facing response shape changes.
The erasure DELETE endpoint response in `routers/visitors.py` is **not touched** — its shape stays
identical regardless of how many tenants hold the person (Phase 1's C1 rule preserved).

---

## Implementation Checklist

### Section 1 — The guard (AC-5)

1. **`apps/api/config.py`** — add `identity_write_erasure_guard_enabled: bool = True` immediately
   adjacent to `graph_identity_lookup_enabled` (anchor: `git grep -n "graph_identity_lookup_enabled" -- apps/api/config.py`).
   Inline comment: defaults **ON** because this is a compliance guard, not a feature; the flag exists
   solely as an operator kill-switch if the guard misfires against a live resolution path.
   *(Deliberate inversion of the repo's default-OFF convention — justified in Rollout below.)*

2. **`apps/api/services/identity_resolver.py`, `_save_identified`** — insert the guard **after** the
   email normalize+`validate_email` block and **before** the `PAID_PERSON_GRAPH_PROVIDERS`
   name↔email consistency check.
   Anchor for the insertion point: the line
   `git grep -n "Paid person-graphs: reject obvious name" -- apps/api/services/identity_resolver.py`
   — the guard goes immediately above that comment.

   Shape (mirrors `_upsert_beam_identity` exactly):
   - Local imports inside the function (matches the existing file convention — `_upsert_beam_identity`
     and `_is_email_opted_out` both import locally to avoid a circular import with
     `graph_erasure` → `identity_resolver`).
   - Guard runs only when `data.get("email")` is truthy **and**
     `settings.identity_write_erasure_guard_enabled`.
   - Condition: `await is_email_suppressed_any(self.db, email, GRAPH_WRITE_BLOCKING_SCOPES)`.
   - On block: `logger.info("identity_write_blocked_erased", visitor_id=visitor.visitor_id[:8], site_id=visitor.site_id, provider=provider)` then `return None`.
     **No email, no name, no hash in the log (G2).**
   - No `try/except` swallow. Unlike `_is_email_opted_out` (which fails *open* on exception because
     it is a budget pre-gate), this is a compliance write boundary: if the suppression lookup raises,
     the exception must propagate so the write does not silently proceed. Record this choice in the
     inline comment — a future reader will otherwise "helpfully" wrap it.

3. Do **not** add a `do_not_resolve` visitor check here. `resolve()` already gates on
   `visitor.do_not_resolve` upstream; duplicating it adds a second failure mode without new coverage.
   The guard's job is specifically the *freshly discovered email* case that upstream cannot see.

4. **(S3 — contradiction resolved.)** Verified live at `3072e89`: the anchor in item 2 (the
   `"Paid person-graphs: reject obvious name"` comment, `identity_resolver.py:1101`) sits **before**
   the email-dedup `canonical` block (`1117-1144`). So the guard's `return None` fires *first* and the
   dedup/merge branch is **unreachable for a suppressed email**. KG-A1 as originally written (claiming
   the merge path stays open) was therefore **false**.

   **Decision: keep the anchor where item 2 puts it, and correct the narrative.** Rationale: guarding
   the merge path too is strictly *more* protective, costs nothing, and still never mutates an
   existing row — `return None` refuses to link, it does not touch `canonical`. Moving the anchor
   below the dedup block to manufacture the gap would be deliberately weakening a compliance guard to
   match a stale comment.

   Consequences, all mandatory:
   - The inline comment at the site must say: *"This guard runs before the email-dedup/merge block, so
     a suppressed email is also refused a merge-link to a pre-existing row. Refusing to link is not a
     mutation of that row — Track B's boundary (mutating existing rows) is still respected."*
   - **KG-A1 is rewritten** in Known Gaps (below) from "merge still links" to its true, narrower form.
   - A new integration test pins the behavior (Section 3, item 9).

### Section 1b — The two unguarded front doors (S1)

**Finding (verified live at `3072e89`).** `_save_identified` is **not** the only path that creates an
`IdentifiedVisitor`. Two live paths construct and commit one straight from caller-supplied data with
**zero** suppression check (`git grep -n "suppress\|erased\|do_not_process"` over both files returns
nothing):

| Path | Site | Shape |
|---|---|---|
| `manual_identify_visitor`, `POST /{site_id}/{visitor_id}/identify` | `apps/api/routers/visitors.py` (anchor `"# Upsert identified visitor"`) | single interactive write; a site owner types an email into the dashboard "Identify" button |
| `import_contacts` | `apps/api/services/contact_importer.py` (anchor `"async def import_contacts"`) | bulk loop; one `db.add(IdentifiedVisitor(...))` per CSV row, single `commit()` at the end |

Both are exactly the harm AC-5 names — a tenant getting an erased person's email for the first time —
so AC-5's original "at any site, indefinitely" was **false as shipped**.

**Decision: option (a) — extend the guard to both sites.** Rationale: option (b) (narrowing AC-5 to
the resolver path and logging a Known-Gap) is honest but leaves a live, trivially-reachable hole in a
compliance feature — an operator can defeat an erasure by retyping one email. The bulk-import
semantics that made (a) look risky are specifiable cleanly (below), and the importer already does a
bulk `IdentifiedVisitor.email.in_([...])` pre-query, so the pattern is a direct copy.

4a. **`apps/api/routers/visitors.py`, `manual_identify_visitor`** — insert the guard immediately after
    the `visitor` 404 check and **before** the `# Upsert identified visitor` block. Same helper, same
    scopes: `await is_email_suppressed_any(db, body.email, GRAPH_WRITE_BLOCKING_SCOPES)`, gated on
    `settings.identity_write_erasure_guard_enabled`. Local import (circular-import convention).
    - **On block: `raise HTTPException(status_code=422, detail="This email cannot be identified.")`** —
      not a silent `None`. This is an interactive request with a human waiting; a silent no-op would
      read as a UI bug and the operator would retry forever.
    - **422, not 404/403, and the message is deliberately generic** (no "erased", no "suppressed").
      G3: the route is tenant-reachable, so the response must not become an existence oracle telling a
      site owner that a specific stranger was erased platform-wide. 422 = "we won't accept this
      value", which is already the shape used for validation rejects on this surface.
    - Guard the `existing`-row update branch too (the `if identified:` path overwrites
      `identified.email` — same hazard). Placing the guard before the whole upsert block covers both
      branches with one check.
    - `logger.info("identity_write_blocked_erased", source="manual", visitor_id=visitor_id[:8], site_id=site_id)` — no email (G2).

4b. **`apps/api/services/contact_importer.py`, `import_contacts`** — add **one bulk** pre-filter
    alongside the existing `already` dedup query (anchor: the `IdentifiedVisitor.email.in_([c["email"] for c in valid])`
    block). Do **not** call `is_email_suppressed_any` per row — the file's own established pattern is a
    single `in_()` query, and a per-row lookup would be N queries inside the loop.
    - Compute `hashes = {email_hash(c["email"]): c["email"] for c in valid}`, then one
      `select(SuppressionEntry.email_hash).where(SuppressionEntry.email_hash.in_(hashes), SuppressionEntry.scope.in_([*GRAPH_WRITE_BLOCKING_SCOPES, "all"]))`.
      This mirrors `is_email_suppressed_any`'s own predicate (verified: `email_hash ==` +
      `scope.in_([*scopes, "all"])`) in set form. `uq_suppression_hash_scope` has `email_hash` as its
      leading column, so this is an index lookup, not a scan.
    - **Failure semantics (the question that made option (a) look risky):** a suppressed row is
      **skipped, not fatal**. Append to the existing `rejected` list with
      `{"line": None, "reason": "cannot be imported"}` — the same generic shape already used for
      `"already imported"` — and `continue`. The rest of the file imports normally.
      **Rationale:** the importer's only existing all-or-nothing behavior is the
      `MAX_IMPORTED_CONTACTS_PER_SITE` cap, which is a quota, not a per-row condition. Aborting a
      500-row CSV because one row is suppressed would be a worse product and would pressure operators
      into bisecting the file — i.e. into an existence oracle. Per-row skip matches the file's
      existing per-row `rejected` semantics exactly.
    - **Reason string is generic** (`"cannot be imported"`, never `"erased"`) — same oracle reasoning
      as 4a, and stronger here because the caller controls the input set and could binary-search it.
    - `logger.info("contacts_import_erasure_blocked", site_id=site_id, blocked=<count>)` — count only (G2).

4c. Both new guards use the **same** helper, the **same** `GRAPH_WRITE_BLOCKING_SCOPES`, and the
    **same** kill-switch `settings.identity_write_erasure_guard_enabled`. One flag turns off all three
    guards together — do not add per-site flags.

4d. **G1 unchanged:** neither new guard keys on `fingerprint`. Both match on email hash only.

### Section 1c — Fix the batch-wide silent outage the fail-closed design makes reachable (S2)

**Finding (verified live at `3072e89`).** `apps/api/services/resolution_runner.py` (`_resolve_site`,
anchor `"resolve_visitor_error"`, ~L171-183) is the live APScheduler sweep — wired at
`apps/api/jobs/scheduler.py:56` via `run_resolution_sweep()`. It shares **one** `db` session across up
to `max_resolve` visitors (default **20**, `SWEEP_MAX_RESOLVE_PER_SITE` at the call site) and wraps
`resolver.resolve(...)` in a bare `except Exception as e: logger.warning("resolve_visitor_error", ...)`
with **no `await db.rollback()`**.

The correct sibling pattern already exists in this repo:
`apps/api/services/agent_company_resolution.py:153-162` does call `await db.rollback()` in its
equivalent per-row handler (comment: *"Per-row fail-open: one bad row must not abort the sweep"*).
Both files were read end to end; the asymmetry is real.

**Consequence.** On the exact transient-DB-error scenario this plan itself anticipates (item 2's
deliberate no-`try/except` fail-closed design), the guard's exception is swallowed **without a
rollback**, the shared session enters `PendingRollbackError`, and every subsequent visitor in that
site's batch fails on session state — e.g. visitors #8–20 die as 13 generic WARNING lines with one
root cause, and the site's remaining resolution budget for that interval is burned. This directly
contradicts `_resolve_site`'s own docstring claim that each visitor is processed in isolation.

**Classification: pre-existing bug, but required by this design.** Track A does not introduce it —
the live `_upsert_beam_identity` guard has the identical no-`try/except` shape. But Track A
deliberately adds a *third* raising boundary on this exact path, so shipping Track A without this
fix means shipping a known batch-kill trigger. It is in scope.

4e. **`apps/api/services/resolution_runner.py`** — add `await db.rollback()` as the **first**
    statement inside the existing `except Exception as e:` handler, before the `logger.warning`.
    Copy the comment shape from `agent_company_resolution.py:153-162`. Do not otherwise restructure
    the loop, do not add a nested try, do not change the log event name.

4f. **Proving gate (Section 3, item 9):** an integration test where visitor #1's `resolve()` raises
    and visitors #2-#3 in the **same batch, same session** still resolve successfully. Without the
    rollback this test fails on `PendingRollbackError`; with it, it passes. This is the only gate that
    proves the fix — a unit assertion that `rollback` was called would pass against a mock while the
    real session bug survived.

### Section 2 — The audit lookup extension (AC-4)

5. **`apps/api/services/graph_erasure.py`, `lookup_graph_identity()`** — anchor
   `git grep -n "async def lookup_graph_identity" -- apps/api/services/graph_erasure.py`.
   When `bidx is not None` (email-keyed lookup only), add two read-only queries:
   - `select(IdentifiedVisitor.site_id).where(IdentifiedVisitor.email_bidx == bidx)`
   - `select(VisitorEmail.site_id).where(VisitorEmail.email_bidx == bidx)`
   Union the site ids, and return `tenant_holder_site_ids: sorted(set(...))` plus
   `tenant_holder_row_count: <total row count across both>`.
   For the fingerprint-keyed branch (`bidx is None`), return `[]` and `0` — **G1: never join tenant
   rows on fingerprint.** Add an inline comment stating why (KG-7).
   Both models are already imported at module top (`IdentifiedVisitor`, `VisitorEmail`) — verified.

5a. **S5 — the new read query is a fresh consumer of an incomplete column. Disclose it.**
   `tenant_holder_site_ids` joins on `IdentifiedVisitor.email_bidx` / `VisitorEmail.email_bidx`. Both
   are **nullable** and populated only by the `before_insert` / `before_update` listeners registered in
   `apps/api/services/pii_encryption_hooks.py:52-64`. Any row created **before** those hooks landed,
   and never updated since, keeps `email_bidx IS NULL` and is **invisible** to this lookup.
   `apps/api/scripts/backfill_pii_ciphertext.py` exists (verified on disk) but **has never been run**.

   This does **not** touch "Verified fact 4" above — that argument is correct and stands **for the
   write guard**, which re-hashes fresh plaintext at write time and never reads `email_bidx`. It was
   simply never applied to the new **read** path, which does.

   **Decision: disclose, do not precondition.** Rationale: making Track A block on a never-run
   repo-wide PII backfill would gate a write-side compliance guard on an unrelated data migration —
   and the backfill is already a stated **Track B** precondition (Track B's cascade joins historical
   rows on `email_bidx`), so it will be run there anyway. Preconditioning here buys nothing and delays
   the guard.

   Mandatory consequences (the undercount must be visible at the point of reading, not buried):
   - The `GraphIdentityLookupOut` docstring (item 6) **must** carry the caveat verbatim — this is the
     schema an operator reads. Wording: *"`tenant_holder_*` is a LOWER BOUND. It matches on
     `email_bidx`, which is populated only by the PII encryption hooks; rows predating those hooks and
     never since updated are invisible. `apps/api/scripts/backfill_pii_ciphertext.py` has not been run.
     Do not read an empty or short list as proof that no tenant holds this person."*
   - The `get_graph_identity` route docstring (item 7) repeats the one-line "LOWER BOUND" caveat.
   - **Recorded as Known-Gap KG-A6** (below), and AC-4's criterion wording is narrowed to say
     "lower bound" rather than implying completeness.

6. **`apps/api/schemas/privacy.py`, `GraphIdentityLookupOut`** — anchor
   `git grep -n "class GraphIdentityLookupOut" -- apps/api/schemas/privacy.py`. Add:
   `tenant_holder_site_ids: list[str] = []` and `tenant_holder_row_count: int = 0`.
   Extend the existing class docstring to state these carry **site ids and counts only — never an
   email, name, or ciphertext**, and that this route is platform-operator-only.

7. **`apps/api/routers/privacy.py`** — no code change required (the handler already splats
   `**await lookup_graph_identity(...)` into the model). Verify by reading; do not edit if unchanged.
   Update the `get_graph_identity` docstring one line to note it now also answers *"which tenants
   still hold this person"* — the Track A answer to AC-4.

### Section 3 — Tests

8. **Unit** (`tests/unit/test_graph_erasure.py`) — code-shape / mocked only, **no DB**
   (`tests/conftest.py:4`: "Unit tests: no DB, no network — use mocks").

   **MOCK TARGET RULE (S4 — read this before writing a single test).** The original item 8 said
   "mock `is_email_suppressed_any`" without naming a patch target. That is the same defect class the
   sibling erasure plan burned 8 PVL cycles on. Item 2 specifies a **local** import
   (`from apps.api.services.suppression import is_email_suppressed_any` *inside* the function body),
   so the name **never binds in `identity_resolver`'s module namespace** — patching
   `apps.api.services.identity_resolver.is_email_suppressed_any` silently patches nothing, the real
   helper runs, and the test passes while proving nothing.

   **Default pattern (use this unless a test genuinely needs call-args):** mock `db.execute` and let
   the **real** `is_email_suppressed_any` run. This is exactly what the two existing sibling tests in
   this same file already do — `test_t_u1` / `test_t_u2` at `tests/unit/test_graph_erasure.py:106-159`
   (`MagicMock()` db + `_scalar_result(...)`). Read them and copy the shape verbatim.

   **Exception (call-arg assertions only):** where a test must assert *what the helper was called
   with*, patch the **origin**: `apps.api.services.suppression.is_email_suppressed_any`. Never the
   `identity_resolver` / `visitors` / `contact_importer` module path. Pair every such mock-call
   assertion with an observable side-effect assertion (`db.add` call count, or the returned value /
   raised `HTTPException`) so a silently-mistargeted patch cannot produce a false green.

   Cases:
   - `test_save_identified_blocks_when_suppressed` — **db.execute pattern** (suppression row present),
     assert `_save_identified` returns `None` and `db.add` was never called.
   - `test_save_identified_proceeds_when_not_suppressed` — **db.execute pattern** (no row), assert
     `db.add` called.
   - `test_save_identified_guard_respects_kill_switch` — flag `False`; **origin-patch** exception case:
     patch `apps.api.services.suppression.is_email_suppressed_any` and assert it is **not awaited**,
     paired with the side-effect assertion that `db.add` **was** called.
   - `test_guard_uses_email_hash_scopes_only` — **origin-patch** exception case (needs call args):
     patch `apps.api.services.suppression.is_email_suppressed_any`, assert it was called with
     `GRAPH_WRITE_BLOCKING_SCOPES` and that no `fingerprint` kwarg appears anywhere (G1). Pair with
     `assert result is None` so a mistargeted patch cannot pass.
   - `test_manual_identify_blocks_when_suppressed` (**S1/4a**) — **db.execute pattern**; assert
     `HTTPException` with `status_code == 422` and that `detail` contains neither `"erased"` nor
     `"suppress"` (generic-message / oracle rule).
   - `test_contact_import_skips_suppressed_row` (**S1/4b**) — **db.execute pattern**; assert the
     suppressed email is absent from the added rows, appears in `rejected` with a generic reason, and
     that the other rows still imported.
   - `test_guard_log_contains_no_pii` — capture the structlog event, assert no `@` and no full
     visitor id in any emitted value (G2 / AC-9 automated leg).
   - **Import ordering:** `import apps.api.main` first — SQLAlchemy `InvalidRequestError` otherwise
     when constructing ORM objects in the unit lane (known repo gotcha).

9. **Integration** (`tests/integration/test_graph_erasure_flow.py`) — DB-truth assertions:
   - `test_new_tenant_write_blocked_after_erasure` (**AC-5**) — seed a real
     `SuppressionEntry(email_hash=email_hash(E), scope="erased")`, run `_save_identified` for Site Z
     with email `E`, assert **zero** `IdentifiedVisitor` rows exist for Site Z with that email.
   - `test_audit_lookup_reports_tenant_holders` (**AC-4**) — seed `IdentifiedVisitor` at Site B and
     `VisitorEmail` at Site C for the same email, call `lookup_graph_identity(db, email=E)`, assert
     `tenant_holder_site_ids == ["site_b", "site_c"]` and the count is right.
   - `test_audit_lookup_fingerprint_branch_returns_no_holders` (**G1**) — fingerprint-keyed lookup
     returns `[]` / `0` even with matching tenant rows present.
   - `test_cascade_suppress_unaffected` (**AC-6**) — run `add_suppression()` → `_cascade_suppress()`
     for an ordinary `do_not_email` scope, assert `IdentifiedVisitor.do_not_email` and
     `Visitor.do_not_resolve` flip exactly as before; assert the new guard did not interfere.
   - `test_non_suppressed_resolution_still_writes` — regression: an ordinary unsuppressed
     resolution still produces an `IdentifiedVisitor` row (guard is a no-op for everyone else).
   - `test_dedup_merge_blocked_for_suppressed_email` (**S3**) — seed a pre-existing
     `IdentifiedVisitor` at Site B for email `E` under visitor_id X, seed
     `SuppressionEntry(email_hash(E), scope="erased")`, then run `_save_identified` for the same site
     under visitor_id Y with email `E`. Assert: return is `None`; visitor Y's `identity_status` is
     **not** `"merged"`; `canonical_visitor_id` is unset; and **the pre-existing row X is byte-identical**
     (Track B boundary — refusing to link is not a mutation). This is the test that pins the S3
     decision so KG-A1's corrected text is enforced, not merely asserted in prose.
   - `test_manual_identify_endpoint_blocked_after_erasure` (**S1/4a**, DB-truth) — seed the tombstone,
     `POST /{site_id}/{visitor_id}/identify` with the erased email, assert 422 **and** zero
     `IdentifiedVisitor` rows created for that site.
   - `test_contact_import_skips_erased_row` (**S1/4b**, DB-truth) — 3-row CSV, middle row erased;
     assert 2 rows land, the erased email has zero `IdentifiedVisitor` rows anywhere, and the response
     `rejected` entry carries a generic reason.
   - `test_batch_survives_one_resolver_exception` (**S2/4f**) — the only gate that proves the
     `resolution_runner` rollback fix. Drive `_resolve_site` over 3 seeded visitors on **one shared
     session**; force visitor #1's `resolve()` to raise; assert visitors #2 and #3 still resolve
     successfully (no `PendingRollbackError`) and `counters["resolved"] == 2`. Without
     `await db.rollback()` in the handler this test fails; with it, it passes. A unit-level
     "was rollback called" assertion does **not** substitute — it would pass against a mock while the
     real session bug survived.

10. **Agent-probe** (AC-9) — run the integration flow at DEBUG, read the captured structlog records,
    confirm no plaintext email/name/ciphertext appears in any record emitted by the two new code
    paths. Record the judgment in the phase report.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `.venv/bin/python3.11 -m pytest tests/unit/test_graph_erasure.py -m unit -q` | Fully-Automated | AC-5 (code-shape), AC-9 (log leg), G1, G2 |
| `.venv/bin/python3.11 -m pytest tests/integration/test_graph_erasure_flow.py -m integration -q` → `test_new_tenant_write_blocked_after_erasure` | Fully-Automated | **AC-5** (DB truth: zero rows written) |
| Same file → `test_audit_lookup_reports_tenant_holders` | Fully-Automated | **AC-4** (tenant list + count, no ad-hoc SQL) |
| Same file → `test_audit_lookup_fingerprint_branch_returns_no_holders` | Fully-Automated | G1 (KG-7 fingerprint ban) |
| Same file → `test_cascade_suppress_unaffected` | Fully-Automated | **AC-6** (no regression on the ordinary path) |
| Same file → `test_non_suppressed_resolution_still_writes` | Fully-Automated | AC-6 (guard is a no-op for unsuppressed) |
| `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` (full unit lane) | Fully-Automated | AC-6 regression, whole-lane |
| `.venv/bin/python3.11 -m pytest tests/ -m integration -q` (full integration lane) | Fully-Automated | AC-6 regression, whole-lane |
| Same file → `test_manual_identify_endpoint_blocked_after_erasure` | Fully-Automated | **AC-5** (S1/4a — manual Identify front door) |
| Same file → `test_contact_import_skips_erased_row` | Fully-Automated | **AC-5** (S1/4b — CSV import front door; per-row skip semantics) |
| Same file → `test_dedup_merge_blocked_for_suppressed_email` | Fully-Automated | **S3** — pins the guard-vs-dedup ordering so KG-A1's corrected text is enforced |
| Same file → `test_batch_survives_one_resolver_exception` | Fully-Automated | **S2/4f** — proves the `resolution_runner` rollback fix; without it the shared session dies at `PendingRollbackError` and the rest of the batch is silently lost |
| DEBUG log inspection of **all four** new paths (resolver guard, manual-Identify guard, import pre-filter, audit lookup) | Agent-Probe | **AC-9** (no PII in logs) |
| Track B ACs (AC-1/2/3/7/8) | — | **Deferred to Track B.** Blocked on SPEC OQ1/OQ3/OQ4. Not a known-gap of Track A: out of scope by design, recorded in Known Gaps below with the unblocking conditions. |

**Tier discipline (learned from the sibling erasure plan's 8 wasted PVL cycles):** every DB-truth
assertion above sits in the **integration** tier because the unit lane has no database
(`tests/conftest.py:4`). Every unit-tier assertion above is **code-shape only** (mock call
assertions, return values, log record content). Do not move a row between tiers.

**Runner note:** use `.venv/bin/python3.11 -m pytest`. `.venv/bin/pytest` has a broken shebang
pointing at a pre-move path. Before running the unit lane, check `docker ps` / port 6379 — a stray
local Redis container shadows the conftest's unit-lane `REDIS_URL` assumption and poisons db15,
producing deterministic-but-fake failures.

**Baseline (07-08-26 gate run, real):** integration **518 passed / 0 failed / 0 errors**, unit
**1203 passed**. Docker is proven working in this repo — integration gates are genuinely runnable and
must NOT be deferred as environment-blocked. Any new red is caused by this change.

---

## Rollout / Rollback Posture

**This is a live-production change.** Phase 1 is running in prod right now (`graph_erasure_sweep_enabled`
defaults `True`, migration applied). Railway auto-applies migrations and redeploys on push to `main`,
so **merging is a production change, not a staging step.**

- **The guard ships ON** (`identity_write_erasure_guard_enabled: bool = True`). Deliberate inversion
  of the repo's default-OFF convention: a compliance guard that ships OFF provides zero compliance.
  Blast radius of shipping ON is bounded — the guard is a strict no-op for any email with no
  `SuppressionEntry` row in scope `erased`/`do_not_process`/`all`, which is the overwhelming majority.
- **Misfire mode.** The only way it misfires is a false-positive suppression match, which requires a
  hash collision on HMAC-SHA256 (not a practical concern) or an incorrectly-written tombstone
  (Phase 1's problem, not Track A's).
- **In-flight resolutions.** The guard returns `None` before `db.add()`, before any commit, on a path
  whose three sibling early-returns already return `None`. An in-flight resolution that trips the
  guard degrades to "not identified" — the same outcome as a failed provider lookup or a rejected
  email. It does not raise to the caller and leaves no partial row.
- **Correction (S2) — "does not abort the ingest request" was only half true.** It holds for the
  synchronous ingest path, where resolution never runs inline. It does **not** hold for the
  APScheduler sweep: `resolution_runner._resolve_site` shares one session across up to 20 visitors and
  its bare `except` had **no `await db.rollback()`**, so a raise from any guard put the shared session
  into `PendingRollbackError` and silently killed the remainder of that site's batch. Section 1c fixes
  this (item 4e) and `test_batch_survives_one_resolver_exception` proves it. The fail-closed
  no-`try/except` design in item 2 is unchanged — the containment now lives where it belongs, in the
  caller's per-visitor handler, matching `agent_company_resolution.py:153-162`.
- **Manual-Identify misfire mode (S1/4a):** a false positive surfaces as a 422 with a generic message.
  Recoverable, visible, no data loss. Kill-switch reverts it.
- **CSV-import misfire mode (S1/4b):** a false positive skips one row and reports it in `rejected`.
  The rest of the file imports. No partial-commit hazard — the skip happens before `db.add`.
- **Rollback:** set `IDENTITY_WRITE_ERASURE_GUARD_ENABLED=false` in the Railway env and restart —
  no redeploy, no migration reversal, no data cleanup. Code rollback is a plain revert; nothing is
  persisted that a revert would orphan.
- **Mock mode:** unaffected. The guard makes only a local DB query; no external call is added, so
  `MOCK_EXTERNAL_APIS=true` needs no new branch.

---

## Known Gaps (Track A)

| ID | Gap | Disposition |
|---|---|---|
| KG-A1 | **(Rewritten at S3 — the original text was false.)** The guard is anchored *before* the email-dedup `canonical` block, so a suppressed email is refused a merge-link too. The residual gap is narrower: the pre-existing row it would have linked to is **left untouched and still live** at that site. | **By design.** Refusing to link is not a mutation; mutating or deleting that pre-existing row is Track B. Pinned by `test_dedup_merge_blocked_for_suppressed_email`. Inline comment at the site states the anchor ordering explicitly. |
| KG-A2 | Name-only identities (no email) cannot be guarded — there is no hash key to match on. | Accepted. Matches Phase 1's posture; the erasure model is email-hash-keyed throughout. |
| KG-A3 | Track A blocks *new* writes but leaves every existing cross-tenant row live — the actual KG-6 harm (Site B keeps emailing) is untouched. | **This is Track B's entire purpose.** Track A is the standing guard half, shipped early because it is unblocked. Must be stated plainly in any compliance claim: Track A alone does not close KG-6. |
| KG-A4 | `EnrichmentProfile` not covered (SPEC OQ6). | Deferred with Track B. |
| KG-A5 | **(Closed by S1, retained for audit trail.)** Manual-Identify and CSV-import were unguarded at cycle 0. | **RESOLVED in this plan** via Section 1b option (a). Not a shipping gap. |
| KG-A6 | **(S5)** `tenant_holder_site_ids` / `tenant_holder_row_count` are a **LOWER BOUND** — they join on nullable `email_bidx`, populated only by the PII encryption hooks; rows predating the hooks and never since updated are invisible. `apps/api/scripts/backfill_pii_ciphertext.py` has never been run. | **Disclosed, not preconditioned.** Caveat is mandatory in both the `GraphIdentityLookupOut` and route docstrings so the operator sees it at read time. Resolution path: running the backfill (already a Track B precondition) makes the answer complete. An empty list is **not** proof that no tenant holds the person. |

---

## Acceptance Criteria

| # | Criterion | proven by | strategy |
|---|---|---|---|
| AC-5 | A tenant that independently obtains an erased person's email cannot create an `IdentifiedVisitor` row for them, at any site, indefinitely — the write is refused at **all three** creation paths: the automated resolver (`_save_identified`), the dashboard manual-Identify endpoint (`routers/visitors.py`), and bulk CSV import (`contact_importer.py`). **(S1 — wording now matches the implemented scope; option (a) chosen.)** | `test_new_tenant_write_blocked_after_erasure` + `test_manual_identify_endpoint_blocked_after_erasure` + `test_contact_import_skips_erased_row` (all integration) + the 7 unit guard cases | Fully-Automated |
| AC-4 | Given an erased person's email, a platform operator can list which tenants still hold a matching `IdentifiedVisitor`/`VisitorEmail` row, and how many — without ad-hoc SQL. **The answer is a documented LOWER BOUND** (`email_bidx` incompleteness — KG-A6, disclosed in both docstrings). | `test_audit_lookup_reports_tenant_holders` (integration) | Fully-Automated |
| AC-6 | `add_suppression()` → `_cascade_suppress()` and the ordinary `do_not_email`/`do_not_resolve` path behave exactly as they do today. | `test_cascade_suppress_unaffected` + `test_non_suppressed_resolution_still_writes` (integration) + full unit and integration lanes green against the 07-08-26 baseline | Fully-Automated |
| AC-9 | Neither new code path logs a plaintext email, name, or ciphertext. | `test_guard_log_contains_no_pii` (unit) + DEBUG log-inspection probe over the integration flow | Agent-Probe |
| G1 | No suppression match anywhere in this work keys on `fingerprint` (Phase 1 KG-7: `_fp` is uncorroborated and attacker-supplied). | `test_guard_uses_email_hash_scopes_only` (unit) + `test_audit_lookup_fingerprint_branch_returns_no_holders` (integration) | Fully-Automated |
| AC-1/2/3/7/8 | — | **Deferred to Track B.** Blocked on SPEC OQ1 (authorization to mutate another tenant's own data), OQ3 (suppress vs delete), OQ4 (notification). Not planned or checklisted here. | n/a |

## Phase Completion Rules

Track A is a single-phase SIMPLE plan. It is complete only when **all** of the following hold:

1. Every checklist item in Sections 1–3 is applied, and every `git grep` anchor in Touchpoints was
   re-verified against the live tree immediately before editing.
2. Every Fully-Automated row in Verification Evidence is green, run with
   `.venv/bin/python3.11 -m pytest` (never `.venv/bin/pytest` — broken shebang).
3. The full unit lane (baseline **1203 passed**) and full integration lane (baseline **518 passed /
   0 failed / 0 errors**) show no new red. Docker is proven working here — a red integration gate is
   a real failure, never an environment deferral.
4. The AC-9 Agent-Probe judgment is recorded in the phase report.
5. Known Gaps KG-A1–KG-A4 are carried forward verbatim into the phase report.

**Status vocabulary:** code applied with gates green is `CODE DONE`. Promotion to `VERIFIED` also
requires items 3–5 above. Track A reaching `VERIFIED` does **not** mean KG-6 is closed — see KG-A3.

---

## Test Infra Improvement Notes

1. **Mock-target footgun is structural, not a one-off (S4).** Every erasure guard in this codebase uses
   a *local* import to dodge the `graph_erasure` ↔ `identity_resolver` circular import. That makes
   `mock.patch("<consumer_module>.is_email_suppressed_any")` a silent no-op — the patch applies to a
   name that never binds. Two plans have now hit this. Worth a shared fixture (e.g.
   `suppressed_email(db_mock, email)` building the `_scalar_result` shape) in
   `tests/unit/test_graph_erasure.py`, plus a one-line note in `process/context/tests/all-tests.md`.
2. **No test exercised the shared-session batch-isolation contract (S2).** `_resolve_site`'s docstring
   claimed per-visitor isolation that the code did not provide, and nothing caught it for the life of
   the file. `test_batch_survives_one_resolver_exception` is the first. Every sweep that shares one
   session across a loop (`resolution_runner`, `agent_company_resolution`, and any future sweep) should
   have an equivalent one-raises-rest-survive test.
3. **`email_bidx`-joined read paths have no completeness guard (S5).** Nothing warns when a new query
   joins on a nullable, hook-populated, never-backfilled column. Consider a lint/grep check, or run
   `apps/api/scripts/backfill_pii_ciphertext.py` and remove the class of gap entirely.

---

## Resume and Execution Handoff

1. **Selected plan file:** `process/features/visitors-identity/active/cross-tenant-erasure-phase2_07-08-26/cross-tenant-erasure-phase2-track-a_PLAN_07-08-26.md`
2. **Last completed phase/step:** PLAN written, VALIDATE cycle 0 run (`Gate: CONDITIONAL`, 0 FAIL /
   6 CONCERN), **PVL supplement cycle 1 applied (S1–S5)**. No implementation started. `devjulley` is
   now at **`3072e89`** — it moved from the `443ad5e` recorded at plan-write time (2 commits ahead of
   `origin/devjulley`). Every anchor in Touchpoints was **re-verified against `3072e89`** during this
   supplement, including the three newly added files.
3. **Validate-contract status:** written, `Gate: CONDITIONAL` (see the Validate Contract section
   below). Supplement cycle 1 applied — all four contract findings F1–F4 plus the verifier's S5
   `email_bidx` finding are now resolved in-plan. Awaiting PVL re-run from V1.
4. **Supporting context loaded:** `cross-tenant-erasure-phase2_SPEC_07-08-26.md` (full),
   `process/features/visitors-identity/_GUIDE.md`, `process/context/tests/all-tests.md`,
   `apps/api/services/identity_resolver.py` (`_save_identified`, `_upsert_beam_identity`,
   `_is_email_opted_out`), `apps/api/services/graph_erasure.py`,
   `apps/api/services/suppression.py`, `apps/api/routers/privacy.py`,
   `apps/api/schemas/privacy.py`, `apps/api/models/erasure_request.py`.
5. **Next step for a fresh agent:** run VALIDATE on this plan. Then EXECUTE Section 1 → run its test
   gates → Section 2 → gates → Section 3. **Before touching `identity_resolver.py`, re-run every
   `git grep` anchor in Touchpoints** — that file has been rewritten three times in the last week and
   anchors may have moved even if the text is stable. If any anchor no longer resolves, stop and
   re-plan rather than guessing at the insertion point.

---

## Validate Contract

Status: CONDITIONAL
Date: 07-08-26
date: 2026-08-07
generated-by: outer-pvl
supersedes: 2026-08-07 (outer-pvl) — PVL cycle 2 re-validation, prior contract's 6 CONCERNs
  addressed by supplement cycle 1 (S1–S5); this pass independently re-verifies all five items
  against the current live tree and surfaces 3 new, smaller findings.

Parallel strategy: sequential
Rationale: No Agent tool grant in this session — Layer 1 (4 dimensions) and Layer 2 (5 sections:
1, 1b, 1c, 2, 3) ran as a single sequential deep-read pass against the live tree at `3072e89`, not
a true parallel fan-out. Disclosed per the fan-out disclosure requirement. A second external
adversarial verifier was instructed to run in parallel in a separate session on the two new
guards — this contract was produced independently, without reading that verifier's output; see
Cross-Check Note.

**TL;DR:** No FAILs. All 6 cycle-0 CONCERNs are independently confirmed resolved by supplement
cycle 1 — every claim in S1–S5 was re-derived from the live source (not taken on the plan's word),
including the two brand-new guard sites, the rollback fix, the KG-A1 anchor-ordering claim, and
the `email_bidx` nullability claim. This cycle surfaces 3 new, smaller findings, none of which
require re-scoping: (1) the manual-Identify 422's "generic message avoids an oracle" reasoning is
overclaimed — verified there is no *other* business-logic 422 on that specific route today, so the
bare 422 status itself (regardless of message text) is a coarse "this email is suppressed
somewhere" signal for any authenticated site owner; recommend disclosing as a Known-Gap rather
than asserting the message text solves it. (2) The Section 3 test guidance doesn't distinguish the
single-row `.scalar_one_or_none()` mock shape (used by the existing `_save_identified`/manual-
Identify guard tests) from the multi-row `.scalars().all()` shape the new bulk CSV-import
pre-filter test needs — applying the wrong shape risks reproducing the exact "backwards mock"
defect class this same cycle already fixed once (F4/S4). (3) `contact_importer.py`'s new imports
(`email_hash`, `SuppressionEntry`, `GRAPH_WRITE_BLOCKING_SCOPES`, `settings`) aren't listed in
item 4b — minor/mechanical, no circular-import risk found. Recommend one more light supplement
cycle, not a return to INNOVATE.

**Live-drift re-check (independent):** `devjulley` has moved again since supplement cycle 1 — the
identity-coop workstream is now **committed** at `3072e89` ("entry gate cleared"), and the
worktree carries a further uncommitted diff to `identity_resolver.py` (the coop's two-line hook at
the tail of `resolve()` plus `_upsert_beam_identity`'s `None`→`bool` return-type change). Read the
diff directly (`git diff apps/api/services/identity_resolver.py`): it touches lines ~1249–1332,
strictly after Track A's guard-insertion anchor at line 1101 and Track A's `_save_identified`
anchor at line 1055. **Re-confirms the plan's own LIVE DRIFT NOTICE: no hunk conflict.** Also
newly verified: identity-coop's `maybe_record_contribution` explicitly does **not** re-check
suppression itself (documented as deliberate, "D-B" in `identity_coop.py`) — it only fires when
`_upsert_beam_identity` reports `wrote_graph=True`, i.e. only after the *existing* graph guard
already passed. Track A's new `_save_identified` guard sits upstream of the `_upsert_beam_identity`
call (same function body, guard returns at ~1101, the coop hook is at ~1252–1256) — so a suppressed
email never reaches the coop hook either. This is incidentally more protective, not a conflict.

---

### Layer 1 dimensions

| Layer 1 dimensions | Status |
|---|---|
| Infra fit | PASS |
| Test coverage | CONCERN |
| Breaking changes | PASS |
| Security surface | CONCERN |

### Layer 2 sections

| Layer 2 sections | Status |
|---|---|
| Section 1 — The guard (AC-5) | PASS |
| Section 1b — Two unguarded front doors (S1) | CONCERN |
| Section 1c — Batch-survival rollback fix (S2) | PASS |
| Section 2 — Audit lookup extension (AC-4) | PASS |
| Section 3 — Tests | CONCERN |

**Totals: 0 FAILs / 3 CONCERNs / 6 PASSes**

**→ Net Gate: CONDITIONAL**

---

### Cycle-0 items re-verified this cycle (all confirmed resolved — evidence, not trust)

| Item | Independent re-verification |
|---|---|
| S1 (guard extension) | Read `routers/visitors.py:1073-1158` and `contact_importer.py:140-223` in full. Confirmed: `manual_identify_visitor`'s guard-insertion point (after the 404 check at :1093, before the `# Upsert identified visitor` comment at :1095) sits before BOTH the create branch (:1110) and the update branch (:1104) — covers both as claimed. Confirmed `email_hash()` (`pii_crypto.py:66`) is a pure sync function usable in a dict comprehension. Confirmed `uq_suppression_hash_scope` (`models/suppression.py:33`) has `email_hash` as its leading unique-index column, so the bulk `.in_()` lookup is genuinely an index lookup, not a scan. |
| S2 (rollback fix) | Read `resolution_runner.py:158-183` — confirmed the bare `except Exception as e:` at :182 has no `await db.rollback()`. Read `agent_company_resolution.py:145-162` — confirmed the sibling pattern's rollback-then-log shape is real and matches what item 4e specifies. |
| S3 (KG-A1 rewrite) | Read `_save_identified` end-to-end (`identity_resolver.py:1055-1264`). Confirmed the anchor comment `"Paid person-graphs: reject obvious name"` sits at :1101, strictly before the email-dedup `canonical` block at :1117-1144. The guard, inserted immediately above :1101 per item 2, therefore does dominate the merge path — KG-A1's rewritten text is accurate. |
| S4 (mock target rule) | Read `tests/unit/test_graph_erasure.py:105-161` (`test_t_u1`, `test_t_u2`) — confirmed both mock `db.execute` via `_scalar_result(...)` and let the real `is_email_suppressed_any` run; neither mocks the helper directly. Confirmed the local-import convention (`_upsert_beam_identity`'s guard imports `is_email_suppressed_any` locally at line ~1281) is real and current. The origin-patch guidance (`apps.api.services.suppression.is_email_suppressed_any`) is correctly targeted. |
| S5 (`email_bidx` lower-bound disclosure) | Confirmed `IdentifiedVisitor.email_bidx` (`models/visitor.py:227`) and `VisitorEmail.email_bidx` (`models/visitor_email.py:68`) are both `nullable=True`. Confirmed both models are already imported at `graph_erasure.py:62-63`. The LOWER BOUND caveat is correctly scoped to the new read path only (the write guard re-hashes plaintext and never touches `email_bidx` — unaffected). |

---

### Findings (cycle 2 — new this pass; cycle-0 F1–F8 all resolved, not repeated)

| # | Finding | Severity | Class | Proposed fix |
|---|---|---|---|---|
| F9 | Manual-Identify's oracle mitigation is weaker than the plan's own G3/4a reasoning claims. Verified via `grep -n "422\|HTTPException" apps/api/routers/visitors.py`: **zero** other `HTTPException` with status 422 exist anywhere on `manual_identify_visitor` today — no other business-logic rejection on this route currently returns 422. The plan's item 4a rationale ("422 = 'we won't accept this value', which is already the shape used for validation rejects on this surface") is true of the *broader* API (`feature_requests.py`, `sites.py`, `outcomes.py` all use generic-message 422s) but **not** of this specific route — so a bare 422 status code, independent of the message text, functions as a reliable binary "this email is suppressed somewhere in the platform" signal for any authenticated site owner with access to that site (auth via `get_current_user` + `_verify_site_access`, so not anonymous, but still tenant-reachable per the plan's own definition). This doesn't invalidate the design choice — a silent fake-200 would be worse (creates a UI/DB inconsistency the operator would trust) — but the current framing ("does not become an existence oracle") overclaims what the generic message alone achieves. | CONCERN | documentable gap (disclosure, not a code defect) | Add a new Known Gap (e.g. KG-A7): "The manual-Identify 422 is a coarse existence oracle — it reveals that *some* suppression scope (`erased`/`do_not_process`/`all`) matches the submitted email, to any site owner with access to that site, though it never confirms which scope or that the person was specifically *erased*. Not eliminable within Track A's scope without a worse alternative (silent fake-success)." No code change required — this is a plan-text correction to item 4a's rationale plus the new Known-Gap row. |
| F10 | Section 3 item 8's per-case guidance says to use "the db.execute pattern" (i.e. `test_t_u1`/`test_t_u2`'s `_scalar_result(...)` shape, which mocks a single-row `scalar_one_or_none()` result) uniformly, but does not distinguish it from the shape `test_contact_import_skips_suppressed_row` actually needs. That test exercises the NEW bulk pre-filter (item 4b), which issues `select(SuppressionEntry.email_hash).where(SuppressionEntry.email_hash.in_(hashes), ...)` — a **multi-row** query that must be consumed via `.scalars().all()` (mirroring the existing bulk `already`-dedup query at `contact_importer.py:164-173`, which already uses `.scalars().all()`), not `.scalar_one_or_none()`. Applying the single-row `_scalar_result` helper to this test would either raise `AttributeError` (no `.scalars()` configured on the mock) or, if patched loosely, silently fail to model the real multi-row query — reproducing the exact "backwards mock, passes while proving nothing" defect class F4/S4 already fixed once in this same cycle, on a different test. | CONCERN | fixable defect (test design) | Add one clarifying sentence to item 8's `test_contact_import_skips_suppressed_row` case: "Mock `db.execute` to return a result whose `.scalars().all()` yields the suppressed row's hash (list-shaped, mirroring the existing `already`-dedup mock shape), not the single-row `_scalar_result(...)` helper used by the other cases — the bulk pre-filter query returns a set of matched hashes, not a boolean." |
| F11 | `apps/api/services/contact_importer.py` currently imports none of `email_hash` (`pii_crypto`), `SuppressionEntry` (`models/suppression`), `GRAPH_WRITE_BLOCKING_SCOPES` (`graph_erasure`), or `settings` (`config`) — confirmed via `grep -n "^from\|^import" apps/api/services/contact_importer.py`. Item 4b does not explicitly list these as new imports to add. No circular-import risk found (`graph_erasure.py` does not import `contact_importer.py` or vice versa — verified by grep in both directions). | CONCERN | fixable defect (mechanical completeness, small effort) | Add one line to item 4b: "Add the four new imports this guard needs: `email_hash` from `pii_crypto`, `SuppressionEntry` from `models.suppression`, `GRAPH_WRITE_BLOCKING_SCOPES` from `graph_erasure`, `settings` from `config` — none currently present in this file, no circular-import risk." |
| F12 | Minor observation, not a gap — no action needed. `test_guard_uses_email_hash_scopes_only`'s "no fingerprint kwarg" assertion is structurally close to vacuous: `is_email_suppressed_any`'s fixed 3-positional-arg signature (`db, email, scopes`) cannot accept a fingerprint kwarg at all, so this half of the assertion can never meaningfully fail. The other half of the same test (asserting `scopes == GRAPH_WRITE_BLOCKING_SCOPES`) is genuinely falsifiable and is the part doing real work. | ✅ PASS (noted, not blocking) | — | None required. Flagging only so a future reader doesn't over-read this test's coverage of G1. |
| F13 | Regression re-check: identity-coop's newest commit (`3072e89`) does not add its own suppression guard to `_save_identified`, and its `maybe_record_contribution` hook only fires after `_upsert_beam_identity` already reports a real write — which Track A's new `_save_identified` guard would prevent from being reached at all for a suppressed email (guard fires at ~1101, the coop hook is at ~1252-1256, same function, later). No merge required, no conflict, extra protection is a side effect not a regression. | ✅ PASS | — | None required. |

---

### Cross-Check Note

Per the task's disclosure instruction, an external adversarial verifier was to run in parallel in a
separate session focused on the two new guards (Section 1b, S1). This contract was produced
independently — no Agent tool grant in this session, so I could not spawn or read that verifier's
output myself. The orchestrator should diff this contract's F9/F10/F11 against the verifier's
findings before resolving V5; agreement on the manual-Identify oracle framing (F9) or the bulk
mock-shape gap (F10) would be a strong signal to prioritize those in the next supplement cycle,
disagreement is itself a finding per the task's own framing.

---

### Test gates (5-column)

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-5 | New tenant write blocked after erasure at `_save_identified` | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_graph_erasure_flow.py -m integration -q -k test_new_tenant_write_blocked_after_erasure` | B |
| AC-5 (unit) | Guard code-shape: blocks/proceeds/kill-switch/scopes-only/no-PII-log | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_graph_erasure.py -m unit -q` | B |
| AC-5 (S1/4a) | Manual-Identify front door blocked, generic 422, zero rows | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_graph_erasure_flow.py -m integration -q -k test_manual_identify_endpoint_blocked_after_erasure` | B |
| AC-5 (S1/4b) | CSV-import front door: per-row skip, generic rejected reason, rest imports | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_graph_erasure_flow.py -m integration -q -k test_contact_import_skips_erased_row` | B — see F10: unit-tier sibling test needs the mock-shape correction before it can be trusted |
| S3 | Dedup/merge path blocked under an active suppression tombstone; pre-existing row untouched | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_graph_erasure_flow.py -m integration -q -k test_dedup_merge_blocked_for_suppressed_email` | B |
| S2/4f | Shared-session batch survives one visitor's `resolve()` exception | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_graph_erasure_flow.py -m integration -q -k test_batch_survives_one_resolver_exception` | B |
| AC-4 | Audit lookup reports correct tenant holders + count (documented LOWER BOUND) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_graph_erasure_flow.py -m integration -q -k test_audit_lookup_reports_tenant_holders` | B |
| G1 | Fingerprint branch never joins tenant rows | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_graph_erasure_flow.py -m integration -q -k test_audit_lookup_fingerprint_branch_returns_no_holders` | B |
| AC-6 | `_cascade_suppress` / ordinary suppression path unaffected | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_graph_erasure_flow.py -m integration -q -k "test_cascade_suppress_unaffected or test_non_suppressed_resolution_still_writes"` | B |
| AC-6 (regression) | Full unit + integration lanes show no new red vs the 07-08-26 baseline (1203 / 518) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` and `.venv/bin/python3.11 -m pytest tests/ -m integration -q` | B |
| AC-9 | No PII in all four new paths' log lines | Agent-Probe | DEBUG log inspection over the integration flow, judged by the executing agent | B |
| F9 (this contract) | Manual-Identify 422 oracle scope disclosed as a Known-Gap, not asserted-solved | Hybrid | plan-text correction (KG-A7) — no test proves an absence-of-oracle claim; disclosure is the fix | C |
| F10 (this contract) | Bulk-importer unit test uses the correct multi-row mock shape | Hybrid | pending supplement — one clarifying sentence in item 8, then `test_contact_import_skips_suppressed_row` as specified | C |
| F11 (this contract) | `contact_importer.py` new imports present before EXECUTE writes code | Hybrid | pending supplement — one import line added to item 4b | C |

C-4 reconciliation: `strategy` above uses only Fully-Automated / Hybrid / Agent-Probe. Known-Gap is
never a strategy value — F9/F10/F11 are gap-resolution `C` (deferred to the next supplement
cycle), not a "Known-Gap" strategy.

What this coverage does NOT prove:
- No gate above was executed in this VALIDATE session (no code exists yet — Section 1/1b/1c/2 are
  still unimplemented at `3072e89`). This table remains a feasibility/coverage plan, matching cycle
  0's disclosure; Docker is proven working in this repo per the plan's own baseline run, so EXECUTE
  has no environment excuse to defer any Fully-Automated or Hybrid row.
- The manual-Identify and CSV-import Fully-Automated rows prove the guard blocks the write; they do
  NOT prove the oracle-scope claim in F9 either way (that is a disclosure fix, not a testable
  behavior — there is no code assertion that would meaningfully prove "this doesn't leak
  information", since any 422-vs-200 distinction observed on this route is a signal by definition).
- The AC-6 regression run proves no NEW red vs baseline; it does not re-verify the pre-existing
  1203/518 baseline counts themselves were correct (trusted from the plan's own prior gate run,
  re-trusted again this cycle — not independently re-run in this VALIDATE session).
- The Agent-Probe AC-9 log check is a single judged pass over one flow, not exhaustive coverage of
  every code path that could theoretically log — including the pre-existing
  `visitor_manually_identified` log line at `routers/visitors.py:1151`, which already truncates the
  email to 5 chars + `***` (pre-existing behavior, not introduced by Track A, out of scope for
  AC-9's "two new code paths" wording but worth an execute-agent awareness note).

Known Gaps (carried from plan, all confirmed accurate this cycle): KG-A1 (rewritten, confirmed
accurate — see re-verification table above), KG-A2, KG-A3, KG-A4, KG-A5 (resolved by S1, confirmed
resolved), KG-A6 (confirmed accurate — see S5 re-verification above).

New known gap proposed by this cycle, pending the user's/plan-agent's decision (not yet added to
the plan's Known Gaps table): KG-A7 (proposed, F9) — the manual-Identify 422 is a coarse existence
oracle for authenticated site owners; disclose rather than assert-solved.

Open gaps: F9 (oracle-disclosure text), F10 (bulk-mock-shape test correction), F11 (missing-imports
note). None are blocking by themselves; all three are addressable in one more light plan-supplement
cycle — none require re-scoping, re-anchoring, or a return to INNOVATE.

Gate: CONDITIONAL (0 FAILs, 3 CONCERNs — none accepted yet, pending supplement cycle 2)
Accepted by: PENDING
