---
phase: phase-4-contact-import
date: 2026-08-04
status: COMPLETE_WITH_GAPS
feature: visitors-identity
plan: process/features/visitors-identity/active/identity-program_03-08-26/phase-4-contact-import_PLAN_03-08-26.md
---

# Phase 4 — Contact Import: EXECUTE report

**TL;DR** — All 23 checklist items implemented. New unit coverage 21 tests, all green.
Full unfiltered unit lane: **1608 passed / 2 skipped / 3 failed**, where all 3 failures are
`tests/unit/test_site_limit.py` breakage caused by **uncommitted concurrent work in
`apps/api/routers/sites.py` that landed mid-session** — outside Phase 4's blast radius and
proven not-mine (see Test Gate Outcomes). Against a worktree without that concurrent edit the
lane was **1610 passed / 0 failed** (baseline 1589 → +21). Web typecheck clean. Migration
offline round-trip clean both directions. Not committed, not pushed, no live migration apply.

## What Was Done

**Step A — data model + migration**
- `apps/api/models/visitor.py`: new `Visitor.is_imported_contact` boolean (default False,
  `server_default="false"`, non-null) with an inline comment documenting that — unlike
  `is_agent_derived` — the resulting exclusion is CONDITIONAL, not permanent.
- New migration `apps/api/migrations/versions/c2f8a5d31e97_add_is_imported_contact.py`.
  Live `alembic heads` re-run at EXECUTE time (E1) returned `b1c9e7f24d83 (head)` — single
  head, no drift since VALIDATE — and that is the `down_revision`. Offline `--sql` validated
  in BOTH directions with an explicit rev range. **Never live-applied, never pushed.**

**Step B — import endpoint + service**
- New `apps/api/services/contact_importer.py`: CSV parse, defensive caps applied FIRST
  (`MAX_FILE_BYTES` 2 MB, `MAX_ROWS_SCANNED` 20,000 — the only body-size defense this route
  has, since `IngestBodySizeLimitMiddleware` guards `/api/v1/events/ingest` only), per-row
  email-format validation (E5/B1a), whole-file quota rejection at
  `MAX_IMPORTED_CONTACTS_PER_SITE = 5000` checked in the same transaction as the insert,
  phantom `Visitor` (`visitor_id = f"import:{contact_id}"`) + seeded `IdentifiedVisitor`
  (`identity_status="identified"`, `resolution_provider="contact_import"`,
  lowercase-normalized plaintext email), counts-only logging.
  `contact_id` is a fresh `uuid.uuid4()` minted BEFORE row creation (E3).
- New `apps/api/routers/contacts.py`: `POST /api/v1/sites/{site_id}/contacts/import`,
  `GET .../contacts`, `GET .../contacts/{visitor_id}`, `GET .../contacts-count`. All four
  gated by the shared `verify_site_access` dependency (404 not 403). Tokenized link derived
  on read via the existing `generate_bid()` — no new token scheme, no second stored copy of
  the PII. Registered in `main.py` under the `/api/v1/sites` prefix, deliberately on a
  `contacts` path segment distinct from `known-contacts`.
- `apps/api/services/identity_classification.py`: `"contact_import"` added to
  `PERSON_LEVEL_PROVIDERS` (B2a). Deliberately NOT added to `GRAPH_CANDIDATE_PROVIDERS`.
  `is_emailable_identity` keeps exactly 3 parameters — unchanged signature.

**Step C — merge-on-click (verification only, per the Merge Mechanism Decision)**
- Zero new code in `identity_resolver.py`, as specified. C1 proved by a targeted test that
  drives the real `_save_identified` against a seeded phantom: the click-derived row becomes
  `identity_status="merged"` with `canonical_visitor_id == <phantom's visitor_id>`, the
  phantom's row stays canonical, and no duplicate `IdentifiedVisitor` is inserted.
- C3 documented: **exact lowercase email is the ONLY match key in v1.** Fingerprint-based
  matching is out of scope (no precedent in `_save_identified`); a test asserts a matching
  fingerprint is not what drives the merge.

