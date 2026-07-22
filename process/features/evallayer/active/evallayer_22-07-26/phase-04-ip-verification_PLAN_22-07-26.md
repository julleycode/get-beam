---
name: plan:evallayer-phase-04-ip-verification
description: "EvalLayer — Phase 04: IP-range verification + confidence field (OpenAI/Perplexity published CIDR ranges; Anthropic stays UA-only structurally; mock path)"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-04
---

# Phase 04 — IP Verification

**Program:** evallayer
**Umbrella plan:** process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md
**Phase status:** VALIDATED (PVL PASS — ready for EXECUTE)
**Report destination:** process/features/evallayer/active/evallayer_22-07-26/phase-04-ip-verification_REPORT_22-07-26.md

---

## Purpose

Upgrade agent-visit confidence from `ua-only` to `ip-verified` by cross-checking a small,
checked-in static set of published vendor CIDR ranges (OpenAI, Perplexity) against the
visitor IP, on a periodic best-effort sweep — never on the ingest hot path. Anthropic
(Claude) publishes no IP ranges and must NEVER exceed `ua-only` confidence, structurally
(no dataset entry exists for it — not an incidental omission). Ships with a
`MOCK_EXTERNAL_APIS=true` deterministic fixture path (SPEC AC14).

rDNS-based verification (`rdns-verified`) and live scheduled range-refresh are explicitly
OUT OF SCOPE for this phase — see the two backlog NOTE files linked in Resolved Design
Decisions below.

---

## Entry Gate

- Phase 2 exit gate passed (agent visits are classified and persisted with `verification_method`).
- Parallel-safe with Phase 3 — disjoint blast radius (verification service vs. read API/dashboard).

---

## Resolved Design Decisions (locked — encode exactly, do not redesign at EXECUTE)

1. **New pure-logic module, not an extension of `company_resolver.py`.** IP verification here
   is a pure in-memory CIDR-membership check (no I/O, no cache, no external call) — simpler
   than `company_resolver.py`'s async/cached datacenter-classification pattern. Only the
   fail-open *convention* is shared, not the caching machinery.
2. **Static JSON dataset, not live-fetched.** Checked into
   `apps/api/data/agent_ip_ranges/{vendor}.json`, shape `{"vendor": "openai", "ranges": ["CIDR", ...]}`.
   A small representative set of real published ranges is sufficient — exhaustiveness and
   staleness handling belong to the `phase-04-live-range-refresh` backlog item.
3. **No `anthropic.json`.** The absence of a dataset entry IS the structural ceiling — `verify_ip`
   returns `None` for any vendor with no loaded ranges, which naturally covers Anthropic without
   a vendor-name special case.
