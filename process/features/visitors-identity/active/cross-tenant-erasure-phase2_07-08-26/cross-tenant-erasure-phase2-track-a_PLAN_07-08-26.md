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
**Status**: ACTIVE — VALIDATE run, Gate: CONDITIONAL (cycle 0), supplement pending
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

Classified **SIMPLE**. Why: 2 production files touched, ~35 net lines, no new module, no schema/migration, no new endpoint,
no external call, no flag surface beyond one optional kill-switch. COMPLEX would be inflation — this
is one guard structurally identical to an existing, live, reviewed one plus a read-only query
extension.

---

## Scope

| In (Track A) | Out (Track B — deferred) |
|---|---|
| AC-5 — standing write-time guard blocking a *new* `IdentifiedVisitor` for an erased person at any tenant | AC-1/2/3/7/8 — the cascade that **mutates other tenants' existing rows** |
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

4. Do **not** guard the email-dedup `canonical` early-return path above the insert. That path returns
   a **pre-existing** row and writes no new identity — mutating or refusing it would be a Track B
   decision (touching an existing row). Add an inline comment saying exactly this so a later reader
   does not "complete" the guard into Track B territory. **Record as Known-Gap KG-A1** (below).

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
   (`tests/conftest.py:4`: "Unit tests: no DB, no network — use mocks"):
   - `test_save_identified_blocks_when_suppressed` — mock `is_email_suppressed_any` → `True`,
     assert `_save_identified` returns `None` and `db.add` was never called.
   - `test_save_identified_proceeds_when_not_suppressed` — mock → `False`, assert `db.add` called.
   - `test_save_identified_guard_respects_kill_switch` — flag `False`, mock → `True`, assert the
     suppression helper is **not awaited** and the write proceeds.
   - `test_guard_uses_email_hash_scopes_only` — assert the helper is called with
     `GRAPH_WRITE_BLOCKING_SCOPES` and that no `fingerprint` kwarg is passed anywhere (G1).
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
| DEBUG log inspection of the two new paths | Agent-Probe | **AC-9** (no PII in logs) |
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
  email. It does not raise to the caller, does not abort the ingest request, and leaves no partial row.
- **Rollback:** set `IDENTITY_WRITE_ERASURE_GUARD_ENABLED=false` in the Railway env and restart —
  no redeploy, no migration reversal, no data cleanup. Code rollback is a plain revert; nothing is
  persisted that a revert would orphan.
- **Mock mode:** unaffected. The guard makes only a local DB query; no external call is added, so
  `MOCK_EXTERNAL_APIS=true` needs no new branch.

---

## Known Gaps (Track A)

| ID | Gap | Disposition |
|---|---|---|
| KG-A1 | The email-dedup `canonical` early-return path in `_save_identified` is not guarded — if an erased person already has a row at that same site under a different visitor_id, the merge still links to it. | **By design.** Touching that pre-existing row is Track B (mutating an existing row). Inline comment added at the site. |
| KG-A2 | Name-only identities (no email) cannot be guarded — there is no hash key to match on. | Accepted. Matches Phase 1's posture; the erasure model is email-hash-keyed throughout. |
| KG-A3 | Track A blocks *new* writes but leaves every existing cross-tenant row live — the actual KG-6 harm (Site B keeps emailing) is untouched. | **This is Track B's entire purpose.** Track A is the standing guard half, shipped early because it is unblocked. Must be stated plainly in any compliance claim: Track A alone does not close KG-6. |
| KG-A4 | `EnrichmentProfile` not covered (SPEC OQ6). | Deferred with Track B. |

---

## Acceptance Criteria

