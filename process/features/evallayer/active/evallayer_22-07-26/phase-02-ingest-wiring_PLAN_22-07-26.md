---
name: plan:evallayer-phase-02-ingest-wiring
description: "EvalLayer — Phase 02: Ingest wiring (classify-then-branch in events.py, filter-ordering reconciliation, persist agent visits)"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-02
---

# Phase 02 — Ingest Wiring

**Program:** evallayer
**Umbrella plan:** process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md
**Phase status:** ⏳ PLANNED — checklist locked, VALIDATE complete, ready for EXECUTE
**Report destination:** process/features/evallayer/active/evallayer_22-07-26/phase-02-ingest-wiring_REPORT_22-07-26.md

---

## Purpose

Wire Phase 1's classifier (`apps/api/services/agent_classifier.py`, `apps/api/models/agent_visit.py`
— both shipped) into the live `/events/ingest` hot path in `apps/api/routers/events.py`. Restructure
the branch flow so a recognized AI-agent UA short-circuits past both the `is_bot()` drop AND the
datacenter/proxy-VPN drops (SPEC AC4, Resolved Open Question 3), persists an upserted `agent_visits`
row via a new `apps/api/services/agent_visit_persistence.py` module, and returns 204 without ever
reaching the human `Event` insert or `visitor_aggregator.py` (SPEC AC2). Generic bots/scrapers
continue to be dropped via `is_bot()` exactly as today (SPEC AC3), gated by a new
`agent_detection_enabled` config flag defaulting to `False`.

---

## Entry Gate

- Phase 1 exit gate passed (classifier + schema exist) — **confirmed**: `apps/api/services/agent_classifier.py`
  and `apps/api/models/agent_visit.py` are present and match the RESEARCH-confirmed shape
  (`classify_agent`, `AgentClassification` NamedTuple, `AgentVisit` model with
  `uq_agent_visits_site_vendor_token` unique constraint).

---

## RESEARCH Findings (confirmed this session, folds into checklist below)

1. **`events.py` real line numbers** (re-confirmed against current file, may drift ±1-2 lines from
   original estimate but content matches): UA extraction line 74; `is_bot` drop lines 77-78; site
   lookup/tracking-disabled block lines ~85-117; `ip_address = _extract_ip(request)` line 119;
   datacenter drop lines ~121-129; proxy/VPN drop lines ~131-140; Event insert lines ~156-199;
   `_process_signal_events` call line 225; background aggregate trigger lines 240-250.
2. **`agent_classifier.classify_agent(ua: str | None) -> AgentClassification | None`** — pure,
   stateless, case-insensitive substring match against 4 vendor token sets (openai, anthropic,
   perplexity, bytespider). Always returns `verification_method="ua-only"` in this phase (Phase 4
   adds IP/rDNS tiers). Does NOT reference `bot_filter.py` — fully independent, confirmed no import
   cycle risk.
3. **`AgentVisit` model** — `__tablename__ = "agent_visits"`, unique on
   `(site_id, vendor, product_or_ua_token)`, `page_paths: list[str]` JSONB column explicitly
   documented in the model as **uncapped at schema level — Phase 2 MUST cap it** (confirms Step C's
   `_append_capped_path` requirement is not optional).
4. **No existing monkeypatch fixture for AC4** — grepped `tests/integration/test_events_ingest.py`
   and `tests/unit/`: `is_datacenter_ip`/`check_ip_privacy` monkeypatch patterns exist in
   `tests/unit/test_company_resolver.py` and `tests/unit/test_asn_lookup.py`, but
   `test_events_ingest.py` has no existing fixture that mocks these for an integration-level
   datacenter-flagged-IP scenario. **The AC4 integration test must write its own
   `monkeypatch.setattr("apps.api.services.company_resolver.is_datacenter_ip", ...)` inline** —
   this is net-new integration-test plumbing, not a reuse of an existing fixture. Flagged as a Test
   Infra Improvement below.
5. **`config.py` insertion point confirmed**: `block_datacenter_traffic` / `block_proxy_vpn_traffic`
   live at lines 126-137 with a documented multi-line-comment convention this phase's new flag must
   match.
6. **VALIDATE-confirmed (V2 fan-out, this session): `_BOT_PATTERN` in `apps/api/services/bot_filter.py`
   literally contains `openai|anthropic|gptbot|chatgpt|...perplexitybot|...bytespider`** — i.e. ALL
   FOUR of this phase's vendor classes already match today's bot-drop pattern. This makes Step C2's
   `if classification is None and is_bot(...)` restructure not merely an improvement but
   **mechanically required** to satisfy AC1: without it, a recognized GPTBot/ClaudeBot/PerplexityBot/
   ByteSpider UA is unconditionally dropped by `is_bot()` today, before `classify_agent` is ever
   consulted. Confirmed via direct file read; no plan-drift, design unchanged.