4. **Sweep, not per-request.** A periodic APScheduler job (`_agent_verification_sweep_job`,
   `interval`, mirroring `_resolution_sweep_job`'s registration shape) upgrades eligible rows
   asynchronously, after the fact — never adds latency to `routers/events.py`'s ingest hot path
   (SPEC Resolved Open Question 2).
5. **Sweep query is bounded and cheap:** `agent_visits WHERE verification_method = 'ua-only' AND
   vendor IN ('openai', 'perplexity') AND last_seen_at > now() - INTERVAL '7 days' ORDER BY
   last_seen_at DESC LIMIT 500` per run. Rationale: 7-day window keeps the sweep scoped to
   recently-active rows (older stale rows are low-value to re-check every cycle); 500-row cap
   keeps each periodic run cheap and bounded regardless of table growth; `vendor IN (...)`
   pre-filters to only the two vendors with a dataset (skips the Anthropic no-op scan entirely).
6. **Persistence key: row `id` (UUID pk).** `upgrade_verification_method(db, id, method)` keys
   on the simple primary key, not the composite (site_id, vendor, ...) tuple — the sweep already
   has the row loaded by primary key from its query, so this is the simplest correct key.
   (Confirmed at VALIDATE: `AgentVisit` inherits `id: Mapped[uuid.UUID]` as its primary key from
   `apps/api/models/database.py`'s declarative `Base` — no explicit `id` column needed on the
   model itself; the key exists today.)
7. **Fail-open at 3 levels:** (a) `load_ip_ranges()` returns `{}` on any file-read/parse error
   (never raises); (b) `verify_ip()` returns `None` on any malformed ip/cidr input (never raises);
   (c) `run_verification_sweep()` wraps each row's upgrade in try/except so one bad row never
   aborts the sweep — matches `_resolution_sweep_job`'s per-item isolation convention.
8. **Config convention:** `agent_verification_sweep_interval_minutes: int = 15` in `config.py`,
   same shape as `resolution_sweep_interval_minutes: int = 30`.
9. **Logging is keys-only.** `upgrade_verification_method` logs `id`/`vendor`/`method` — never
   `ip_address` or other PII-adjacent fields, matching the Business Guardrails PII rule.
10. **Out of scope, tracked in backlog:**
    - `process/features/evallayer/backlog/phase-04b-rdns-verification_NOTE_22-07-26.md` — the
      `rdns-verified` tier (Forward-Confirmed rDNS, a live DNS round-trip; a separate mechanism
      from the CIDR check in this phase).
    - `process/features/evallayer/backlog/phase-04-live-range-refresh_NOTE_22-07-26.md` —
      scheduled fetch+diff of vendor-published range docs vs. the committed JSON, drift
      alerting, and adding new tracked vendors (Amazonbot, cohere-ai) beyond OpenAI/Perplexity.
11. **No caching in `load_ip_ranges()` — read fresh every call (added at VALIDATE, see V2 findings
    below).** The static datasets are two tiny JSON files and the sweep runs at most every 15
    minutes, so re-reading from disk on every call is cheap and eliminates an entire class of
    test-isolation bugs: a naive module-level cache would let one unit test's
    `settings.mock_external_apis` value leak into a later test in the same pytest session (the
    "mock branch" test and the "fail-open on load error" test would otherwise silently see each
    other's cached result depending on run order). If a future phase needs to optimize this,
    scope any cache key by the `mock_external_apis` boolean explicitly — do not add an
    unconditional cache.

---

## Blast Radius

- `apps/api/services/agent_verification.py` — new (pure logic: `load_ip_ranges`, `verify_ip`;
  plus the sweep orchestrator `run_verification_sweep`)
- `apps/api/services/agent_visit_persistence.py` — extend (add `upgrade_verification_method`)
- `apps/api/jobs/scheduler.py` — extend (add `_agent_verification_sweep_job` + registration)
- `apps/api/config.py` — extend (add `agent_verification_sweep_interval_minutes`)
- `apps/api/data/agent_ip_ranges/openai.json`, `perplexity.json` — new static fixtures
- `apps/api/data/agent_ip_ranges/mock/openai.json`, `mock/perplexity.json` — new mock fixtures
- `tests/unit/test_agent_verification.py` — new
- `tests/integration/` — new sweep test (Docker known-gap)

Risk class: none of auth/billing/schema-migration/public-API/deploy — this is an internal
background-job + pure-logic addition with no new externally-visible contract (Public Contracts
below). Blast radius size: ~8 files, single package (`apps/api`).

Confirmed at VALIDATE against `phase-blast-radius-registry.md`: disjoint from Phase 1
(`agent_visit.py`, migration, `agent_classifier.py`, one `main.py` import line,
`test_agent_classifier.py`), Phase 2 (`events.py`, `config.py`, `agent_visit_persistence.py` —
this phase EXTENDS the last two, which is expected: Phase 4 depends on Phase 2's output; no file
is claimed as "new/owned" by two phases), and Phase 3 (`agents.py`, `schemas/agents.py`, frontend
dashboard files). No collision found.

---

## Implementation Checklist

### Step A — Static datasets

- [ ] A1. Create `apps/api/data/agent_ip_ranges/openai.json` and `perplexity.json` with shape
      `{"vendor": "openai", "ranges": ["CIDR", ...]}`, populated with a small set (a handful) of
      real published CIDR ranges per vendor. No `anthropic.json`.
- [ ] A2. Create `apps/api/data/agent_ip_ranges/mock/openai.json` and `mock/perplexity.json`
      with a deterministic fake CIDR each (e.g. `10.99.0.0/24`), so a test IP inside that block
      deterministically upgrades under `MOCK_EXTERNAL_APIS=true`.

### Step B — Verification module (`apps/api/services/agent_verification.py`, new)

- [ ] B1. `load_ip_ranges() -> dict[str, list[str]]`: read the vendor→CIDR-list JSON files from
      the real dir, or the `mock/` dir when `settings.mock_external_apis` is true. Fail-open:
      any missing file, JSON parse error, or malformed shape returns `{}` (log a warning, never
      raise). **Do NOT cache the result across calls** (Resolved Design Decision 11, added at
      VALIDATE) — read fresh from disk every call. The dataset is two tiny JSON files and the
      sweep runs at most every 15 minutes, so this is cheap; it also avoids stale-cache bugs
      between unit tests that flip `settings.mock_external_apis`.
- [ ] B2. `verify_ip(vendor: str, ip: str) -> str | None`: PURE except for calling
      `load_ip_ranges()` internally (no caching — see B1). Look up `vendor` in the loaded ranges;
      if absent (including Anthropic, which has no entry), return `None`. Otherwise parse `ip` via
      `ipaddress.ip_address(ip)` (mirrors `url_guard.py`'s usage) and check membership in any
      `ipaddress.ip_network(cidr)` for that vendor; return `"ip-verified"` on match, else `None`.
      Wrap parsing defensively — malformed `ip` or `cidr` values return `None`, never raise.
- [ ] B3. `async run_verification_sweep(db: AsyncSession) -> None`: query eligible rows per the
      locked sweep query (Resolved Design Decision 5), call `verify_ip(vendor, ip_address)` per
      row, and for matches call `upgrade_verification_method(db, id, "ip-verified")` (Step C).
      Wrap each row's processing in its own try/except so one bad row logs and continues rather
      than aborting the sweep (matches `_resolution_sweep_job`'s per-item isolation convention).

### Step C — Persistence extension (`apps/api/services/agent_visit_persistence.py`)

- [ ] C1. Add `async upgrade_verification_method(db: AsyncSession, id: str, method: str) -> None`:
      fail-open `UPDATE agent_visits SET verification_method = :method WHERE id = :id`. On any
      exception: `db.rollback()`, `logger.exception(...)` with keys-only fields (`id`, `method` —
      never IP/PII), and return without raising (caller treats as best-effort).

### Step D — Scheduler wiring (`apps/api/jobs/scheduler.py`)

- [ ] D1. Add `async def _agent_verification_sweep_job() -> None`, a thin wrapper mirroring
      `_resolution_sweep_job`: opens its own `async_session()`, calls
      `agent_verification.run_verification_sweep(db)`, wraps the whole call in its own
      try/except with `logger.exception("agent_verification_sweep_crashed")` on failure.
- [ ] D2. Register via
      `scheduler.add_job(_agent_verification_sweep_job, "interval", minutes=settings.agent_verification_sweep_interval_minutes, id="agent_verification_sweep", replace_existing=True)`
      alongside the existing job registrations in this file. Confirmed at VALIDATE: `id`
      `"agent_verification_sweep"` does not collide with any existing job id (`sync_all_feeds`,
      `resolution_sweep`, `publish_scheduled_blog`, `retention_purge`, `changelog_sync`,
      `connection_nudge`, `referral_activation`, `outcome_digest`).

### Step E — Config (`apps/api/config.py`)

- [ ] E1. Add `agent_verification_sweep_interval_minutes: int = 15` next to
      `resolution_sweep_interval_minutes`, same convention (plain `int` field with inline comment
      describing cadence purpose).

### Step F — Static-safety check (proves the hot path stays untouched)

- [ ] F1. Confirm (via grep or a one-line python import-check) that
      `apps/api/routers/events.py` does NOT import `agent_verification` — the module is
      sweep-only, never invoked from the ingest hot path. This is the AC5/OQ2 proof. Confirmed at
      VALIDATE: baseline count is already `0` (module does not exist yet) — this is the correct
      pre-EXECUTE starting point for the check.

---

## Backlog Items Written (out-of-scope, tracked)

- `process/features/evallayer/backlog/phase-04b-rdns-verification_NOTE_22-07-26.md`
- `process/features/evallayer/backlog/phase-04-live-range-refresh_NOTE_22-07-26.md`

---

## Test Plan

### Unit — `tests/unit/test_agent_verification.py` (no deps, Fully-Automated)

- `verify_ip` matches a mock-CIDR IP (e.g. `10.99.0.5` against `10.99.0.0/24`) → returns
  `"ip-verified"`.
- `verify_ip` with a non-matching IP → returns `None`.
- `verify_ip` for vendor `"anthropic"` → returns `None` regardless of IP (structural ceiling —
  proves no dataset entry, not an incidental gap).
- `verify_ip` with a malformed IP string or malformed CIDR entry → returns `None`, never raises.
- `load_ip_ranges()` under `mock_external_apis=True` → returns the mock fixture set (deterministic
  fake CIDRs), not the real dataset.
- `load_ip_ranges()` on a simulated file-read/parse failure → returns `{}` (fail-open), does not
  raise.
- **(Added at VALIDATE — closes a V2 test-coverage gap.)** `run_verification_sweep` isolates
  per-row failures without raising, using a mocked `AsyncSession` (no real DB, no Docker
  required): seed 3 fake row objects (one openai match, one anthropic no-match, one whose
  `upgrade_verification_method` call is monkeypatched to raise) and assert the sweep coroutine
  completes without raising and still processes the remaining rows. This gives the fail-open
  orchestration property (Resolved Design Decision 7c) a Fully-Automated proof that does not
  depend on the Docker-gated integration test below.

Failing stub (per fully-automated scenario, TDD red-first starting point for execute-agent):

```
test("should upgrade a matching mock-CIDR IP to ip-verified", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: verify_ip matches a mock-CIDR IP")
})
test("should return None for a non-matching IP", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: verify_ip non-matching IP")
})
test("should return None for Anthropic regardless of IP", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: verify_ip Anthropic structural ceiling")
})
test("should return None for malformed ip/cidr without raising", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: verify_ip malformed input fail-open")
})
test("should return mock fixture set under MOCK_EXTERNAL_APIS=true", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: load_ip_ranges mock branch")
})
test("should return empty dict on file load failure", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: load_ip_ranges fail-open on error")
})
test("should isolate a per-row failure in run_verification_sweep without raising", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: run_verification_sweep fail-open isolation (mocked AsyncSession)")
})
```

(Note: repo test suite is Python/pytest — the JS-shaped stub above is the harness's canonical
TDD-stub notation per `vc-test-coverage-plan`; execute-agent translates each stub 1:1 into a
`pytest` test function with the same behavior name before writing real logic.)

### Static-safety — Fully-Automated

- Area: `agent_verification` not imported by `routers/events.py`.
- Command: `grep -c "agent_verification" apps/api/routers/events.py` → expect `0`.

### Regression — Fully-Automated

- Full unit suite: `.venv/bin/python -m pytest tests/unit -q` → no regression vs the pre-phase
  baseline count (baseline per blast-radius registry: 725 passed, 2 skipped after Phase 3).

### Integration — Hybrid (Docker known-gap)

- Area: `run_verification_sweep` end-to-end against a real (test) DB.
- Scenario: seed one `ua-only` openai row with a mock-matching IP, one `ua-only` anthropic row,
  and one `ua-only` non-matching-IP openai row. Run the sweep. Assert: openai-matching row →
  `ip-verified`; anthropic row → still `ua-only`; non-matching row → still `ua-only`. Assert
  sweep completes without raising when one row's upgrade is forced to fail (fail-open proof —
  also covered at the unit tier per the added mocked-AsyncSession test above, so this property no
  longer rests on the Docker gate alone).
- Precondition: Docker Postgres running (`infra/docker-compose.yml`).
- Command: `.venv/bin/python -m pytest tests/integration/test_agent_verification_sweep.py -m integration -q`
- Gap if not run in CI: marked Known-Gap per repo's existing Docker-gated integration convention
  (see `process/context/tests/all-tests.md`); does not block phase VERIFIED per SPEC AC8 note on
  live-provider verification being Agent-Probe/Known-Gap-acceptable. Same environment-gap pattern
  already logged for Phase 1/2/3 in the blast-radius registry — not phase-4-specific.

### Missing Test Areas

| Area | Why untestable in this phase | Resolution chosen |
|---|---|---|
| Live (non-mocked) vendor range accuracy | Requires real live IP traffic from each vendor to confirm real-world CIDR correctness | Known-Gap per SPEC AC8 — acceptable, not required for VERIFIED |
| Sweep behavior under concurrent scheduler replicas | No multi-replica test harness exists | Deferred — matches existing `_resolution_sweep_job` precedent (no advisory-lock requirement identified for this sweep; single-flight not required since upgrades are idempotent) |

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `verify_ip` matches mock-CIDR IP → `ip-verified` | Fully-Automated | AC8 |
| `verify_ip` non-matching IP → `None` | Fully-Automated | AC8 |
| `verify_ip` Anthropic vendor → `None` regardless of IP | Fully-Automated | AC8 (Anthropic ceiling) |
| `verify_ip` malformed input → `None`, no raise | Fully-Automated | AC8 (fail-open) |
| `load_ip_ranges()` mock branch under `MOCK_EXTERNAL_APIS=true` | Fully-Automated | AC14 |
| `load_ip_ranges()` fail-open on file error → `{}` | Fully-Automated | AC14 |
| `run_verification_sweep` per-row fail-open isolation (mocked AsyncSession) | Fully-Automated | AC8 (fail-open orchestration, added at VALIDATE) |
| `agent_verification` not imported by `routers/events.py` | Fully-Automated | AC5 / Resolved Open Question 2 (hot-path untouched) |
| Full unit regression, no count drop | Fully-Automated | Program-level regression safety |
| `run_verification_sweep` end-to-end (seeded rows, real DB) | Hybrid (Docker known-gap) | AC8 |

Exact commands:

```bash
.venv/bin/python -m pytest tests/unit/test_agent_verification.py -m unit -q
grep -c "agent_verification" apps/api/routers/events.py   # expect: 0
.venv/bin/python -m pytest tests/unit -q                  # no regression vs pre-phase baseline
.venv/bin/python -m pytest tests/integration/test_agent_verification_sweep.py -m integration -q   # Docker known-gap
```

---

## Test Infra Improvement Notes

(none identified yet)

---

## Exit Gate

```bash
# Mock IP-range verification upgrades confidence (AC8)
.venv/bin/python -m pytest tests/unit/test_agent_verification.py -m unit -q
# Expected: matching mocked IP -> confidence upgraded to ip-verified; all 7 unit scenarios pass
# (6 original + 1 added at VALIDATE for sweep fail-open isolation)

# Anthropic ceiling (AC8)
# covered by the same test file — "verify_ip Anthropic vendor -> None regardless of IP"

# Hot-path untouched (AC5 / Resolved Open Question 2)
grep -c "agent_verification" apps/api/routers/events.py
# Expected: 0

# Mock mode coverage (AC14, this phase's external-call-shaped surface)
# unit tests above run fully offline under MOCK_EXTERNAL_APIS=true; no live network call in test suite
```

- All exit-gate criteria pass; live-provider (non-mocked) verification and the sweep's
  integration-level DB test remain explicitly Hybrid/Known-Gap per SPEC AC8 note — not required
  for this phase's VERIFIED status, but documented (not silently dropped) per the backlog notes
  and Missing Test Areas table above.
- Phase report written to report destination above.

---

## Blockers That Would Justify BLOCKED Status

- Phase 2 exit gate not yet passed (no classified visits to verify).
- No real vendor IP-range fixture available and mock-only path insufficient for confidence in
  correctness (should not block VERIFIED per SPEC, but must be documented as Known-Gap, not
  silently dropped — see Missing Test Areas table above).

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [ ] 1. RESEARCH — research-agent: prior phase reports read; test context loaded; plan drift checked
- [ ] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written
- [x] 3. PLAN-SUPPLEMENT — plan-agent: exact checklist + resolved design decisions encoded; backlog
      NOTE files written; see Inner Loop Refresh Note below
- [x] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md`
- [x] 5. EXECUTE — all checklist items done; per-section test gates run and green (unit 10/10,
      import-check=0, regression 735/2; Docker integration Known-Gap, collect-clean)
- [x] 6. EVL — all EVL gates green on runnable gates (unit 10/10, hot-path grep=0, Anthropic
      structural ceiling confirmed); Docker integration Known-Gap (collect-clean, unrun); follow-up
      stubs (2 backlog notes) already registered; EVL Confirmation section written to phase report
- [x] 7. UPDATE PROCESS — phase report written, umbrella state updated, blast-radius registry
      finalized. Not committed this session (vc-git-manager next, per instruction).

**Validate-contract required before execute.** New external-call-shaped surface — VALIDATE may
never be skipped for this phase. Satisfied — see `## Validate Contract` below.

---

## Inner Loop Refresh Note (22-07-26)

Plan-agent supplement pass. Sections updated: Purpose, added "Resolved Design Decisions" section
(10 locked decisions encoding the design brief exactly, including the concrete sweep query sizing
that INNOVATE left open), Blast Radius (expanded to list all concrete new/touched files), full
Implementation Checklist rewritten with atomic file-scoped steps (A–F), new "Backlog Items Written"
section, full "Test Plan" section (unit/static-safety/regression/integration/missing-areas),
"Verification Evidence" table populated with real commands mapped to AC8/AC14/AC5, Exit Gate
commands filled in with real (non-placeholder) commands, Phase Loop Progress step 3 ticked. No
architectural deviation from the prior draft — this pass concretizes previously-placeholder
sections per the locked design brief. `## Validate Contract` left as placeholder per protocol —
PVL has not yet run.

---

## Touchpoints

- `apps/api/services/agent_verification.py` (new)
- `apps/api/services/agent_visit_persistence.py` (extend)
- `apps/api/jobs/scheduler.py` (extend)
- `apps/api/config.py` (extend)
- `apps/api/data/agent_ip_ranges/openai.json`, `perplexity.json` (new)
- `apps/api/data/agent_ip_ranges/mock/openai.json`, `mock/perplexity.json` (new)
- `tests/unit/test_agent_verification.py` (new)
- `tests/integration/test_agent_verification_sweep.py` (new, Docker known-gap)

---

## Public Contracts

- No new externally-visible API surface — this phase enriches the confidence field already
  exposed by Phase 3's `/agents` API; no shape change to that contract.
- No new inbound HTTP endpoint; the only new surface is an internal periodic scheduler job.

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/evallayer_22-07-26/phase-04-ip-verification_PLAN_22-07-26.md`
- Last completed step: Step 4 (PVL) — validate-contract written, Gate: PASS
- Validate-contract status: written (22-07-26), `generated-by: inner-pvl: phase-4`
- Supporting context files loaded: `apps/api/jobs/scheduler.py`, `apps/api/services/agent_visit_persistence.py`,
  `apps/api/services/agent_classifier.py`, `apps/api/config.py`, `apps/api/services/url_guard.py`,
  `apps/api/models/agent_visit.py`, `apps/api/models/database.py`,
  `evallayer-umbrella_PLAN_22-07-26.md` (Hard Safety Constraints + Hard Stops sections),
  `evallayer_SPEC_22-07-26.md` (AC5, AC8, AC14), `phase-blast-radius-registry.md` (Phases 1-3)
- Next step: spawn vc-execute-agent for Step 5 (EXECUTE) against this plan's Implementation
  Checklist (Steps A-F); may run in parallel with Phase 3's EXECUTE (disjoint blast radius) if
  Phase 3 is not already complete.

---

## Validate Contract

Status: PASS
Date: 22-07-26
date: 2026-07-22
generated-by: inner-pvl: phase-4

Parallel strategy: sequential
Rationale: Single-phase plan, single package (`apps/api`), ~8 files, no independent
investigation directions and no cross-agent coordination needed for this VALIDATE pass — signals
present: S4 (phase-program classification) only. Score 1/7 → LOW, but Deep Mode context loading
was triggered regardless (phase-program plan; prior phase reports + blast-radius registry loaded)
per `vc-validate-findings` Deep Mode trigger rules. EXECUTE for this phase's checklist (Steps A-F)
can run sequentially — no independent workstreams need parallel execution or a review team.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC8 | `verify_ip` matches mock-CIDR IP → `ip-verified` | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_agent_verification.py -m unit -q` | A |
| AC8 | `verify_ip` non-matching IP → `None` | Fully-Automated | same file, non-match case | A |
| AC8 | `verify_ip` Anthropic vendor → `None` regardless of IP (structural ceiling) | Fully-Automated | same file, Anthropic case | A |
| AC8 | `verify_ip` malformed ip/cidr → `None`, never raises | Fully-Automated | same file, malformed-input case | A |
| AC14 | `load_ip_ranges()` mock branch under `MOCK_EXTERNAL_APIS=true` | Fully-Automated | same file, mock-branch case | A |
| AC14 | `load_ip_ranges()` fail-open on file/parse error → `{}` | Fully-Automated | same file, load-error case | A |
| AC8 (fail-open orchestration) | `run_verification_sweep` isolates a per-row failure without raising (mocked `AsyncSession`, no Docker) | Fully-Automated | same file, sweep-isolation case (added at VALIDATE, closes vacuous-green gap) | A |
| AC5 / OQ2 | `agent_verification` never imported by `routers/events.py` (hot path untouched) | Fully-Automated | `grep -c "agent_verification" apps/api/routers/events.py` → expect `0` | A |
| Program regression | Full unit suite, no count regression vs Phase-3 baseline (725 passed / 2 skipped) | Fully-Automated | `.venv/bin/python -m pytest tests/unit -q` | A |
| AC8 | `run_verification_sweep` end-to-end against a real (test) DB, seeded rows | Hybrid | `.venv/bin/python -m pytest tests/integration/test_agent_verification_sweep.py -m integration -q` — precondition: Docker Postgres up | D |

gap-resolution legend:
- A — proven now (gate passes in this cycle, once execute-agent writes the code+tests)
- B — fixed in this plan (gate added by this plan's checklist)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: no `strategy:` value is `Known-Gap` — the one D-resolution row (Docker
integration) carries `Hybrid` as its strategy; `Known-Gap` here describes the CI-execution
condition (Docker unavailable in this sandbox), not the proving strategy itself. This mirrors the
Phase 1/2/3 precedent already recorded in the blast-radius registry.

Legacy line form (retained so existing validate-contract consumers still parse):
- agent_verification core logic: Fully-automated: `.venv/bin/python -m pytest tests/unit/test_agent_verification.py -m unit -q` (7 scenarios, including the sweep-isolation case added at VALIDATE)
- hot-path safety: Fully-automated: `grep -c "agent_verification" apps/api/routers/events.py` → expect 0
- regression: Fully-automated: `.venv/bin/python -m pytest tests/unit -q` (no count drop vs 725/2 baseline)
- sweep end-to-end: hybrid: `.venv/bin/python -m pytest tests/integration/test_agent_verification_sweep.py -m integration -q` + precondition: Docker Postgres running

Dimension findings:
- Infra fit: PASS — APScheduler `add_job` registration mirrors `_resolution_sweep_job` exactly; new job id `agent_verification_sweep` confirmed non-colliding with 8 existing job ids; no container/port surface touched; single package (`apps/api`).
- Test coverage: PASS (after in-plan fix) — original V2 pass found `run_verification_sweep`'s per-row fail-open property proven ONLY by the Docker-gated Hybrid test (a vacuous-green risk per the Net-gate rule). Fixed in-plan: added a Fully-Automated mocked-`AsyncSession` unit test for the same property (Test Plan, added-at-VALIDATE scenario) — the developed behavior now has real automated coverage independent of the Docker gap.
- Breaking changes: PASS — no new externally-visible API surface (confirmed against Public Contracts section); no schema/route/auth changes; extends two existing internal service files additively.
- Security surface: PASS — STRIDE-lite: no auth/tenant-scoping concern (internal background job, not a per-tenant user-facing query); logging is keys-only (`id`/`vendor`/`method`, never `ip_address` — matches PII/GDPR guardrail); sweep query is bounded (`LIMIT 500`, 7-day window) — no DoS/unbounded-growth risk; `verify_ip`/`load_ip_ranges` fail-open on malformed input, never raise.
- Section — Phase 04 plan (single section): PASS (after in-plan fix) — mechanical feasibility confirmed by direct file reads (`_resolution_sweep_job` pattern, `agent_visit_persistence.py` fail-open convention, `VERIFICATION_METHODS` tuple, `config.py` field location, `AgentVisit.id` inherited PK from `Base`, `url_guard.py`'s `ipaddress` usage, zero pre-existing `agent_verification` references in `events.py`). Two gaps found and fixed in-plan (not deferred): (1) missing Fully-Automated proof for `run_verification_sweep`'s fail-open isolation — added; (2) unscoped module-level cache in `load_ip_ranges()` risked stale-data leakage across unit tests that flip `mock_external_apis` — resolved by removing caching entirely (Resolved Design Decision 11). No conflicts found with other phases' file state or repo conventions. Highest-risk edit: scheduler registration (Step D2) — mitigated by confirmed unique job id and exact mirroring of the existing `_resolution_sweep_job` block.

Open gaps: none blocking. Docker-gated integration test (`test_agent_verification_sweep.py`) remains a documented environment Known-Gap (not a design defect) — same pattern already accepted for Phase 1/2/3 in the blast-radius registry; does not block VERIFIED per SPEC AC8 note.
What this coverage does NOT prove:
- Unit tests (`verify_ip`, `load_ip_ranges`, sweep-isolation) prove pure-logic correctness and fail-open behavior in isolation; they do NOT prove the sweep's actual SQL query executes correctly against a real Postgres schema (column types, index usage, `ORDER BY`/`LIMIT` behavior) — that requires the Docker-gated Hybrid integration test.
- The static-safety grep proves `events.py` does not statically import `agent_verification` at EXECUTE-time baseline; it does not prove no *future* regression reintroduces the import — this is a point-in-time check, re-run at EVL for the same guarantee.
- The regression command proves no unit-test-count drop; it does not measure latency — the ingest-latency benchmark (AC5) is a separate Hybrid gate owned by the Phase-2 backlog stub (`phase-02-latency-benchmark_NOTE_22-07-26.md`), not this phase.
- Live (non-mocked) vendor IP-range accuracy is not proven by any gate in this phase — explicitly Known-Gap per SPEC AC8, tracked in the Missing Test Areas table and the `phase-04-live-range-refresh` backlog note.
(Required until C3 is implemented — temporary C3 mitigation)
Gate: PASS (no FAILs, plan updated)
Accepted by: N/A — Gate: PASS, no CONCERNs remain outstanding (2 findings from the V2 pass were fixed in-plan, not accepted-as-gaps; the one Docker known-gap is a pre-existing environment condition, not a CONCERN requiring acceptance)
