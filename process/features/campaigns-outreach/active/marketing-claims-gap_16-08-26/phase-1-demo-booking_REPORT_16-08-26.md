---
name: report:marketing-claims-gap-phase-1-demo-booking-execute
description: "Phase 1 demo-booking EXECUTE report — code complete, all Fully-Automated gates green, Hybrid gates infra-blocked"
date: 16-08-26
phase: phase-1-demo-booking
status: COMPLETE_WITH_GAPS
feature: campaigns-outreach
plan: process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-1-demo-booking_PLAN_16-08-26.md
metadata:
  node_type: memory
  type: report
  feature: campaigns-outreach
  phase: phase-1
---

# Phase 1 — Demo Booking — EXECUTE Report

**TL;DR:** All checklist items except A2/A4 are done. Every Fully-Automated gate is green
(2832 passed / 2 skipped / 0 failed on the unmarked unit lane; 74 passed on the targeted per-file
gates). The two Hybrid gates (integration lane, migration live round-trip) could NOT run: the Docker
daemon refuses to start in this session, so there is no Postgres on `:5433` and no Redis on `:6379`.
Classification: **CODE DONE**, not VERIFIED.

---

## Pre-Edit Measurements (E16 — mandated)

`git diff --stat apps/api/models/site.py apps/api/routers/sites.py` was run before any edit in this
session. Because a prior pass had already applied the Phase-1 edits on top of the concurrent
site-analysis work, the two are no longer separable by diffstat alone. Verbatim measurement of the
full Phase-1 touch set at session start:

```
 apps/api/agents/campaign_planner.py  |  4 +-
 apps/api/models/site.py              |  6 +++
 apps/api/routers/campaigns.py        | 17 ++++++---
 apps/api/routers/sites.py            |  5 +++
 apps/api/schemas/sites.py            | 44 ++++++++++++++++++++++
 apps/api/services/campaign_sender.py | 73 ++++++++++++++++++++++++++++++------
 6 files changed, 131 insertions(+), 18 deletions(-)
```

No `git stash` / `checkout --` / `restore` / `revert` / `rebase` was run at any point. Git usage was
read-only apart from file edits.

**Drift confirmed as EXPECTED (M-4):** every line number in the plan has moved.
`send_campaign_emails` is now defined at `campaign_sender.py:242` (plan said `:201`); its callers are
`campaigns.py:38,566,614,665,869` (plan said `:38,559,607,658,862`). The unit lane collects 2832
(plan snapshot 2804). Per the plan's own instruction these are drifting snapshots, not anomalies.

---

## What Was Done

**Important context:** a prior execution pass in this worktree had already applied nearly the whole
of Steps A–F before this session began (untracked migration file, four new test files, three backlog
notes, and edits across all six source files). This session's work was: full source-verified audit of
that state against every checklist item and every E-row, correction of the plan checklist, execution
of all gates, and this report. No implementation defects were found in the pre-existing work; it
matches the plan exactly, including the append-only rule, both brace forms, and the `_tidy` sentinel.

