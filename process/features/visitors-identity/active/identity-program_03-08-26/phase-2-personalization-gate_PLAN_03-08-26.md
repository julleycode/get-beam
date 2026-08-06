---
name: plan:identity-program-phase-2-personalization-gate
description: "Identity honesty program — Phase 2: send-time hard guard blocking personalized copy for Candidate-tier recipients"
date: 03-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
  phase: phase-2
---

# Phase 2 — Personalization Gating (Send-Time Hard Guard)

**Program:** identity-program
**Umbrella plan:** process/features/visitors-identity/active/identity-program_03-08-26/identity-program-umbrella_PLAN_03-08-26.md
**Phase status:** ✅ EXECUTE complete (unit gates green; Hybrid gate env-blocked known-gap)
**Report destination:** process/features/visitors-identity/active/identity-program_03-08-26/phase-2-personalization-gate_REPORT_03-08-26.md

---

## Purpose

Enforce, at send time, that a Candidate-tier recipient never receives a guessed name/title/company
merge field anywhere in subject or body — generic copy only ("Hey there" instead of "Hi Janet").
This is a send-time guard (reads current `identity_status` per send), not a draft-time-only check,
so mid-campaign promotion (Phase 1's confirm-candidate) is correctly reflected per send. The guard
must fail loud (raise/log) if a candidate row ever reaches the personalized branch — never silently
substitute — so future refactors fail fast in CI rather than silently regressing to guessing.

---

## Entry Gate

- Phase 1 exit gate passed: `is_verified_identity()` exists, `identity_status="candidate"` is being assigned correctly, confirm-candidate endpoint sets a promotion timestamp.

---

## Blast Radius

- `apps/api/services/campaign_sender.py` — **Phase 2's owned region only**: the tier-check guard immediately before the `_personalize()` calls at ~line 248/250, PLUS a new `Visitor.identity_status` join added to the existing per-recipient query in `send_campaign_emails()`. **VALIDATE correction:** `identity_status` lives on `Visitor`, NOT on `IdentifiedVisitor` — the loop currently only queries `IdentifiedVisitor` (line ~187-193), so `identity_status` is NOT already fetched and must be added via the same join pattern already used elsewhere in this codebase (`identity_resolver.py:135`, `routers/visitors.py:98`, `daily_digest.py:421`): `Visitor.site_id == IdentifiedVisitor.site_id` AND `Visitor.visitor_id == IdentifiedVisitor.visitor_id`. Does NOT touch the shared compose step upstream (that is Phase 3's owned region — decoration/custom_args construction, which reads `subject`/`body_html` produced by this phase's branch but is not itself edited by this phase).
- Campaign drafting logic (wherever draft copy is generated — locate exact file via research; likely `apps/api/agents/campaign_planner.py` or a drafting service) — UX-polish only: prefer generic wording by default for Candidate-tier drafts (not the enforcement mechanism, just better defaults).
- `tests/unit/test_outbound_identity_gate.py` — extend with Candidate-tier personalization assertions.
- New test file or extension covering send-time personalization composition.

**Does NOT touch:** `is_emailable_identity()` (Candidates remain emailable per locked decision — this phase gates copy, not sendability), `gmail_sender.py` (Phase 3), any import/promotion logic (Phases 4/5/6).

---

## Implementation Checklist

### Step A — Send-time hard guard

- [x] A1. **(VALIDATE-corrected)** In `campaign_sender.py::send_campaign_emails()`, extend the existing per-recipient `IdentifiedVisitor` lookup to also fetch `Visitor.identity_status` via a join on `(site_id, visitor_id)` — the same join pattern used in `identity_resolver.py:135` / `routers/visitors.py:98` / `daily_digest.py:421`. `identity_status` is NOT already fetched in this loop (it lives on `Visitor`, not `IdentifiedVisitor`; the loop currently only selects `IdentifiedVisitor`). Then, immediately before the `_personalize()` call sites (~line 248/250), branch: if `not is_verified_identity(identity_status)`, route to a generic-copy composition path; else proceed to the existing `_personalize()` flow unchanged.
- [x] A2. Add a `_compose_generic(...)` function (or equivalent) that strips/replaces any name/title/company merge field with a generic fallback ("Hey there", no company reference) — reuse existing template infrastructure, do not fork a new template engine. **Testability requirement:** factor the A1 branch decision into a small pure helper, e.g. `_compose_for_recipient(identity_status: str, full_name: str | None, company_name: str | None, sender_name: str | None) -> tuple[str, str]`, mirroring the existing pure `_personalize()` precedent (`test_personalize.py` tests `_personalize` directly with no DB). This keeps C1/C4 genuine no-DB unit tests instead of requiring the full DB-coupled `send_campaign_emails()` call graph.
- [x] A3. **Fail-loud guard**: add an assertion/raise immediately after A1's branch — if somehow a Candidate-tier row's data reaches the `_personalize()` call path (e.g. future refactor accidentally bypasses the branch), raise a clear exception and log at ERROR level with `resolution_provider` + `visitor_id` (no PII in the log message itself, matching structlog conventions). This must be a hard failure in tests, not a silent no-op. Prefer implementing this check inside the same pure helper from A2 so C4 can also be a no-DB test.
- [x] A4. Confirm the guard reads `identity_status` fresh at send time (via the A1 join, evaluated per-iteration inside the loop, not cached from an earlier point in campaign processing) — this is what makes AC17's mid-campaign cutover correct "for free."

### Step B — Draft-time UX polish (non-enforcing)

- [x] B1. Locate the campaign draft composition path (segmenter/campaign_planner or drafting endpoint) via research.
- [x] B2. When drafting copy for a segment containing Candidate-tier recipients, bias the AI prompt/template toward generic wording by default (UX nicety — the real enforcement is Step A, this just reduces friction/rework for the human approving the draft).

### Step C — Tests

- [x] C1. Unit test: Candidate-tier recipient send composition never includes a populated name/title/company merge field sourced from `{rb2b, leadpipe, capturify}` resolution_provider data (SPEC AC15). **Testability note (VALIDATE):** `send_campaign_emails()` is DB-coupled end-to-end (Campaign/Site/IdentifiedVisitor/Visitor/EnrichmentProfile/CampaignTouchpoint) and cannot be exercised as a no-DB unit test. Test the A2 pure helper (`_compose_for_recipient` or equivalent) directly with `identity_status="candidate"` — assert no name/title/company appears in the output. The DB wiring itself (that the guard actually reads the joined `Visitor.identity_status` and dispatches to the right composer) is proven by C3's integration test, not by C1.
- [x] C2. Regression test: verified/"identified" recipient send is personalized exactly as today — run existing personalization test coverage unchanged (SPEC AC16), plus a new assertion that the A2 pure helper called with `identity_status="identified"` produces output identical to calling `_personalize()` directly.
- [x] C3. Integration test (requires Postgres+Redis, per TESTING.md — Hybrid tier, not Fully-Automated): simulate a campaign mid-send-batch where a recipient's candidate is confirmed (Phase 1's confirm-candidate) partway through; assert sends BEFORE the promotion timestamp used generic copy and sends AFTER used personalized copy, and that already-sent messages are not retroactively changed (SPEC AC17).
- [x] C4. Fail-loud test: directly exercise the Step A3 guard path (e.g. call the extracted pure helper with a forced-invalid state such as `identity_status="candidate"` paired with a flag/path claiming the personalized branch was taken) and assert it raises rather than silently proceeding. If A3 lives in the same pure helper as C1/A2, this is also a no-DB test.