| # | Criterion | proven by | strategy |
|---|---|---|---|
| AC-5 | A tenant that independently discovers an erased person's email for the first time cannot create an `IdentifiedVisitor` row for them — the write is refused at `_save_identified`, at any site, indefinitely. | `test_new_tenant_write_blocked_after_erasure` (integration) + the 5 unit guard cases | Fully-Automated |
| AC-4 | Given an erased person's email, a platform operator can list which tenants still hold a matching `IdentifiedVisitor`/`VisitorEmail` row, and how many — without ad-hoc SQL. | `test_audit_lookup_reports_tenant_holders` (integration) | Fully-Automated |
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

(none identified yet)

---

## Resume and Execution Handoff

1. **Selected plan file:** `process/features/visitors-identity/active/cross-tenant-erasure-phase2_07-08-26/cross-tenant-erasure-phase2-track-a_PLAN_07-08-26.md`
2. **Last completed phase/step:** PLAN written. No implementation started. Working tree clean at `443ad5e`.
3. **Validate-contract status:** pending — vc-validate-agent has not run.
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

Parallel strategy: sequential
Rationale: No Agent tool grant in this session — Layer 1 (4 dimensions) and Layer 2 (2 sections)
ran as a single sequential deep-read pass against the live tree, not a true parallel fan-out.
Disclosed per the fan-out disclosure requirement. An external adversarial verifier ran in parallel
in a separate session — see Cross-Check note at the end of this contract.

**TL;DR:** No FAILs. Four CONCERNs, all fixable without re-scoping the plan. The most material one:
the guard as scoped only covers `_save_identified` — two other live write paths
(`routers/visitors.py` manual "Identify", and `contact_importer.py` CSV import) construct
`IdentifiedVisitor` rows with **zero** suppression check and are not touched by this plan, so AC-5's
"at any site, indefinitely" claim is currently overclaimed. Also found: an internal contradiction
between the plan's guard-placement instruction and its own KG-A1 narrative (fixable — see below),
and a mock-target risk in the proposed unit tests that matches the exact defect class the sibling
erasure plan burned cycles on. Recommend one supplement cycle to resolve, not a return to INNOVATE.

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
| Section 1 — The guard (AC-5) | CONCERN |
| Section 2 — Audit lookup extension (AC-4) | PASS |
| Section 3 — Tests | CONCERN |

**Totals: 0 FAILs / 4 CONCERNs / 2 PASSes**

**→ Net Gate: CONDITIONAL**

---

### Findings