7. **VALIDATE-confirmed: existing test convention** for flag toggling in this codebase is
   `monkeypatch.setattr(settings, "<attr>", <value>)` against the imported `settings` singleton
   (e.g. `tests/integration/test_ai_ask.py`, `test_crm_push.py`). Since `events.py`'s local
   `from apps.api.config import settings as _settings` import binds to the same singleton instance,
   Step D2's plan to monkeypatch `agent_detection_enabled` on `settings` will correctly affect the
   ingest path with no additional wiring — confirmed compatible with existing test infra.

No plan-drift found beyond re-confirming line numbers; INNOVATE's classify-then-branch design
(hard `return` immediately after persisting an agent visit, before any human-path code) is locked
unchanged. Marking Phase Loop Progress Step 1 (RESEARCH) and Step 2 (INNOVATE — approach already
decided, no new alternatives surfaced) both clean; this PLAN-SUPPLEMENT (Step 3) encodes the full
checklist below.

---

## Blast Radius

- `apps/api/routers/events.py` (ingest hot path — `ingest_events` function body restructure)
- `apps/api/services/agent_visit_persistence.py` (**new file**)
- `apps/api/config.py` (new `agent_detection_enabled` flag)
- `tests/unit/test_agent_visit_persistence.py` (**new file**)
- `tests/integration/test_events_ingest.py` (extended with new test class/cases)

No changes to `apps/api/services/bot_filter.py` (RESEARCH confirmed the classifier is additive and
independent — no changes needed there this phase) or `apps/api/services/agent_classifier.py` /
`apps/api/models/agent_visit.py` (Phase 1 artifacts, consumed read-only).

**VALIDATE-confirmed disjoint (V1 registry check, this session):** no overlap with Phase 1's DONE
blast radius (`agent_visit.py`, migration, `agent_classifier.py`, `main.py`, `test_agent_classifier.py`
— all read-only/unmodified here) or Phase 3's planned blast radius (`agents.py`, `schemas/agents.py`,
`dashboard/agents/*`, `layout.tsx`, `api.ts`/`api-types.ts` — none of these files appear in this
phase's list). See registry entry appended this session.

---

## Implementation Checklist

### Step A — Config flag

- [x] A1. In `apps/api/config.py`, add `agent_detection_enabled: bool = False` immediately beside
      `block_datacenter_traffic` / `block_proxy_vpn_traffic` (current lines 126-137), using the same
      multi-line-comment convention. Comment must explain: gates whether recognized AI-agent traffic
      is classified + persisted to `agent_visits`; default OFF until the `agent_visits` migration is
      confirmed applied in prod.

### Step B — New persistence module