---

## Exit Gate

```bash
.venv/bin/python3.11 -m pytest tests/unit/test_outbound_identity_gate.py -q
# Expected: 0 failures, including new Candidate generic-copy assertions

.venv/bin/python3.11 -m pytest tests/unit -k "campaign_sender or personaliz" -q
# Expected: 0 failures, no regression on existing personalization tests

.venv/bin/python3.11 -m pytest tests/integration -k "mid_campaign or promotion_cutover" -q
# Expected: 0 failures (requires Postgres+Redis running locally — see TESTING.md; Hybrid tier)
```

- SPEC ACs 15, 16, 17 all have a passing proving test.
- Fail-loud guard proven to raise, not silently substitute.
- Phase report written to report destination above.

---

## Blockers That Would Justify BLOCKED Status

- Phase 1 exit gate not yet passed (no `is_verified_identity()` or confirm-candidate timestamp to read).
- Draft composition path (Step B) turns out to require a larger AI-prompt refactor than expected — if so, descope Step B to a backlog note and keep Step A (the actual enforcement) as the phase's exit criterion; Step A alone satisfies AC15-17.

---

## Phase Loop Progress

- [ ] 1. RESEARCH — research-agent: prior phase reports read (Phase 1 report); test context loaded; plan drift checked
- [ ] 2. INNOVATE — innovate-agent: approach decided (largely pre-decided by program INNOVATE Fork 3 — confirm/refine only)
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated (or "n/a — research clean")
- [x] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written (outer-pvl, 03-08-26, Gate: PASS after 2 plan-text fixes applied in-line)
- [x] 5. EXECUTE — all checklist items done; per-section test gates run and green (or gaps documented)
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.**