| # | Finding | Severity | Class | Proposed fix |
|---|---|---|---|---|
| F1 | `_save_identified`'s new guard does not dominate all `IdentifiedVisitor` creation paths. Two other live code paths construct a new `IdentifiedVisitor` row with **zero** suppression check, entirely independent of `_save_identified`: (a) `apps/api/routers/visitors.py:1110` inside `manual_identify_visitor` — the dashboard's manual "Identify" action, a site owner typing in an email; (b) `apps/api/services/contact_importer.py:195` — bulk CSV contact import. Both are legitimate "a tenant discovers/enters an erased person's email for the first time" events, structurally identical in kind to the paid-provider discovery this plan closes. AC-5's stated guarantee ("the write is refused at `_save_identified`, at any site, indefinitely") is therefore materially incomplete as written — an operator can silently re-add or bulk-import an erased person via either path today, and Known Gaps KG-A1–KG-A4 do not mention this. | CONCERN | fixable defect (scope gap) | Either (a) extend Touchpoints to add the same `is_email_suppressed_any(db, email, GRAPH_WRITE_BLOCKING_SCOPES)` guard at both sites (small, same pattern, ~10 lines total), or (b) explicitly descope and correct AC-5's wording to name the exact boundary ("...refused at the automated resolution path; manual Identify and CSV import are out of scope, tracked as KG-A5") plus add KG-A5 to Known Gaps. Do not ship AC-5 as currently worded without one of these two fixes — the current wording is a compliance overclaim. |
| F2 | Internal contradiction between the guard's specified insertion point and the plan's own KG-A1 narrative. Checklist item 2 places the guard strictly **before** the name-email consistency check (line 1101), which is itself **before** the email-dedup `canonical` early-return (lines 1117–1144). Given that ordering, the guard's early `return None` for a suppressed email makes the dedup/merge branch **unreachable** whenever the guard fires — so KG-A1's claimed gap ("if an erased person already has a row at that same site under a different visitor_id, the merge still links to it") does **not** actually occur with the guard positioned exactly as item 2 instructs. Verified by reading the live function body end to end (`apps/api/services/identity_resolver.py:1055-1262`). Either the anchor is wrong (guard should sit between the dedup check and the `IdentifiedVisitor(...)` construction at line 1150, which would make KG-A1 true as written) or KG-A1's text and the item-4 inline-comment content are wrong (the guard incidentally also blocks the merge-to-existing-row path, which is arguably *more* protective, not less — but the code comment as specified would describe behavior the code doesn't actually have). No test in Section 3 exercises the dedup/merge-under-suppression scenario, so this contradiction is not caught by the proposed test suite either way. | CONCERN | fixable defect (plan-text/placement) | Pick one: (a) confirm the guard's anchor is intentionally before the dedup check (item 2, as literally written) and correct KG-A1 + the item-4 inline comment to state accurately that the merge path is also incidentally blocked; or (b) move the guard's anchor to immediately before line 1150 (`identified = IdentifiedVisitor(...)`) so it sits after the dedup check, making KG-A1 true as currently described. Either way, add one integration test exercising the dedup/merge scenario under an active suppression tombstone so the chosen behavior is locked in, not just asserted in prose. |
| F3 | Rollout section overclaims fail-closed behavior for one real caller. "An in-flight resolution that trips the guard... does not raise to the caller, does not abort the ingest request" is true for the synchronous `POST /ingest` path (resolution never runs inline there) but not accurate for every caller of `resolve()`. `apps/api/tasks/resolution_tasks.py:_process_site` (the Celery-beat sweep, line 130 `identified = await resolver.resolve(visitor)`) has **no** try/except around that call inside its `for visitor in visitors:` loop — an uncaught exception from the new guard (or the pre-existing, structurally identical `_upsert_beam_identity` guard, which has the same no-try/except shape today) would abort resolution of the *remaining* visitors in that batch (up to 50), not just the current one. By contrast, `apps/api/services/resolution_runner.py` line 171 *does* wrap its `resolver.resolve(...)` call in a per-visitor try/except, correctly containing the blast radius to one visitor. This is a **pre-existing, already-accepted** risk pattern (identical in shape to the live `_upsert_beam_identity` guard — not new to Track A), so it is not a reason to change the no-try/except design. It is a reason to correct the Rollout section's claim so a future reader doesn't believe the batch-abort case has been ruled out. | CONCERN | documentable gap (text correction) | Correct the Rollout / Rollback Posture wording: "does not abort the ingest request" is true; add a sentence naming that `resolution_tasks.py`'s Celery-beat per-site sweep has no per-visitor try/except and so *can* abort the remainder of a batch on a DB hiccup — same accepted risk as the existing `_upsert_beam_identity` guard, not a new regression. Optional, not required for this plan: add a per-visitor try/except in `_process_site`'s loop as a separate, out-of-scope hardening item (do not fold into Track A's checklist — flag as a backlog note instead if pursued). |
| F4 | Mock-target risk in the proposed unit tests, matching the exact "backwards mock" defect class the sibling erasure plan burned cycles on (per plan header context: "8 wasted PVL cycles" on gates that could not prove what they claimed). Checklist item 8 describes 3 tests that "mock `is_email_suppressed_any`" directly. Since the plan's own item 2 specifies the import as **local** (`from apps.api.services.suppression import is_email_suppressed_any` inside `_save_identified`'s body — mirroring `_upsert_beam_identity`'s existing pattern), a `mock.patch`/`monkeypatch` targeting `apps.api.services.identity_resolver.is_email_suppressed_any` would not intercept the real call (that name is never a persistent module attribute of `identity_resolver`) — the patch must target the **origin**, `apps.api.services.suppression.is_email_suppressed_any`. Notably, the existing sibling tests in the SAME file for `_upsert_beam_identity` (`test_t_u1_do_not_resolve_visitor_writes_no_graph_row`, `test_t_u2_erased_tombstone_blocks_graph_write` — both read in full) do **not** mock the helper at all; they mock `db.execute` and let the real `is_email_suppressed_any` run against the mocked db, which is more robust and avoids this exact class of mistake. | CONCERN | fixable defect (test design) | Follow the file's own established pattern: mock `db.execute` (via `MagicMock()` + `_scalar_result(...)`, matching `test_t_u1`/`test_t_u2`) and let the real `is_email_suppressed_any` execute, rather than mocking the helper function itself, wherever the test only needs a True/False suppression outcome. For the one test that genuinely needs to assert *call arguments* (`test_guard_uses_email_hash_scopes_only`, which must confirm `GRAPH_WRITE_BLOCKING_SCOPES` was passed and no `fingerprint` kwarg exists anywhere), if the helper itself must be mocked, patch `apps.api.services.suppression.is_email_suppressed_any` (the origin), never the `identity_resolver` module path, and pair the mock call-count assertion with an observable side-effect assertion (`db.add` call count / return value) so a silently-mistargeted patch cannot produce a false pass. |
| F5 | Anchor/mechanical-feasibility check on all 7 Touchpoints entries. | ✅ PASS | — | All `git grep` anchors re-verified byte-exact against `443ad5e`: `"async def _save_identified"` (identity_resolver.py:1055), `"Write-boundary erasure guard"` (1272), `"Paid person-graphs: reject obvious name"` (1101), `"async def lookup_graph_identity"` (graph_erasure.py:513), `"class GraphIdentityLookupOut"` (schemas/privacy.py:13), `"graph_identity_lookup_enabled"` (config.py:662). `GRAPH_WRITE_BLOCKING_SCOPES` and `is_email_suppressed_any` signatures confirmed exactly as the plan states. Both `IdentifiedVisitor`/`VisitorEmail` confirmed already imported at `graph_erasure.py` module top. Sole caller of `lookup_graph_identity()` confirmed as `routers/privacy.py`. `email_hash,scope` confirmed as a real composite unique index (`uq_suppression_hash_scope`), so the "one indexed lookup" no-op claim (item 3 of the validate task) holds. |
| F6 | No-migration claim. | ✅ PASS | — | Confirmed by content analysis: no `mapped_column` addition anywhere in Touchpoints, only a config bool and two additive Pydantic response fields. Consistent with "no migration" — live `alembic heads` re-derivation was not attempted (no `.venv`/Docker in this session), matching the plan's own stated caveat; this is a runtime condition, not a planning gap. |
| F7 | Compliance-claim honesty (task item 7). | ✅ PASS | — | KG-A3 and "Phase Completion Rules" state plainly that Track A alone does not close KG-6 (Site B keeps emailing from rows it already holds). No overclaiming text found elsewhere in the plan. |
| F8 | AC-4 existence-oracle surface (task item 4). | ✅ PASS | — | Both gates confirmed live in `routers/privacy.py`: `settings.graph_identity_lookup_enabled` (default `False` → 404) and `require_admin` dependency. The existing `contributing_site_ids` field on the SAME endpoint already reveals per-site existence for the shared-graph case — the new `tenant_holder_site_ids`/`tenant_holder_row_count` fields set no new precedent for the existence-oracle risk; they extend an already-accepted pattern on an already double-gated route. |

---

### Cross-Check Note

An external adversarial verifier ran in a separate session in parallel with this pass, per the task's
disclosure instruction ("agreement is signal, disagreement is a finding"). This contract was produced
independently, without reading that verifier's output. If the two disagree, treat the disagreement
itself as a signal worth a second look before accepting this contract's CONDITIONAL as final — the
orchestrator should diff both outputs before resolving V5.

---

### Test gates (5-column)

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-5 | New tenant write blocked after erasure at `_save_identified` | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_graph_erasure_flow.py -m integration -q -k test_new_tenant_write_blocked_after_erasure` | B |
| AC-5 (unit) | Guard code-shape: blocks/proceeds/kill-switch/scopes-only/no-PII-log | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_graph_erasure.py -m unit -q` | B |
| AC-4 | Audit lookup reports correct tenant holders + count | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_graph_erasure_flow.py -m integration -q -k test_audit_lookup_reports_tenant_holders` | B |
| G1 | Fingerprint branch never joins tenant rows | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_graph_erasure_flow.py -m integration -q -k test_audit_lookup_fingerprint_branch_returns_no_holders` | B |
| AC-6 | `_cascade_suppress` / ordinary suppression path unaffected | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_graph_erasure_flow.py -m integration -q -k "test_cascade_suppress_unaffected or test_non_suppressed_resolution_still_writes"` | B |
| AC-6 (regression) | Full unit + integration lanes show no new red vs the 07-08-26 baseline (1203 / 518) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` and `.venv/bin/python3.11 -m pytest tests/ -m integration -q` | B |
| AC-9 | No PII in the two new code paths' log lines | Agent-Probe | DEBUG log inspection over the integration flow, judged by the executing agent | B |
| F1 (this contract) | Guard covers manual-Identify and CSV-import write paths | Hybrid | pending supplement decision — extend guard (new Fully-Automated tests) or document as KG-A5 | C |
| F2 (this contract) | Dedup/merge path behavior under an active suppression tombstone is locked in and matches the stated Known-Gap | Fully-Automated | new integration test `test_dedup_merge_blocked_for_suppressed_email` (does not yet exist) | C |

C-4 reconciliation: `strategy` above uses only Fully-Automated / Hybrid / Agent-Probe. Known-Gap is
never a strategy value — F1/F2 are gap-resolution `C` (deferred to the supplement cycle), not a
"Known-Gap" strategy.

What this coverage does NOT prove:
- The Fully-Automated AC-5 test proves the `_save_identified` path only — it does NOT prove anything
  about the manual-Identify or CSV-import paths (F1), since neither is currently touched by this plan.
- The AC-6 regression run proves no NEW red vs baseline; it does not re-verify the pre-existing
  1203/518 baseline counts themselves were correct (trusted from the plan's own prior gate run).
- The Agent-Probe AC-9 log check is a single judged pass over one flow, not exhaustive coverage of
  every code path that could theoretically log.
- Docker was unavailable in this VALIDATE session (`docker` command not found) — no gate above was
  actually executed here; this table is a feasibility/coverage plan, not a run confirmation. EXECUTE
  must run each Fully-Automated/Hybrid row and the Agent-Probe judgment before claiming CODE DONE.

Known Gaps (carried from plan, unchanged): KG-A1 (needs correction per F2 above), KG-A2, KG-A3
(Track A does not close KG-6 by itself — stated plainly, verified accurate), KG-A4.

New known gap surfaced by this VALIDATE pass, pending supplement resolution: KG-A5 (proposed) —
manual-Identify (`routers/visitors.py`) and CSV-import (`contact_importer.py`) write paths are not
covered by the new guard (F1). Not yet added to the plan's Known Gaps table — added here as a
placeholder pending the user's/plan-agent's F1 fix decision.

Open gaps: F1 (guard coverage — needs a decision: extend scope vs. document+correct AC-5), F2 (KG-A1
text/placement contradiction), F3 (Rollout wording correction), F4 (unit test mock-target guidance).
None are blocking by themselves; all four are addressable in a single plan-supplement cycle.

Gate: CONDITIONAL (0 FAILs, 4 CONCERNs — none accepted yet, pending supplement)
Accepted by: PENDING