**Step D — metric exclusion (E6 red-first) + tests**
- `agent_visitor_filters.py::human_only_visitor_filter()` extended at the single choke point
  (not at the 9 call sites) with a correlated `EXISTS` subquery:
  `NOT (is_imported_contact AND total_pageviews == 0 AND NOT EXISTS(merged child))`, where
  the child match is `v2.canonical_visitor_id = visitors.visitor_id AND v2.site_id =
  visitors.site_id AND v2.identity_status = 'merged'`. The `site_id` correlation is an
  addition beyond the plan text (see Deviations).
- **E6 red-first was executed literally and in order:** D8 written first → 3 assertions RED
  against the original predicate → naive `total_pageviews==0`-only form implemented → the
  pointer-resolution assertion STILL RED (proving the plan-found self-contradiction is real,
  not theoretical) → EXISTS version implemented → green.

**Step E — frontend**
- New route `apps/web/src/app/dashboard/contacts/page.tsx` ("Imported Contacts"): upload
  form with cap/error surfacing, per-row rejection reasons, contact list with link status.
- New sidebar nav item "Imported Contacts" (top level, not nested under Connectors).
- Cross-link copy added to the existing Connectors → Import "Known contacts" block warning it
  does NOT create contacts and pointing at the new surface; the new page carries the mirror
  explainer. `api.ts` / `api-types.ts` gained the client methods and types.

## What Was Skipped or Deferred

- Live migration apply — explicit operator action per the umbrella hard-stop. Not run.
- Commit / push — explicitly out of scope for this session; worktree left dirty.
- Merged-visitor consumer awareness across the 7 downstream surfaces — pre-existing gap,
  out of blast radius, already tracked at
  `process/features/visitors-identity/backlog/merged-visitor-consumer-awareness_NOTE_04-08-26.md`.

## Test Gate Outcomes

| Gate | Command | Result |
|---|---|---|
| New importer unit tests | `pytest tests/unit/test_contact_importer.py -q` | 15 passed |
| D8 predicate regression | `pytest tests/unit/test_imported_contact_filter.py -q` | 4 passed (red-first proven) |
| C1/D6 merge-on-click | `pytest tests/unit/test_contact_import_merge.py -q` | 3 passed |
| Targeted regression | `pytest tests/unit -k "link_decorator or is_emailable or human_only_visitor_filter" -q` | passed |
| **Full unfiltered unit lane** | `pytest tests/unit -q` | **1608 passed / 2 skipped / 3 failed — all 3 external, see below** |
| Web typecheck | `cd apps/web && npx tsc --noEmit` | clean |
| Migration offline round-trip | `alembic upgrade b1c9e7f24d83:c2f8a5d31e97 --sql` + reverse | clean both directions |
| Integration lane | `pytest tests/integration/test_contact_import.py -q` | **Known-Gap — no Docker** (`which docker` → not found) |
| Live migration apply | — | **Known-Gap — operator action** |

**The 3 unit-lane failures are NOT from this phase.** All three are in
`tests/unit/test_site_limit.py` and fail at `apps/api/routers/sites.py:161` with
`TypeError: 'Mock' object does not support the asynchronous context manager protocol` — a new
`async with` added to `create_site` by concurrent, uncommitted pixel-verify work that landed
in this shared worktree mid-session (file mtime 12:12 today; `git show HEAD:apps/api/routers/sites.py`
contains none of it). Evidence it is not mine: the SAME full lane run earlier in this session,
with every Phase 4 code change already applied, was **1610 passed / 0 failed**; the 3 failures
appeared only after `sites.py` / `schemas/sites.py` / `pixel_verifier.py` / `config.py` /
`events.py` changed under the session. None of those five files is in Phase 4's blast radius
and none was edited by this agent.

## Plan Deviations

1. **`site_id` added to the EXISTS correlation** (within blast radius). The plan's predicate
   correlated only on `canonical_visitor_id`. `visitor_id` is unique per `(site_id,
   visitor_id)`, not globally, so a cross-tenant `visitor_id` collision could otherwise
   re-include a phantom on the wrong site's evidence. Adding `v2.site_id = visitors.site_id`
   is strictly narrowing and tenant-safe. No impact on the plan's stated semantics.