---

## Touchpoints

- `apps/api/services/campaign_sender.py` (send-time guard region only — see Blast Radius)
- Campaign draft composition path (exact file TBD by Phase 2 research)
- `tests/unit/test_outbound_identity_gate.py`

---

## Public Contracts

- Verified/"identified" recipient personalization behavior unchanged.
- `is_emailable_identity()` unchanged, 3 params — Candidates remain emailable.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Candidate send never contains guessed name/title/company merge field | Fully-Automated | AC15 |
| Verified send personalized exactly as today (regression) | Fully-Automated | AC16 |
| Mid-campaign promotion cutover — per-send state at send time | Hybrid (requires Postgres+Redis; VALIDATE-corrected from Fully-Automated — this is a `tests/integration` scenario per repo convention) | AC17 |
| Fail-loud guard raises on candidate reaching personalized branch | Fully-Automated | (defense-in-depth, vc-predict mitigation) |

Failing stub (example):
```
test("should never personalize a Candidate-tier send with a guessed name", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: candidate generic-copy enforcement")
})
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/visitors-identity/active/identity-program_03-08-26/phase-2-personalization-gate_PLAN_03-08-26.md`
- Last completed step: EXECUTE (Steps A/B/C implemented; 2 Fully-Automated gates green; Hybrid gate env-blocked)
- Validate-contract status: written (03-08-26) — see `## Validate Contract` below
- Supporting context files loaded: umbrella plan, SPEC, INNOVATE Decision Summary (Fork 3), Phase 1 plan (Phase 1 not yet executed — `is_verified_identity()` does not exist on disk yet; confirmed via `identity_classification.py` read at VALIDATE time)
- Next step: Spawn vc-research-agent for RESEARCH (Step 1), after Phase 1 exit gate confirmed passed

---

## Validate Contract

Status: PASS
Date: 03-08-26
date: 2026-08-03
generated-by: outer-pvl

Parallel strategy: sequential
Rationale: single-plan outer-PVL validation, 4 Layer-1 dimension agents + 1 Layer-2 section agent — score 1/7 (S7: blast radius touches 1 primary file for enforcement + 1 test file; well under the 5-file/multi-package thresholds that would justify parallel fan-out for THIS phase in isolation). Sequential read-through by a single validate-agent was sufficient; no cost guard triggered.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC15 | Candidate-tier send composition never includes a populated name/title/company merge field | Fully-Automated | `tests/unit/test_outbound_identity_gate.py::test_candidate_tier_uses_generic_copy` (new — calls the extracted `_compose_for_recipient`/equivalent pure helper with `identity_status="candidate"`) | B |
| AC16 | Verified/"identified" recipient personalization unchanged (regression) | Fully-Automated | `tests/unit/test_personalize.py` (existing, run unchanged) + `tests/unit/test_outbound_identity_gate.py::test_identified_tier_uses_personalized_copy` (new) | B |
| AC17 | Mid-campaign promotion cutover — per-send state read fresh at send time | Hybrid (precondition: Postgres+Redis via docker-compose, per TESTING.md) | `tests/integration/test_campaign_mid_send_promotion_cutover.py` (new; `-k "mid_campaign or promotion_cutover"`) | B |
| (defense-in-depth) | Fail-loud guard raises when a candidate row reaches the personalized-branch code path | Fully-Automated | `tests/unit/test_outbound_identity_gate.py::test_fail_loud_guard_raises_on_candidate_in_personalized_branch` (new) | B |
| (non-enforcing UX) | Draft-time AI prompt bias toward generic wording for Candidate-containing segments (Step B) | Agent-Probe / Known-Gap (optional) | Manual review of a drafted campaign touching a Candidate-tier segment; plan explicitly permits descoping Step B to backlog per its own Blockers section — Step A alone satisfies AC15-17 | D |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: `strategy:` column carries only Fully-Automated / Hybrid / Agent-Probe. The Step B row uses Agent-Probe (not Known-Gap) as its strategy value; Known-Gap is recorded via gap-resolution D only, per policy — Step B is optional/non-enforcing UX and does not gate AC15-17, so the net gate does not rest on this row.