- [x] B1. Create `apps/api/services/agent_visit_persistence.py` with:
      - `def _append_capped_path(paths: list[str], new_path: str | None, cap: int = 50) -> list[str]`
        — PURE function. Dedupes (no duplicate path appended if already present — but re-appending
        a seen path still counts as a "recent" visit, so implement as: if `new_path` already in
        `paths`, move it to the end (most-recently-seen ordering) rather than no-op; skip entirely
        if `new_path` is `None` or empty string), then truncate to the last `cap` entries.
      - `async def persist_agent_visit(db: AsyncSession, site_id: str, classification: AgentClassification, ip_address: str, path: str | None) -> None`
        — **VALIDATE-revised design (P1 — plan fix applied this session, replaces the original
        "SELECT ... FOR UPDATE then branch insert/update" design):** use an atomic
        `pg_insert(AgentVisit).on_conflict_do_update(...)` upsert — the exact pattern already used
        twice in this codebase for the same kind of rollup row (`visitor_aggregator.py`'s `Visitor`
        upsert at lines 188-224, and its `Company` upsert at line ~369). Rationale: the originally
        planned "SELECT ... FOR UPDATE, then branch to insert-or-update" has an unhandled race —
        `FOR UPDATE` only locks *existing* rows, so when no row exists yet for a given
        `(site_id, vendor, product_or_ua_token)`, two concurrent first-ever visits can both observe
        "no row" and both attempt an INSERT, and the loser raises a `UniqueViolation`. The atomic
        `ON CONFLICT DO UPDATE` form used elsewhere in this codebase eliminates that race at the DB
        level and is more consistent with repo convention (DRY — reuse the proven pattern instead of
        reinventing manual locking):
        1. `SELECT page_paths FROM agent_visits WHERE site_id = :site_id AND vendor = :vendor AND product_or_ua_token = :token` (no `FOR UPDATE` needed with the upsert form below) to compute
           `new_paths = _append_capped_path(existing_page_paths or [], path)` if a row was found,
           else `new_paths = [path] if path else []`.
        2. `pg_insert(AgentVisit).values(site_id=site_id, vendor=classification.vendor, product_or_ua_token=classification.product_or_ua_token, verification_method=classification.verification_method, ip_address=ip_address, first_seen_at=now, last_seen_at=now, visit_count=1, page_paths=new_paths, resolved_company_id=None).on_conflict_do_update(index_elements=["site_id", "vendor", "product_or_ua_token"], set_={"page_paths": new_paths, "visit_count": AgentVisit.__table__.c.visit_count + 1, "last_seen_at": now, "ip_address": ip_address})`.
           Use the SQL-level `visit_count + 1` expression (not a Python-computed increment) in the
           `set_` clause — this keeps `visit_count` race-free regardless of read staleness, matching
           the same reasoning as the existing `GREATEST(...)` expression in the `Visitor` upsert.
        3. `await db.commit()`.
        - **Documented accepted residual (narrow, non-blocking):** because `new_paths` for the
          `page_paths` column is still computed from a Python-side read taken before the atomic
          upsert, the extremely narrow case of two *first-ever* visits for the same brand-new
          `(site_id, vendor, product_or_ua_token)` tuple landing within the same DB round-trip can
          still cause one request's single `page_path` to be overwritten rather than merged (the
          loser's `ON CONFLICT SET page_paths=...` uses its own stale `new_paths`, computed against
          "no existing row"). `visit_count` remains correct in this case (SQL-level `+1`). This is a
          data-completeness edge case only — it never affects the 204 response, multi-tenancy, or
          human data, and is fail-open safe like everything else in this module. Accepted as a
          documented residual rather than solved with an app-level advisory lock (out of proportion
          for this phase's scope).
      - **FAIL-OPEN (mandatory):** wrap the entire body of `persist_agent_visit` in
        `try/except Exception as exc:` → `logger.warning("agent_visit_persist_failed",
        site_id=site_id, vendor=classification.vendor, error=str(exc))` (log keys/vendor/site_id
        only — NO raw UA string, NO IP address in the log body per PII/GDPR guardrail: never log
        PII or prompt bodies), `await db.rollback()`, return `None`. Never raise — a persistence
        failure must never break the ingest response.
      - Import `AgentClassification` type from `apps.api.services.agent_classifier`; import
        `AgentVisit` from `apps.api.models.agent_visit`.

### Step C — Classify-then-branch restructure in `events.py`

- [x] C1. Immediately after `request_ua = request.headers.get("user-agent", "")` (current line 74),
      add:
      ```python
      from apps.api.config import settings as _settings
      classification = classify_agent(request_ua) if _settings.agent_detection_enabled else None
      ```
      (import `classify_agent` from `apps.api.services.agent_classifier` at module top, alongside
      the existing `from apps.api.services.bot_filter import is_bot` import.)
      **Execute-Agent Instruction (E2, non-blocking cleanup):** this local import duplicates the
      existing `from apps.api.config import settings as _settings` local import later in the same
      function (current line ~125, ahead of the datacenter check). Both bind to the same singleton
      so this is functionally harmless, but consolidate to a single local import near the top of the
      function (matching the file's existing lazy-local-import style) rather than leaving the
      duplicate.
- [x] C2. Change the existing bot-drop block (current lines 77-78) to:
      ```python
      if classification is None and is_bot(request_ua):
          return Response(status_code=204)
      ```
      — when `classification` is not `None`, `is_bot()` is skipped entirely (a recognized agent UA
      that also happens to match `_BOT_PATTERN` — e.g. `gptbot` is literally in `_BOT_PATTERN` today
      — must NOT be dropped once classified; this is exactly the AC1/AC3 split).
- [x] C3. Batch parsing (`_parse_event_batch`) and the site-lookup block (existing, current lines
      ~85-117: unknown site → 403 + cookie purge, tracking-disabled → 204) run UNCHANGED and
      UNCONDITIONALLY for both human and agent paths — both need `site_id` resolved before
      persisting anything.
- [x] C4. Immediately after `ip_address = _extract_ip(request)` (current line 119) and BEFORE the
      datacenter/proxy-VPN drop blocks, insert the agent branch:
      ```python
      if classification is not None:
          agent_path = batch.events[0].page_path if batch.events else None
          await persist_agent_visit(db, batch.site_id, classification, ip_address, agent_path)
          return Response(status_code=204)
      ```
      This is a **hard return** — the agent branch MUST NOT fall through to the datacenter/proxy-VPN
      drops (current lines ~121-140), Client Hints extraction, GeoIP resolution, the `Event` insert
      (current lines ~156-199), `_process_signal_events`, conversion tracking, or the background
      aggregation trigger. This satisfies SPEC AC2 (human tables never polluted) and AC4 (agent
      traffic is never re-dropped by datacenter/proxy-VPN filters, because it never reaches them).
      Import `persist_agent_visit` from `apps.api.services.agent_visit_persistence` at module top.
      **Note (non-blocking, VALIDATE-confirmed):** only the first event's `page_path` in a
      multi-event batch is recorded this phase; subsequent paths in the same batch are not captured.
      Acceptable for v1 (matches the plan's original scope); not a regression against any existing
      behavior since this is new functionality.
- [x] C5. Human path (`classification is None`) continues completely unchanged from current
      behavior: datacenter/proxy-VPN drops → Client Hints → GeoIP → Event insert → signal
      processing → conversion tracking → background aggregation → cookie set → 204 response.

### Step D — Tests (see Verification Evidence for exact commands)

- [x] D1. `tests/unit/test_agent_visit_persistence.py` (new, `pytest.mark.unit`, no deps):
      `_append_capped_path` edge cases — empty list + new path; `None`/empty-string path (no-op,
      list unchanged); exact-duplicate path (moves to end, no length change); exactly-50-entry list
      + new path (still 50, oldest dropped); already-over-50 input (defensive — truncates to last
      50); ordering is oldest-first / most-recent-last.
- [x] D2. `tests/integration/test_events_ingest.py` — new test class (or extend `TestIngestEvents`)
      covering, per SPEC AC1-AC5 (all require `MOCK_EXTERNAL_APIS=true` +
      `agent_detection_enabled=True` monkeypatched on settings for the AC1/AC2/AC4 cases):
      - **AC1** (GPTBot UA + flag ON → one `agent_visits` row + 204): POST with `User-Agent: Mozilla/5.0 (compatible; GPTBot/1.0; +https://openai.com/gptbot)`, assert response is 204 and exactly one row exists in `agent_visits` with `vendor="openai"`, `verification_method="ua-only"`.
      - **AC2** (agent-only batch → zero new `Visitor`/`Event` rows): same request, assert `Visitor`
        and `Event` row counts for the site are unchanged before/after.
      - **AC3** (Googlebot → still 204-dropped, NO `agent_visits` row — regression): existing
        `test_bot_ua_returns_204_silently` must continue passing unmodified; add explicit assertion
        that no `agent_visits` row was created for a Googlebot UA.
      - **AC4** (GPTBot UA + datacenter-flagged IP → visit still persists): monkeypatch
        `apps.api.services.company_resolver.is_datacenter_ip` to return `True` for the test IP
        (net-new fixture — see RESEARCH Finding 4), send the GPTBot request, assert the
        `agent_visits` row is still created (i.e., the agent branch's hard-return happens BEFORE the
        datacenter check, so the monkeypatched `True` is never even consulted for this request).
      - **flag-OFF regression**: `agent_detection_enabled=False` (the default) + GPTBot UA → dropped
        via `is_bot()` exactly as today (0 `agent_visits` rows, 204, byte-identical to pre-Phase-2
        behavior).
      - **AC5 (latency, Hybrid)**: out of scope for this integration file — see Verification
        Evidence below; documented as a Known-Gap in `## Known Gaps (Resolved via Backlog)` below,
        with a backlog stub already created this VALIDATE session.
- [x] D3. Run full unit regression (`tests/unit -m unit`) to confirm zero regressions against the
      716-test baseline noted in the umbrella plan. **VALIDATE-confirmed: this command does NOT
      require Docker/Postgres/Redis and IS runnable in a sandbox without a responsive Docker daemon
      — EXECUTE/EVL must actually run this, it is not part of the Docker-environment known-gap.**

---

## Exit Gate

```bash
# AC1 — Recognized-agent UA persists
MOCK_EXTERNAL_APIS=true .venv/bin/python -m pytest tests/integration/test_events_ingest.py -k "agent" -m integration -q
# Expected: new agent-visit-row assertions pass; 204 response

# AC2 — Human tables unaffected
# (same test run above includes the Visitor/Event count-unchanged assertion)

# AC3 — Generic bots still dropped (regression)
.venv/bin/python -m pytest tests/integration/test_events_ingest.py::TestIngestEvents::test_bot_ua_returns_204_silently -m integration -q
# Expected: existing test passes unmodified; no agent_visits row created

# AC4 — Filter-ordering / datacenter IP not re-dropped
MOCK_EXTERNAL_APIS=true .venv/bin/python -m pytest tests/integration/test_events_ingest.py -k "datacenter_flagged" -m integration -q
# Expected: agent visit persists even when IP monkeypatched as datacenter-flagged

# AC5 — Latency check (Hybrid, Known-Gap this phase — no benchmark harness exists yet)
# No command — documented Known-Gap with backlog stub (see Known Gaps section below); a
# human/CI adds a benchmark comparing ingest p95 with/without agent_detection_enabled before
# this AC is closed.

# Unit regression (runnable in ANY environment, no Docker needed)
.venv/bin/python -m pytest tests/unit -m unit -q
# Expected: 716+ passed, no regressions; includes new test_agent_visit_persistence.py cases
```

- AC1-AC4 pass automated (Docker-dependent — see Test Infra Improvement Notes for this build env).
- AC5 recorded as Known-Gap with an explicit resolution path (see Known Gaps section).
- Unit regression (`tests/unit -m unit`) runs in any environment and must be green before EXECUTE
  is considered done.
- Phase report written to report destination above.

---

## Blockers That Would Justify BLOCKED Status

- Phase 1 exit gate not yet passed (classifier/schema unavailable) — **not applicable, confirmed
  passed this session**.
- Filter-ordering change risks regressing existing datacenter/proxy-VPN drop behavior for non-agent
  traffic — mitigated: the human path (Step C5) is byte-identical to current code; only a NEW
  early-return branch is inserted for `classification is not None`, so non-agent traffic's code path
  is untouched line-for-line.

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [x] 1. RESEARCH — research-agent: prior phase reports read; test context loaded; plan drift checked (see RESEARCH Findings above)
- [x] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written (classify-then-branch with hard return, locked; no new alternatives surfaced this pass)
- [x] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated with exact executable checklist; no Inner Loop Refresh Note needed (this IS the initial supplement pass encoding the locked design)
- [x] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md`; Gate: CONDITIONAL, accepted this session (see Validate Contract below)
- [x] 5. EXECUTE — all checklist items done; unit gates green (9/9 new + 171 regression); integration gates Docker-gated known-gap (collect-clean)
- [x] 6. EVL — independent vc-tester confirmation run: full unit baseline GREEN (725 passed, 2 skipped, +9 vs Phase-1's 716, 0 regressions); classifier 24/24; static safety review confirmed all 3 declared safety properties (hard-return before Event insert, flag-off byte-identical, fail-open persistence). Docker integration tests (5 cases) + AC5 latency remain Known-Gaps (collect-clean, unrun — exact close commands in phase report). EVL HANDOFF SUMMARY written.
- [x] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit deferred to vc-git-manager (not run in this session per explicit instruction)

**Validate-contract required before execute.** Ingest hot path + filter-ordering surface —
VALIDATE may never be skipped for this phase.

---

## Touchpoints

- `apps/api/routers/events.py`
- `apps/api/services/agent_visit_persistence.py` (new)
- `apps/api/config.py`
- `tests/unit/test_agent_visit_persistence.py` (new)
- `tests/integration/test_events_ingest.py`

---

## Public Contracts

- `/events/ingest` external request/response shape is unchanged for both human and agent traffic —
  only internal branching and persistence behavior change. Response is always `204` for both
  dropped-bot, agent-classified, and normal-human paths (matching current behavior); `403` for
  unknown site; `400` for malformed JSON — none of these status codes change.
- New internal contract (not externally visible): `agent_visit_persistence.persist_agent_visit`
  never raises — callers may assume fire-and-forget semantics identical to the existing GeoIP
  best-effort pattern in the same file.

---

## Blast Radius

(See "Blast Radius" section above — duplicated heading removed; canonical section is above the
Implementation Checklist.)

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `_append_capped_path` unit cases (empty/None/dup/exact-50/over-50/ordering) — `.venv/bin/python -m pytest tests/unit/test_agent_visit_persistence.py -m unit -q` | Fully-Automated | Supports AC1 (page_paths cap is a documented schema requirement from Phase 1's model docstring) |
| AC1 integration: GPTBot UA + flag ON → agent_visits row + 204 — `MOCK_EXTERNAL_APIS=true .venv/bin/python -m pytest tests/integration/test_events_ingest.py -k "agent" -m integration -q` | Fully-Automated (Docker-gated known-gap in this build env — no responsive Docker; give exact command for human/CI) | AC1 |
| AC2 integration: agent-only batch → zero new Visitor/Event rows (same test run as AC1) | Fully-Automated (Docker-gated known-gap) | AC2 |
| AC3 regression: `test_bot_ua_returns_204_silently` continues passing + no agent_visits row for Googlebot | Fully-Automated (Docker-gated known-gap) | AC3 |
| AC4 integration: monkeypatched datacenter-flagged IP + GPTBot UA → visit still persists — `MOCK_EXTERNAL_APIS=true .venv/bin/python -m pytest tests/integration/test_events_ingest.py -k "datacenter_flagged" -m integration -q` | Fully-Automated (Docker-gated known-gap; net-new monkeypatch fixture per RESEARCH Finding 4) | AC4 |
| AC5 latency check — no benchmark harness exists this phase | Hybrid → **Known-Gap this phase** (backlog stub written this VALIDATE session; gate stays CONDITIONAL, not silently PASS — see Known Gaps section) | AC5 |
| flag-OFF regression: `agent_detection_enabled=False` + GPTBot → dropped exactly as today, 0 agent_visits rows | Fully-Automated (Docker-gated known-gap) | Regression safety net for AC1/AC3 (not a numbered SPEC AC, but required by the Blockers section above) |
| Full unit regression — `.venv/bin/python -m pytest tests/unit -m unit -q` | Fully-Automated (runs in ANY environment, no Docker needed) | No-regression guard vs 716-test baseline (umbrella plan) |

**Vacuous-green note:** AC5 (latency) has no automated or hybrid gate available this phase — per the
vacuous-green ban, this is recorded as a Known-Gap with a backlog stub (see below), and the AC5 row
in the Exit Gate keeps this phase's overall gate CONDITIONAL until a benchmark harness exists, not
silently PASS.

---

## Known Gaps (Resolved via Backlog)

Pre-classified per V3 known-gap exclusion rule — accepted this VALIDATE session, not silently
passed. Both gaps below are **environment/tooling gaps in a design that is otherwise fully
specified and testable**, not design defects:

- **AC5 — ingest latency benchmark**: no benchmark harness exists in this repo yet to measure
  ingest p95 with/without `agent_detection_enabled`. known-gap: documented as NEW PLAN REQUIRED —
  see `process/features/evallayer/backlog/phase-02-latency-benchmark_NOTE_22-07-26.md` (written
  this VALIDATE session). Forces the phase gate to CONDITIONAL per the vacuous-green ban (a
  developed-behavior AC with zero Fully-Automated/Hybrid gate can never be a silent PASS) — this is
  a classification requirement, not a block on proceeding to EXECUTE.
- **AC1-AC4 + flag-OFF regression integration gates — Docker environment gap**: this build
  environment has no responsive Docker daemon (confirmed live this VALIDATE session — `docker ps`
  timed out with no response). The tests themselves ARE Fully-Automated in design (exact runnable
  commands given above); they simply cannot execute in this sandbox. This is an environment
  availability gap, not a coverage gap — EXECUTE/EVL or CI with Docker must actually run these
  commands and confirm green before the phase is marked ✅ VERIFIED in the umbrella. Unit-tier
  regression (`tests/unit -m unit`) is NOT part of this gap — it runs without Docker and must be
  confirmed green at EXECUTE/EVL.

---

## Test Infra Improvement Notes

- **Docker dependency (this build environment):** all integration-tier gates above (AC1-AC4,
  flag-OFF regression) require the project's docker-compose Postgres+Redis stack
  (`infra/docker-compose.yml`) per `TESTING.md`. This build environment has no responsive Docker
  daemon (confirmed both at PLAN-write time and again this VALIDATE session) — EXECUTE/EVL will
  confirm what it can locally; the exact commands above are what a human or CI with Docker runs to
  close these gates.
- **Net-new monkeypatch fixture needed (AC4):** `tests/integration/test_events_ingest.py` has no
  existing fixture that monkeypatches `apps.api.services.company_resolver.is_datacenter_ip` for an
  integration-level test (confirmed via grep — this pattern only exists in
  `tests/unit/test_company_resolver.py` and `tests/unit/test_asn_lookup.py`). EXECUTE must write
  this fixture inline in the new test rather than reuse one.
- **AC5 latency benchmark harness does not exist.** Backlog stub written this VALIDATE session:
  `process/features/evallayer/backlog/phase-02-latency-benchmark_NOTE_22-07-26.md`. Do not close
  AC5 as PASS on Known-Gap alone; keep CONDITIONAL until a benchmark exists or the user explicitly
  accepts the gap (accepted this session — see Validate Contract below).

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/evallayer_22-07-26/phase-02-ingest-wiring_PLAN_22-07-26.md`
- Last completed step: PVL (Step 4) — full V1-V7 run this session. Gate: CONDITIONAL, accepted
  autonomously (session, /goal execution) — see Validate Contract below.
- Validate-contract status: written this session, Gate: CONDITIONAL (accepted)
- Supporting context files loaded: `evallayer_SPEC_22-07-26.md`, umbrella plan hard-safety
  constraints, `apps/api/routers/events.py`, `apps/api/services/agent_classifier.py`,
  `apps/api/models/agent_visit.py`, `apps/api/services/visitor_aggregator.py:188-224` (confirmed
  aggregator entry point and upsert pattern reused for Step B1's revised design),
  `apps/api/config.py:126-137`, `apps/api/services/bot_filter.py` (confirmed `_BOT_PATTERN` overlap
  with all 4 vendor classes), `tests/integration/test_events_ingest.py`,
  `tests/unit/test_company_resolver.py`.
- Next step: spawn `vc-execute-agent` for Step 5 (EXECUTE) against this plan + validate-contract.
  Execute in checklist order: Step A (config flag) → Step B (persistence module, using the
  VALIDATE-revised `ON CONFLICT DO UPDATE` design) → Step C (events.py restructure) → Step D
  (tests). Run `tests/unit -m unit` locally at EXECUTE time regardless of Docker availability;
  attempt the Docker-gated integration commands and record actual outcome (pass, or confirmed
  Docker-unavailable) in the phase report.

---

## Validate Contract

Status: CONDITIONAL
Date: 22-07-26
date: 2026-07-22
generated-by: inner-pvl: phase-2
supersedes: none — no prior validate-contract existed for this plan; this is the first PVL pass

Parallel strategy: sequential
Rationale: single self-contained phase plan with 4 checklist sections in one blast radius (no
multi-package scope, no 3+ independent directions); Layer 1 dimension checks + Layer 2 section
checks were each run as focused reads/greps within this single VALIDATE session rather than
requiring separate agent spawns — signal score 1/7 (S7: 5 files in blast radius). Full
`vc-agent-strategy-compare` scoring below.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC1 | Recognized AI-agent UA (GPTBot) persists as `agent_visits` row, 204 response | Fully-Automated | `MOCK_EXTERNAL_APIS=true .venv/bin/python -m pytest tests/integration/test_events_ingest.py -k "agent" -m integration -q` | A (proven at EXECUTE/EVL time — Docker-env-gated in this sandbox) |
| AC2 | Agent-only batch produces zero new Visitor/Event rows | Fully-Automated | Same command as AC1 (shared test run, count-unchanged assertion) | A |
| AC3 | Generic bots (Googlebot) still dropped, no agent_visits row (regression) | Fully-Automated | `.venv/bin/python -m pytest tests/integration/test_events_ingest.py::TestIngestEvents::test_bot_ua_returns_204_silently -m integration -q` | A |
| AC4 | Legit/flagged-datacenter agent IP not re-dropped by datacenter filter (filter-ordering) | Fully-Automated | `MOCK_EXTERNAL_APIS=true .venv/bin/python -m pytest tests/integration/test_events_ingest.py -k "datacenter_flagged" -m integration -q` | A |
| flag-OFF regression | `agent_detection_enabled=False` (default) → byte-identical to pre-Phase-2 behavior | Fully-Automated | Same integration file, flag-OFF case (see D2) | A |
| AC5 | No material ingest latency added by classify-then-branch restructure | Hybrid | No benchmark harness exists yet | D — backlog stub: `process/features/evallayer/backlog/phase-02-latency-benchmark_NOTE_22-07-26.md` |
| `_append_capped_path` correctness | Dedup/reorder/cap-at-50 pure function | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_agent_visit_persistence.py -m unit -q` | A |
| Full regression | No regression vs 716-test unit baseline | Fully-Automated | `.venv/bin/python -m pytest tests/unit -m unit -q` (runs without Docker) | A |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

Legacy line form:
- Ingest/persistence: Fully-automated: `MOCK_EXTERNAL_APIS=true .venv/bin/python -m pytest tests/integration/test_events_ingest.py -k "agent" -m integration -q` | hybrid: none | agent-probe: none | known-gap: AC5 latency benchmark documented, backlog stub written
- Unit coverage: Fully-automated: `.venv/bin/python -m pytest tests/unit -m unit -q` (no Docker precondition)

Dimension findings:
- Infra fit: PASS — all file paths and line-number references confirmed against the live repo this session (`events.py` 74/77-78/85-117/119/121-140/156-199 all match); new module path is genuinely new (no collision); config insertion point at `config.py:126-137` matches the documented comment convention. No container/infra/runtime surface touched.
- Test coverage: CONCERN → accepted this session — Docker unavailable in this build environment (confirmed live: `docker ps` timed out with no daemon response) makes AC1-AC4 + flag-OFF regression un-runnable IN THIS SESSION, though they are Fully-Automated by design; AC5 has zero test tier assigned (genuine Known-Gap, not environment-limited) — per the vacuous-green ban this alone forces CONDITIONAL classification. Both gaps are named, justified, and backlog-stubbed (see Known Gaps section in plan). `tests/unit -m unit` full regression is NOT Docker-gated and must actually run at EXECUTE/EVL.
- Breaking changes: PASS — `/events/ingest` external status codes (204/403/400) are unchanged for both human and agent traffic; `bot_filter.py` untouched (read-only, confirmed via blast radius); Phase 1 artifacts (`agent_classifier.py`, `agent_visit.py`) consumed read-only, no signature changes; no downstream consumer of `visitor_aggregator.py` is affected since the agent branch hard-returns before ever reaching it.
- Security surface: PASS — fail-open exception handler logs only `site_id`/`vendor`/`error` (no UA, no IP — matches PII/GDPR guardrail); multi-tenancy preserved (agent branch runs strictly after the existing site-lookup gate that already enforces 403-unknown/204-tracking-disabled, so no existence-leak is introduced); no new auth/secret surface. STRIDE quick pass: UA-based vendor classification can be spoofed (Spoofing) but the consequence is limited to a persisted classification row (matches the existing accepted risk profile of `is_bot()`'s own UA-based detection) — not a privilege or data-access escalation.

Section findings:
- Section A (Config flag): PASS — mechanical feasibility confirmed (exact insertion point + comment convention match); no gaps; no conflicts; risk: none (pure opt-in default-False flag, inert until Step B/C land).
- Section B (Persistence module, new file): CONCERN → resolved via Plan Update (P1) applied this session. Mechanical feasibility: PASS (new file, no naming collision; imports resolve — `AgentClassification`/`AgentVisit` shapes confirmed against live Phase 1 files). Gap found: the original "SELECT ... FOR UPDATE then branch insert/update" design had an unhandled INSERT-vs-INSERT race for a brand-new `(site_id, vendor, product_or_ua_token)` tuple (`FOR UPDATE` does not lock nonexistent rows). Fixed in plan: Step B1 now specifies the atomic `pg_insert(...).on_conflict_do_update(...)` pattern already used twice in this codebase (`visitor_aggregator.py` Visitor + Company upserts), with SQL-level `visit_count + 1` for race-free counting; a narrow, documented, fail-open-safe residual remains for the `page_paths` column on the exact first-ever-visit double-insert collision (accepted, non-blocking — see Step B1 note). Highest-risk edit in the whole plan; mitigation is now written directly into the checklist.
- Section C (Classify-then-branch restructure): PASS — mechanical feasibility confirmed (line numbers verified live; `_BOT_PATTERN` confirmed to already match all 4 vendor classes, which makes this restructure mechanically required for AC1, not optional). Gap found: none material; minor duplicate local-import noted as a non-blocking Execute-Agent Instruction (E2). Conflicts found: none — Step C3 (site-lookup gate) is confirmed to run unconditionally before the agent branch, preserving multi-tenancy. Highest-risk edit: Step C4's hard return (must never fall through to Event insert/aggregator) — mitigated by the explicit "MUST NOT fall through" checklist language and proven by the AC2 integration assertion.
- Section D (Tests): CONCERN → accepted this session (see Test coverage dimension + Known Gaps section above for full reasoning).

Open gaps:
- AC5 latency benchmark: known-gap: documented as NEW PLAN REQUIRED — see backlog/phase-02-latency-benchmark_NOTE_22-07-26.md
- AC1-AC4 + flag-OFF integration gates: environment-limited (Docker unavailable this session); Fully-Automated by design; must be run and confirmed green at EXECUTE/EVL or by CI before the phase is marked ✅ VERIFIED in the umbrella.

What this coverage does NOT prove:
- The `_append_capped_path` unit test and full unit regression (both runnable and required to be green at EXECUTE) do NOT prove the ingest hot-path wiring itself works end-to-end — that requires the Docker-gated AC1-AC4 integration commands, which must be run at EXECUTE/EVL time in an environment with a responsive Docker daemon (or by CI) before this phase can be marked ✅ VERIFIED.
- No automated or hybrid gate proves AC5 (latency) this phase — a benchmark harness does not exist yet; the backlog stub names the exact follow-up work required to close this gap.
- The Section B residual (page_paths overwrite on a first-ever-visit double-insert race) has no dedicated regression test this phase — it is a narrow, accepted, fail-open-safe edge case, not proven absent.

Gate: CONDITIONAL (0 FAILs; 2 concerns — 1 resolved via Plan Update applied this session
[Section B persistence race], 1 accepted as a genuine zero-coverage Known-Gap forcing
CONDITIONAL classification per the vacuous-green ban [AC5 latency] — plus environment-only
Docker-gated integration known-gaps that do not themselves indicate a design defect)
Accepted by: session (autonomous, /goal execution) — accepted concerns, quoted: (1) "AC5 —
ingest latency benchmark: no benchmark harness exists in this repo yet... forces the phase gate
to CONDITIONAL per the vacuous-green ban... this is a classification requirement, not a block on
proceeding to EXECUTE" (backlog stub written this session); (2) "AC1-AC4 + flag-OFF regression
integration gates — Docker environment gap: this build environment has no responsive Docker
daemon (confirmed live this VALIDATE session)... EXECUTE/EVL or CI with Docker must actually run
these commands and confirm green before the phase is marked ✅ VERIFIED." Per orchestration.md
§PVL routing option (c), this in-session acceptance under the active AUTOPILOT CONTEXT decision
policy ("self-decide reversible validation detail; surface only charter hard-stops — none of
which apply to a documented test-coverage gap") makes `PHASE_COMPLETE: VALIDATE` legal without a
further plan-supplement cycle.