2. **`tests/unit/test_resolution_eligibility_floor.py` assertion narrowed** (test-breakage,
   within blast radius). `test_runner_uses_one_distinct_handoff_join` asserted a bare
   `"exists" not in sql`, whose real intent was "the HANDOFF correlated EXISTS was replaced by
   a join". The new phantom-pointer EXISTS is an unrelated, legitimate EXISTS. The assertion
   was narrowed to the handoff scope (`"exists" not in sql.split("agent_handoff_links")[0]`
   plus an explicit `"exists (select agent_handoff_links"` ban), preserving the original intent
   and keeping the join guarantee. Classification: **test-breakage**, not product-breakage.
3. **D8's unit-level assertions are structural** (compiled-SQL), not row-level. The row-level
   exclude→re-include proof requires a live Postgres (the ORM uses `UUID`/`JSONB`), so it is
   written in `tests/integration/test_contact_import.py::TestPhantomExclusionPredicate` and
   inherits the phase's documented no-Docker known-gap. The structural form is still
   non-vacuous — it was RED against both the original and the naive predicate.
4. **Tracking link derived on read, not persisted.** The plan said "generate a tokenized link
   per contact" without naming storage. The token is a pure function of the email, so storing
   it would duplicate PII for no benefit. Same `generate_bid()` mechanism either way.

### Incident note (no damage, disclosed for audit)

While bisecting the `test_site_limit` failures I ran `git stash push -- <paths>` with a
pathspec that did not match (the new router was untracked). The push created nothing, and the
follow-up `git stash pop` therefore targeted a **pre-existing user stash**
(`stash@{0}: pre-commit-local-work-after-gumroad-deploy`). The pop **aborted** — tracked-file
merge refused ("local changes would be overwritten"), untracked restore refused ("already
exists") — and git kept the stash entry. Verified after the fact: `git stash list` still shows
all 10 entries with `stash@{0}` intact, and no file changed as a result. No further git
state-changing commands were used for the rest of the session.

## Test Infra Gaps Found

- No Docker in this sandbox: the integration lane (AC9 boundary at 5,000/5,001, AC18
  cross-tenant, D8 behavioural) is written but unrun. Pre-named known-gap, matches Phase 1/2/3.
- A stray local Redis on :6379 is up; it did not affect this phase's tests.
- Shared-worktree concurrency is actively breaking the unit lane (see above) — any EVL re-run
  should expect the same 3 `test_site_limit` failures until that concurrent work settles.

## Closeout Packet

- Selected plan: `process/features/visitors-identity/active/identity-program_03-08-26/phase-4-contact-import_PLAN_03-08-26.md`
- Finished: all of Steps A–E; Phase Loop Progress step 5 ticked.
- Verified: unit + typecheck + offline migration round-trip.
- Unverified: integration lane, live migration apply (both known-gaps).
- Remaining: EVL confirmation run, then UPDATE PROCESS.
- Classification: **Keep in active** — EVL not yet run; 2 environment known-gaps open.

## Forward Preview

**Test Infra Found** — no new runner; unit lane is the gate. Integration lane needs Docker.
**Blast Radius Changes** — added `apps/api/routers/contacts.py`,
`apps/api/services/contact_importer.py`, `apps/web/src/app/dashboard/contacts/page.tsx`, and
the migration; `agent_visitor_filters.py` now carries a second, conditional exclusion axis that
any future predicate work must preserve.
**Commands to Stay Green** — `.venv/bin/python3.11 -m pytest tests/unit -q` and
`cd apps/web && npx tsc --noEmit`.
**Dependency Changes** — none. No new packages.
**For Phase 5** — confirmed: an imported contact's later click yields outcome (b),
`identity_status == "merged"` + `canonical_visitor_id` → the phantom's `"identified"` row.
Promotion-sweep logic reading `is_verified_identity()` must follow the pointer, not read the
click-derived row's own status.

## Follow-up Stubs Created

None new. The one open cross-cutting item was already registered by VALIDATE at
`process/features/visitors-identity/backlog/merged-visitor-consumer-awareness_NOTE_04-08-26.md`.

## CONTEXT_PARTIAL

None.