Legacy line form (retained for existing validate-contract consumers):
- campaign_sender.py send-time guard: Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_outbound_identity_gate.py -q` | Fully-automated (regression): `.venv/bin/python3.11 -m pytest tests/unit -k "campaign_sender or personaliz" -q` | Hybrid: `.venv/bin/python3.11 -m pytest tests/integration -k "mid_campaign or promotion_cutover" -q` + precondition: Postgres+Redis running (docker-compose, per TESTING.md) | known-gap: none blocking (Step B UX polish is optional, documented above)

Failing stubs (Fully-Automated rows only):

```
test("should never personalize a Candidate-tier send with a guessed name/title/company", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: candidate-tier send composition never includes a populated name/title/company merge field (AC15)")
})
```
```
test("should personalize an identified-tier send exactly as today", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: verified/identified recipient personalization is byte-identical to pre-Phase-2 behavior (AC16)")
})
```
```
test("should raise, not silently substitute, when a candidate row reaches the personalized branch", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: fail-loud guard raises on candidate-in-personalized-branch (defense-in-depth)")
})
```

Dimension findings:
- Infra fit: PASS — pure Python service-layer edit inside an existing async function; no container/infra/runtime-surface change; no new dependency.
- Test coverage: CONCERN → RESOLVED IN PLAN — original plan text classified AC17 as Fully-Automated and specified C1/C4 as plain "unit tests" against a fully DB-coupled function (`send_campaign_emails()` queries Campaign/Site/IdentifiedVisitor/Visitor/EnrichmentProfile/CampaignTouchpoint — cannot run without a DB session). Fixed by: (1) reclassifying AC17 to Hybrid in the Verification Evidence table and Test Gates table (matches this repo's own `pytest.ini` marker convention: "integration: Tests that require PostgreSQL and/or Redis"); (2) adding an explicit Step A2/C1/C4 instruction to factor the branch decision into a small pure helper (mirroring the existing `_personalize()` / `test_personalize.py` precedent) so C1 and C4 are genuine no-DB unit tests, while C3 (DB-backed, Hybrid) proves the actual query/dispatch wiring.
- Breaking changes: PASS — `is_emailable_identity()` signature untouched (still 3 params, confirmed by reading the current call site at `campaign_sender.py:202-206`); no schema/migration; no public API/route change; verified/identified personalization path is explicitly regression-tested (C2) to stay byte-identical.
- Security surface: PASS — no auth, secrets, billing, or trust-boundary surface touched. The fail-loud guard (A3) is itself a defense-in-depth mitigation against silent identity-honesty regression (per the program's INNOVATE vc-predict CAUTION finding), not a new attack surface. No PII enters log messages per structlog convention (confirmed A3's own wording matches existing `logger.warning("campaign_email_failed", visitor_id=vid[:8], ...)` pattern in the file, i.e. truncated visitor_id only, no email/name).
- Section — Phase 2 plan (mechanical feasibility / gaps / conflicts / highest-risk edit): CONCERN → RESOLVED IN PLAN — see "Mechanical feasibility" below.

Mechanical feasibility: Edit target strings are real and uniquely matchable — `send_campaign_emails()` at `campaign_sender.py:119`, the `_personalize()` call sites at lines 248-251 (plan's "~248/250" is accurate), `is_emailable_identity(iv.resolution_provider, ...)` call at lines 202-206 (untouched, confirmed 3-arg signature). ONE real gap found and fixed in-plan: the plan originally asserted `identity_status` was "already fetched via resolution_provider lookup at line 203" — false. `identity_status` is a column on `Visitor` (`apps/api/models/visitor.py:55`), not on `IdentifiedVisitor` (confirmed by reading the model file — `IdentifiedVisitor` has no `identity_status` field). `campaign_sender.py` imports only `IdentifiedVisitor` (`from apps.api.models.visitor import IdentifiedVisitor`), never `Visitor`, and the per-recipient query at lines 187-193 selects only `IdentifiedVisitor`. Fixed via Plan Update: Step A1 now explicitly specifies the join needed, using the exact join predicate already established elsewhere in this codebase (`identity_resolver.py:135`, `routers/visitors.py:98`, `daily_digest.py:421`) — this is a well-precedented, low-risk join, not a novel pattern.

Gaps found: (1) [FIXED] identity_status fetch — see above. (2) [FIXED] AC17 test-tier misclassification — see Test coverage above. (3) Step C1's original target file (`test_outbound_identity_gate.py`, which today ONLY contains `is_emailable_identity` tests) is a defensible home for the new candidate-tier assertions since it is already the identity-gating test file, but `test_personalize.py` (which already tests the pure `_personalize()` function this phase parallels) is an equally valid location — plan already hedges with "New test file or extension," so no fix required; left to execute-agent's judgment (see Execute-Agent Instructions).

Conflicts found: none. Confirmed disjoint from Phase 3's owned region: `subject`/`body_html` (produced by this phase's branch at ~248-251) are read by BOTH the Gmail send path (line ~301) and the SendGrid path (line ~318) further down in the same function — Phase 3's job is decoration/custom_args parity between those two branches, not the composition step this phase edits. No overlapping line ranges. Confirmed no migration is introduced by this phase (identity_status column already exists — added by nothing in Phase 2's scope; Phase 1 or an earlier migration owns that column's existence).

Highest-risk edit + mitigation: Replacing the unconditional `_personalize()` call at lines 248-251 with a branching path. Mitigation (already specified via A2 fix above): implement the "identified" branch as a call to the existing `_personalize()` function completely unchanged (byte-for-byte), and add the new "not verified" branch as an entirely separate code path — never modify `_personalize()` itself. C2's regression assertion (new helper called with `identity_status="identified"` must equal calling `_personalize()` directly) is the proving test for this mitigation. Execute-agent should implement Step A2's pure helper as a thin dispatcher: `if is_verified_identity(identity_status): return _personalize(...), _personalize(...) else: return _compose_generic(...), _compose_generic(...)` — this keeps `_personalize()` a zero-touch dependency.

Plan updates applied (during this VALIDATE pass, before contract write):
- P1: Blast Radius + Step A1 — corrected the false "identity_status already fetched" claim; specified the exact join needed and cited 3 existing precedents in this codebase for the same join pattern.
- P2: Step A2/A3/C1/C4 — added the pure-helper decomposition requirement so C1 and C4 can be genuine no-DB `tests/unit` tests instead of requiring the full DB-coupled `send_campaign_emails()` call graph.
- P3: Verification Evidence + Test Gates table — reclassified AC17 from Fully-Automated to Hybrid (it is a `tests/integration` scenario requiring Postgres+Redis per this repo's own pytest marker convention).
- P4: Exit Gate — added a Hybrid-precondition note to the `tests/integration` command.

Execute-agent instructions:
- E1: Implement the A1 join using `select(IdentifiedVisitor, Visitor.identity_status).join(Visitor, (Visitor.site_id == IdentifiedVisitor.site_id) & (Visitor.visitor_id == IdentifiedVisitor.visitor_id)).where(...)` or an equivalent second lightweight query per iteration — either is acceptable; prefer whichever keeps the diff smallest against the existing query shape at lines 187-193.
- E2: Do not modify `_personalize()`'s signature or behavior. The "identified" branch must call it exactly as today.
- E3: Choose the test-file home for C1/C2/C4 (extend `test_outbound_identity_gate.py` OR `test_personalize.py` OR a new file) at implementation time; document the choice in the phase report. Either is acceptable — this was left open by design (see Gaps found #3).
- E4: If Step B (draft-time UX polish) proves to require a larger AI-prompt refactor than a small bias tweak, descope it to a backlog note per the plan's own Blockers section — this does not block the phase exit gate, which is satisfied by Step A alone (AC15-17).
- E5: Confirm Phase 1's exit gate has actually passed (`is_verified_identity()` exists in `apps/api/services/identity_classification.py`) before starting EXECUTE — confirmed NOT to exist yet as of this VALIDATE pass (03-08-26); Phase 1 has not been executed. This phase's plan is validated and ready, but its Entry Gate is not yet met — do not spawn execute-agent for Phase 2 until Phase 1's exit gate is independently confirmed.

Open gaps: none blocking. Step B (draft-time UX polish) remains explicitly optional per the plan's own design.

What this coverage does NOT prove:
- AC15/AC16/defense-in-depth unit tests (Fully-Automated, testing the extracted pure helper) do NOT prove that `send_campaign_emails()` actually calls that helper correctly with a freshly-joined `identity_status` value from the database — that wiring is proven only by AC17's Hybrid integration test.
- AC17's Hybrid integration test proves per-send state correctness for ONE simulated mid-batch promotion scenario; it does not prove behavior under concurrent sends racing a promotion (out of scope — no such requirement in SPEC ACs 15-17).
- No test in this plan proves Step B's draft-time AI prompt bias actually produces better draft copy — that row is Agent-Probe/Known-Gap by design (non-enforcing UX, optional).
- No test proves this phase's behavior end-to-end through the real SendGrid/Gmail providers (both are already mocked/stubbed upstream of this phase's edits in existing test infra) — provider-level send confirmation is out of this phase's scope.

Gate: PASS (no FAILs; 2 real CONCERNs found during Layer 1/Layer 2 review, both resolved by in-plan text fixes before contract write — see "Plan updates applied" above; no unresolved CONCERNs remain)
Accepted by: session (outer-PVL, autonomous — no interactive user in this delegated VALIDATE task; both CONCERNs were mechanically fixable and fixed in-plan rather than deferred, so no CONDITIONAL acceptance was needed)
