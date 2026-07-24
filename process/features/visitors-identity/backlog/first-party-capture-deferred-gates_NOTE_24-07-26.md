---
name: plan:first-party-capture-deferred-gates
description: "Backlog: environment-only deferred gates for first-party-capture — webkit/firefox autofill legs, Phase 3 integration re-confirm, migration live-apply; plus D4 CLEAN/RED policy doc pointer"
date: 24-07-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
  phase: first-party-capture
---

# First-Party Capture — Deferred Gates Backlog

**STATUS: RESOLVED (24-07-26)** for Gap 1 and Gap 2. Independent EVL final run: Gap 1 (AC5
webkit/firefox autofill legs) — `e2e/autofill.spec.ts --project=webkit --project=firefox` 2/2
passed. Gap 2 (Phase 3 integration re-confirm) — the AC11 `do_not_resolve` integration test
(non-vacuous: real `Visitor(do_not_resolve=True)`, real `record_signal()`, asserts insert
count==0) 1/1 passed. Gap 3 (migration live-apply) — the round-trip was proven on a disposable
Postgres this session (see `owned-data-layer-docker-verification_NOTE_23-07-26.md` for the shared
migration-chain evidence); a REAL/production live-apply remains a separate explicit operator
action, unchanged in scope. The D4 CLEAN/RED policy doc pointer remains genuinely open — carried
forward to `post-docker-gate-followups_NOTE_24-07-26.md`. `first-party-capture_PLAN_24-07-26.md`
promoted to VERIFIED and archived to `completed/`. This note is kept as audit trail — do not
delete.

**Why this note exists (original, 24-07-26):** per the vacuous-green ban, an acceptance criterion whose only proving
gate never actually ran in this session is scored **unmet/partial** at closeout even when the rest
of the plan is fully green. This tracks the exact residuals for
`first-party-capture_PLAN_24-07-26.md` and the close command for each. None of these are design
defects — all three are environment/sandbox limitations, not behavioral gaps. Same posture as the
sibling `owned-data-layer-docker-verification_NOTE_23-07-26.md` in this same backlog folder —
cross-reference it for the Docker-gate precedent this plan follows.

**Not blocking:** these gaps do not block the plan from being code-complete. They block promotion
from CODE DONE to VERIFIED per the plan's own `## Phase Completion Rules`, and the task folder's
move from `active/` to `completed/`.

## Gap 1 — AC5 webkit/firefox autofill legs

**What:** the plan's cross-browser autofill matrix (`e2e/autofill.spec.ts --project=chromium
--project=webkit --project=firefox`) only ran the chromium leg. webkit/firefox Playwright browser
binaries were not cached in this sandbox and `npx playwright install webkit firefox` could not
complete within the available time/network budget.

**Proving tier:** Hybrid (chromium leg is Fully-Automated and green; webkit/firefox legs are
Hybrid on binary availability, per the plan's own Verification Evidence table).

**Close command:**
```bash
cd apps/pixel
npx playwright install webkit firefox
npx playwright test e2e/autofill.spec.ts --project=chromium --project=webkit --project=firefox
```

## Gap 2 — Phase 3 integration re-confirm

**What:** `tests/ -m integration -k "visitor_email or do_not_resolve"` (AC10/AC11) ran green at
EXECUTE time with PG+Redis up (per the plan's own EXECUTE record), but EVL could not independently
re-run it because Docker was unavailable at EVL time (15s health-check cap exceeded).

**Proving tier:** Fully-Automated (once PG+Redis are up).

**Close command:**
```bash
docker compose -f infra/docker-compose.yml up -d postgres redis
.venv/bin/python -m pytest tests/ -m integration -k "visitor_email or do_not_resolve" -q
```

## Gap 3 — source-enum migration live-apply

**What:** migration `a9f2c1e7b4d6` (`ck_visitor_emails_source` CHECK constraint) has only been
offline-validated (`alembic upgrade head --sql` dry-run) in this sandbox, never applied against a
live Postgres. Docker-gated by design — same convention as `owned-data-layer` and `evallayer`.

**Migration chain context:** current head is `a9f2c1e7b4d6`, downstream of
`e2a4c7f81b93` — re-run `alembic heads` before applying; other work may advance the head further.
See `all-context.md` AI-Agent-Traffic Layer / Owned Identity Data Layer sections for the full
pending-migration chain this repo is carrying.

**Close command:**
```bash
docker compose -f infra/docker-compose.yml up -d postgres redis
cd apps/api
../../.venv/bin/python -m alembic heads   # confirm a9f2c1e7b4d6 is still current head
../../.venv/bin/python -m alembic upgrade head
../../.venv/bin/python -m alembic downgrade -1
../../.venv/bin/python -m alembic upgrade head
```

## D4 pointer — formal CLEAN/RED capture-technique policy doc

The plan's Decision Log (D4) and SPEC Open Question 3 both explicitly defer writing a formal
documented CLEAN/RED capture-technique policy (a single reference doc future capture-point
proposals can be checked against, instead of re-litigating the reasoning each time) to a follow-up
documentation task. This is a **product decision, not a gap found during execution** — tracked here
only as a pointer so it isn't lost. No close command; this is new-doc-writing work, not a test to
re-run. Suggested home when written: `process/context/all-context.md` (Business Guardrails section)
or a dedicated `process/context/{group}/capture-policy.md` if it grows beyond a few paragraphs.

## Close sequence (run once, closes all 3 gaps)

```bash
docker compose -f infra/docker-compose.yml up -d postgres redis
cd apps/pixel && npx playwright install webkit firefox && npx playwright test --project=webkit --project=firefox
cd ../.. && .venv/bin/python -m pytest tests/ -m integration -k "visitor_email or do_not_resolve" -q
cd apps/api && ../../.venv/bin/python -m alembic heads && ../../.venv/bin/python -m alembic upgrade head
```

After running the above green, update `first-party-capture_PLAN_24-07-26.md`'s Closeout section to
`VERIFIED` and move the task folder from `active/` to `completed/`.