| Step | Status | Evidence |
|---|---|---|
| A1 — `Site.booking_url` | DONE | `models/site.py`, `String(500)` nullable, mirrors `leadpipe_pixel_id` style |
| A2 — re-derive head via alembic | **BLOCKED (infra)** | Docker daemon will not start; no PG on `:5433` |
| A2b — committed-parent check | DONE — **now PASSES** | `git ls-files --error-unmatch` on `d7e2b4c81f93` and `c5e1a9b73d20` exits **0**. The plan's STOP rule is satisfied: Phase 0 landed those revisions in `7081402` + `52fa1cb`. |
| A3 — migration | DONE | `apps/api/migrations/versions/e4b1d78c3a05_add_site_booking_url.py`, `down_revision = "d7e2b4c81f93"`, additive-nullable, clean `downgrade` |
| A4 — live round-trip | **BLOCKED (infra)** | same as A2 |
| B1 — validator | DONE | `schemas/sites.py::validate_booking_url` — http(s)-absolute only; rejects `< > " ' )`; rejects any whitespace; ≤500 chars. Reject set matches `link_decorator._URL_RE`'s terminator set exactly. |
| B2 — router wiring | DONE | `routers/sites.py` `update_site`, uniform `if body.booking_url is not None` chain, existing tenancy filter untouched |
| B3 — web field | DONE | `api-types.ts` `booking_url?: string \| null`; `site-settings-dialog.tsx` "Demo booking link" panel incl. the P10 subdomain note |
| C1a — select append | DONE | `Site.booking_url` appended **LAST**; positional consumption `site_row[0..3]` unchanged; `booking_url = site_row[4]` |
| C1b — `_personalize` token | DONE | both `{{booking_link}}` and `{booking_link}` replaced |
| C1c/C1d — compose branches | DONE | `_compose_generic` and `_compose_for_recipient` both accept + forward, appended last with `= None` |
| C1e — `[TEST]` preview | DONE | `campaigns.py` — single query widened to `select(Site.name, Site.booking_url)` with `.first()` + explicit unpack (per E8, not a second query); BOTH `_personalize` call sites updated |
| C1f — parity | DONE | generic branch renders identically; unit-asserted |
| C1g — real send path | DONE | `booking_url=booking_url` passed at the `_compose_for_recipient` call inside `send_campaign_emails` |
| C1h — both generic calls | DONE | both `_compose_generic(...)` calls in the non-verified branch forward it |
| C2 — empty behavior | DONE | resolves to `""`, never `"None"`; mid-sentence / bare / anchor / single-brace cases all covered |
| C2b — byte-for-byte | DONE | `_BOOKING_SENTINEL` (`\x00BOOKINGLINK\x00`) is substituted before `_tidy` and swapped back after, so `_LEFTOVER_HINT` cannot eat a `[...]` span inside the URL. Asserted for a URL with `[`, `(`, trailing `.` |
| C3 — planner prompt | DONE | `{{{{booking_link}}}}` correctly escaped in the JSON `"body"` example + added to `personalization_fields` |
| C3b — planner test | DONE | `tests/unit/test_campaign_planner_prompt.py`, all 9 `.format()` kwargs passed |
| C4 — ordering | DONE | personalize → decorate → footer ordering unchanged (no reordering in the diff) |
| D1/D2 — no new endpoint, no auto-create | DONE | zero code added to `routers/outcomes.py`; no goal write on `booking_url` save |
| D3 — UI affordance | DONE | "Track demo bookings" pre-fills `match_type=prefix`, placeholder `/thanks`, posts to the existing goals endpoint; helper text says "path, not a full URL" |
| D4 — v2 route documented | DONE | in `link_decorator` docstring, the backlog note, and this report (provider webhook → existing HMAC endpoint) |
| E1 — decoration test | DONE | ONE case added to the EXISTING `tests/unit/test_link_decoration.py`; no duplicate file created |
| E2 — docstring | DONE | attribution consequence appended; privacy rationale not restated as link-parsing |
| E3 — backlog note | DONE | `backlog/third-party-link-attribution_NOTE_16-08-26.md` (+ two cross-cutting notes) |
| F1 — caller-set invariant | DONE / PASS | exactly 6 lines, no additions |
| F2 — regression lanes | DONE (unit) / BLOCKED (integration) | see gates below |
| F3 — pytestmark | DONE | all four new files carry an explicit marker |

---

## Test Gate Outcomes

| Gate | Strategy | Result |
|---|---|---|
| `pytest tests/unit/test_campaign_sender_tokens.py …test_campaign_planner_prompt.py …test_campaign_send_booking_link.py …test_link_decoration.py …test_gmail_sender_decoration_parity.py …test_agent_origin_exclusion.py …test_personalize.py -q` | Fully-Automated | **74 passed** in 1.04s |
| `pytest tests/unit -q` (UNMARKED whole-phase lane) | Fully-Automated | **2832 passed, 2 skipped, 0 failed** in 14.75s |
| `grep -rn "send_campaign_emails" apps/api --include="*.py"` (AC-9 caller set) | Fully-Automated | **PASS** — exactly 6 lines: `campaign_sender.py:242` (def) + `campaigns.py:38,566,614,665,869`. No new caller. Line numbers drifted; the SET is unchanged. |
| `git ls-files --error-unmatch` on both parent revisions (AC-8 precondition) | Fully-Automated | **PASS (exit 0)** — the plan's armed STOP rule is now cleared by Phase 0 |
| `validate-plan-artifact.mjs` on the phase plan | Fully-Automated | **PASS** — `failures: []` |
| `pytest tests/integration/test_booking_goal_preset.py -m integration -q --collect-only` | Fully-Automated | **6 tests collected** — imports clean, so the blocker is infra only, not code |
| `pytest tests/integration/test_booking_goal_preset.py -m integration -q` (AC-1/5/6) | Hybrid | **BLOCKED (infra)** — setup error at `sync_engine.connect` |
| `pytest tests/ -m integration -q` (whole-lane) | Hybrid | **BLOCKED (infra)** — 3 failed / 18 passed / **609 errors**, all DB-connection setup errors. Not attributable to this phase. |
| alembic `upgrade head` → `downgrade -1` → `upgrade head` (AC-8) | Hybrid | **BLOCKED (infra)** — never attempted; a bare alembic run would hit Supabase PROD (E2) |
| `[TEST]` preview-send human probe (AC-2a/AC-9) | Agent-Probe | **NOT RUN** — needs a running API + authenticated dashboard session |
| Real Calendly/Cal.com redirect chain | Known-Gap | residual, `needs-live-provider` |
| Web/UI half (B3, D3) e2e | Known-Gap | residual, no Clerk auth-harness in this repo |

### Infra blocker — evidence (E12 compliance)

E12 forbids marking a Hybrid gate environment-blocked without running `lsof` and reporting its
output. Run verbatim:

```
$ lsof -nP -iTCP -sTCP:LISTEN | grep -E ':5433|:6379'
(no output, exit 1)
```

Only a native `postgres` on `:5432` is listening — not the `:5433` container the test conftest
targets, and there is no Redis listener at all. Remediation attempted, three times:

1. `open -a Docker` → no Docker process appeared.
2. `open -a "Docker Desktop"` → VM booted; waited 5 min; `~/.docker/run/docker.sock` never created.
   `console.log` shows an endless `vpnkit-data.sock … data connection closed. Will reconnect in 1s`
   loop.
3. `pkill` + clean relaunch, waited a further 5 min → still `DOWN`.

OrbStack was checked as an alternative runtime: a stale docker context exists but the app is not
installed (`Unable to find application named 'OrbStack'`).

**Deliberately NOT done:** pointing the integration lane at the native `:5432` Postgres. The
integration conftest runs `drop_all`, and per the `getbeam-local-dev-db-rebuild-recipe` memory note
`:5432` is a separate dev database. Repointing it would be an unrequested destructive data mutation
on a database the plan never designates — a hard-stop class action, not a workaround.

---

## Plan Deviations

| # | Deviation | Class | Rationale |
|---|---|---|---|
| 1 | Steps A–F were found already implemented rather than being written by this session | Within blast-radius | A prior execute pass in this worktree had applied them. Audited line-by-line against every checklist item and E-row; matches exactly. No re-implementation. |
| 2 | A2 and A4 not executed | Documented gap | Docker daemon unstartable; evidence above. Both remain unticked in the plan. |
| 3 | Every line-number anchor in the plan has drifted | Expected, not a deviation | The plan labels all such figures drifting snapshots and mandates in-session re-measurement. Done and reported. |
| 4 | A2b's STOP rule is now cleared (plan text still says it will fire) | Favourable state change | Phase 0 committed both parent revisions in `7081402` + `52fa1cb`. `git ls-files --error-unmatch` exits 0. |

**Self-inflicted incident (disclosed):** a scripted checkbox update in this session used a faulty
regex that truncated 31 checklist lines to a single letter. Detected immediately by inspection and
fully restored verbatim from the plan text read earlier in-session; `validate-plan-artifact.mjs`
re-run afterwards returns `failures: []` and the checklist reads correctly. No source file was
touched by that script. Lesson: never regex-rewrite a plan checklist — edit the specific lines.

---

## Test Infra Gaps Found

- **Docker Desktop VM is unstartable on this machine right now** (vpnkit reconnect loop). This
  invalidates, for this session only, the standing repo assumption that "Docker IS available, just
  off PATH". The CLI is indeed off PATH, but the daemon itself also fails to boot. Any future agent
  should run the `lsof` check AND confirm `docker info` succeeds before promising a Hybrid gate.
- `EmailSender` still has no mock-mode branch — already captured in
  `backlog/emailsender-no-mock-branch_NOTE_16-08-26.md`.
- 68 of 160 `tests/unit` files carry no `unit` marker — already captured in
  `backlog/unit-marker-coverage-gap_NOTE_16-08-26.md`.

---

## Hard Safety Constraint — verified intact

`send_campaign_emails` gained **no new caller**. Measured caller set is exactly six lines:
`campaign_sender.py:242` (definition) plus `campaigns.py:38` (import), `:566` (docstring), `:614`,
`:665` (the two approval-gated calls), `:869` (comment). Nothing in this phase creates a path that
bypasses human approval; `{{booking_link}}` renders into a DRAFT only. No auto-send introduced.

---

## Closeout Packet

- **Selected plan:** `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-1-demo-booking_PLAN_16-08-26.md`
- **Finished:** all checklist items except A2/A4; all Fully-Automated gates green.
- **Verified:** AC-2a, AC-2b, AC-3, AC-4, AC-7, AC-9, AC-10 (automated). AC-8's committed-parent
  precondition verified; its round-trip half is not.
- **Unverified:** AC-1, AC-5, AC-6 (integration, infra-blocked), AC-8 round-trip (infra-blocked),
  the Agent-Probe preview send, and both named Known-Gap residuals.
- **Remaining:** start Docker → `docker compose -f infra/docker-compose.yml up -d` → re-run the
  integration lane and the migration round-trip with `DATABASE_URL` pinned to `localhost:5433`.
- **Classification:** `Keep in active/testing` — **CODE DONE**, not VERIFIED. Per the plan's own
  Phase Completion Rules, code-only completion is never VERIFIED.

## Forward Preview

- **Test Infra Found:** Docker daemon unstartable this session; integration lane therefore
  unavailable end-to-end (609 setup errors, none code-attributable).
- **Blast Radius Changes:** none beyond the plan's declared set. 6 source files + 1 migration +
  5 test files (4 new, 1 extended) + 2 web files + 3 backlog notes.
- **Commands to Stay Green:** `.venv/bin/python3.11 -m pytest tests/unit -q` (expect ≥2832 passed).
- **Dependency Changes:** none.
