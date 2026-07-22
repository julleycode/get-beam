---
name: plan:evallayer-phase-01-data-model-classifier
description: "EvalLayer — Phase 01: Data model + agent_classifier.py (new agent-visit surface, migration, drop-vs-classify token split, trust-tier classifier)"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-01
---

# Phase 01 — Data Model + Classifier

**Program:** evallayer
**Umbrella plan:** process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md
**Phase status:** ⏳ PLANNED
**Report destination:** process/features/evallayer/active/evallayer_22-07-26/phase-01-data-model-classifier_REPORT_22-07-26.md

---

## Purpose

Build the foundation substrate for the whole detection chain: a net-new data surface for agent
visits (SPEC D1: separate surface, not a `visitor_type` discriminator) plus a new, pure
`apps/api/services/agent_classifier.py` that classifies known AI-agent vendor tokens WITHOUT
touching or importing `bot_filter.py`'s `_BOT_PATTERN` (confirmed via RESEARCH: no split of the
existing regex is required — the classifier is additive and independent; `bot_filter.py` is
read-only reference in this phase). No ingest wiring happens in this phase — that is Phase 2.

---

## Entry Gate

- Program start — no dependency on any other phase (parallel-safe with Phase 0).

---

## Blast Radius

- `apps/api/models/agent_visit.py` (new file)
- `apps/api/migrations/versions/` (new migration file)
- `apps/api/services/agent_classifier.py` (new file, pure/stateless, no DB)
- `apps/api/main.py` (one new import line, mirroring existing model-registration pattern)
- `tests/unit/test_agent_classifier.py` (new file)
- `apps/api/services/bot_filter.py` — READ-ONLY reference in this phase; not modified

Risk class: schema/migration (net-new table). No auth/billing/API-contract surface touched.
Single-package (backend only), ~4 new files + 1 one-line edit to an existing file.

Confirmed at VALIDATE (22-07-26): claim registered in the program's
`phase-blast-radius-registry.md`; disjoint from Phase 0 (frontend-only, shipped) and Phase 2
(`events.py`, `bot_filter.py`, `config.py`) — no overlap, no conflict.

---

## Implementation Checklist

### Step A — Classifier service (`apps/api/services/agent_classifier.py`, new)

- [ ] A1. Create `apps/api/services/agent_classifier.py`. Define `_VENDOR_TOKENS: dict[str, frozenset[str]]`:
      ```python
      _VENDOR_TOKENS: dict[str, frozenset[str]] = {
          "openai": frozenset({"gptbot", "chatgpt-user", "oai-searchbot"}),
          "anthropic": frozenset({"claudebot", "anthropic-ai", "claude-user", "claude-searchbot"}),
          "perplexity": frozenset({"perplexitybot", "perplexity-user"}),
          "bytespider": frozenset({"bytespider"}),
      }
      ```
      Case-insensitive matching (lowercase the UA before comparing against these lowercase tokens).
- [ ] A2. Define `VERIFICATION_METHODS: tuple[str, ...] = ("ua-only", "ip-verified", "rdns-verified")`
      as a module-level constant (Phase 1 always returns `"ua-only"`; Phase 4 adds the other tiers).
      Execute-agent note (VALIDATE finding): this constant is not consumed for validation within
      Phase 1 itself (verification_method is set as the literal `"ua-only"` string in A4) — that's
      expected; it exists as a forward-declared contract for Phase 4 to import and validate against.
      Do not add enforcement logic against it in this phase.
- [ ] A3. Define `AgentClassification(NamedTuple)` with fields `vendor: str`,
      `product_or_ua_token: str`, `verification_method: str`.
- [ ] A4. Implement `classify_agent(user_agent: str | None) -> AgentClassification | None`:
      - Returns `None` for `None`/empty/whitespace-only UA.
      - Lowercases the UA and substring-matches against every token in `_VENDOR_TOKENS`; on first
        match returns `AgentClassification(vendor=<vendor>, product_or_ua_token=<matched token>,
        verification_method="ua-only")`.
      - Returns `None` for any UA that matches no known vendor token (including generic bots,
        curl/python-requests, headless/puppeteer/selenium/scrapy, `ccbot`, `bedrock-agentcore`,
        `agentcore`, `shap-user` — these stay `bot_filter.py`'s drop-only concern, unchanged; add a
        one-line comment: "non-OpenAI/Anthropic/Perplexity/ByteSpider vendors are v1 backlog per
        SPEC Resolved Open Question 6").
      - **AC13 hard exclusion**: `google-extended` and `applebot-extended` MUST NOT appear anywhere
        in `_VENDOR_TOKENS` (robots.txt-only tokens, never live-traffic UAs per SPEC).
      - Do NOT import, reference, or mutate `apps.api.services.bot_filter._BOT_PATTERN` from this
        module — confirmed independent per RESEARCH; this phase does not modify `bot_filter.py`.
      - Execute-agent note (VALIDATE finding): `bot_filter.py`'s existing `_BOT_PATTERN` regex
        currently also matches `bytespider` (and would match `gptbot`/`claudebot`/`perplexitybot` if
        it ran) — this is expected and unchanged in Phase 1; the classify-vs-drop ordering/branch
        logic that reconciles the two is explicitly Phase 2's "filter-ordering requirement" (SPEC
        AC4). Do not attempt to resolve that ordering here.

### Step B — Model (`apps/api/models/agent_visit.py`, new)

- [ ] B1. Create `apps/api/models/agent_visit.py`:
      ```python
      import uuid
      from datetime import datetime

      from sqlalchemy import String, DateTime, Integer, Index, UniqueConstraint
      from sqlalchemy.dialects.postgresql import UUID, JSONB
      from sqlalchemy.orm import Mapped, mapped_column

      from apps.api.models.database import Base


      class AgentVisit(Base):
          """Aggregate rollup row for one (site, vendor, product_or_ua_token) tuple.

          Structurally separate from Visitor/Event (SPEC D1) — never mixed into
          human visitor data. Upserted by (site_id, vendor, product_or_ua_token)
          as new agent-visit events arrive (Phase 2 wires the upsert; this phase
          only defines the schema).
          """

          __tablename__ = "agent_visits"
          __table_args__ = (
              UniqueConstraint(
                  "site_id", "vendor", "product_or_ua_token",
                  name="uq_agent_visits_site_vendor_token",
              ),
              Index("idx_agent_visits_site_last_seen", "site_id", "last_seen_at"),
          )

          site_id: Mapped[str] = mapped_column(String(50), nullable=False)
          vendor: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
          product_or_ua_token: Mapped[str] = mapped_column(String(50), nullable=False)
          verification_method: Mapped[str] = mapped_column(String(20), nullable=False, default="ua-only")
          first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
          last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
          ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
          # Bounded list of distinct page paths this vendor/token has visited on this
          # site. Phase 2 (ingest wiring) MUST cap this list (e.g. last 50 distinct
          # paths) when appending — no cap is enforced at the schema level here.
          page_paths: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
          visit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
          # No FK constraint in Phase 1 (Phase 5 adds the FK once company-resolution
          # exists) — nullable loose reference only.
          resolved_company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
      ```
      `id`/`created_at`/`updated_at` are inherited from `Base` (`apps/api/models/database.py`) —
      do NOT redeclare them (confirmed convention via `Base(DeclarativeBase)` at
      `apps/api/models/database.py:34`).
      **VALIDATE correction (applied 22-07-26):** the original draft typed `page_paths` as
      `Mapped[list]`. Confirmed at VALIDATE against the sibling JSONB list-column convention in
      `apps/api/models/visitor.py:29` (`pages_visited: Mapped[list[str]] = mapped_column(JSONB,
      default=list)`) and `apps/api/models/segment.py:22` (`recommended_channels: Mapped[list[str]]
      = mapped_column(JSONB, default=list)`) — both type the column `Mapped[list[str]]`, not the
      untyped `Mapped[list]`. Corrected above to `Mapped[list[str]]` to mirror the confirmed repo
      convention (per this file's own B1 instruction: "if one exists, mirror it instead of
      inventing a new shape"). `nullable=False` is kept as an explicit strengthening over the
      sibling convention (which relies on the Python-side `default=list` only) — this is additive
      safety, not a different shape, and matches the migration's DB-level `nullable=False` exactly.
      Before writing the file, confirm no sibling model already uses a different array/JSON-list
      convention for a similar "list of strings" column (grep `JSONB` usage across
      `apps/api/models/*.py`) — if one exists, mirror it instead of inventing a new shape.
- [ ] B2. Register the model for `create_all`/Alembic autogenerate discovery: add
      `from apps.api.models.agent_visit import AgentVisit  # noqa: F401 — register for create_all`
      to `apps/api/main.py`, placed alongside the existing block of similar `# noqa: F401` model
      imports (see the import list starting at `apps/api/main.py:13`) — mirror the exact comment
      style used by the most recently added entry (line 31, `from apps.api.models.outcome import
      ConversionGoal, CampaignClick, Conversion  # noqa: F401 — register for create_all`). Do NOT
      create a `models/__init__.py` registry; none exists today and none should be introduced by
      this phase.

### Step C — Migration (`apps/api/migrations/versions/`, new)

- [ ] C1. Confirm current Alembic head: `apps/api/migrations/versions/b8f3c1d92a47_touchpoint_unique_campaign_visitor_channel.py`
      (`revision = "b8f3c1d92a47"`) is the newest file by mtime as of this plan-supplement pass —
      re-confirm at EXECUTE time in case a newer migration landed on `main` first.
      **VALIDATE re-confirmation (22-07-26):** re-verified — `b8f3c1d92a47` is still the newest
      migration file by mtime (22 Jul 11:01) and no other migration file's `down_revision` points
      to it, so it is confirmed to still be the actual current head with no fork risk. Execute-agent
      MUST still re-check at EXECUTE time per the original instruction, since time may pass between
      VALIDATE and EXECUTE.
- [ ] C2. Generate a new revision file under `apps/api/migrations/versions/` (NOT
      `apps/api/alembic/versions/` — that path does not exist; the plan's earlier draft referenced
      it incorrectly and this supplement corrects it everywhere). New file: a fresh
      `<hash>_add_agent_visits_table.py` with `down_revision = "b8f3c1d92a47"`.
      `upgrade()`:
      ```python
      op.create_table(
          "agent_visits",
          sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
          sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
          sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
          sa.Column("site_id", sa.String(50), nullable=False),
          sa.Column("vendor", sa.String(30), nullable=False),
          sa.Column("product_or_ua_token", sa.String(50), nullable=False),
          sa.Column("verification_method", sa.String(20), nullable=False, server_default="ua-only"),
          sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
          sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
          sa.Column("ip_address", sa.String(45), nullable=True),
          sa.Column("page_paths", postgresql.JSONB, nullable=False, server_default="[]"),
          sa.Column("visit_count", sa.Integer, nullable=False, server_default="1"),
          sa.Column("resolved_company_id", postgresql.UUID(as_uuid=True), nullable=True),
      )
      op.create_index("idx_agent_visits_vendor", "agent_visits", ["vendor"])
      op.create_index("idx_agent_visits_site_last_seen", "agent_visits", ["site_id", "last_seen_at"])
      op.create_unique_constraint(
          "uq_agent_visits_site_vendor_token", "agent_visits",
          ["site_id", "vendor", "product_or_ua_token"],
      )
      ```
      `downgrade()`: drop the two indexes, drop the unique constraint, then `op.drop_table("agent_visits")`.
      Include a one-line docstring cross-referencing this phase/plan path.
- [ ] C3. Do NOT autogenerate blindly — hand-write per the shape above, then run
      `alembic upgrade head` locally (see Verification Evidence) to confirm it applies cleanly
      against the actual model metadata with no drift.

### Step D — Tests (`tests/unit/test_agent_classifier.py`, new)

- [ ] D1. Create `tests/unit/test_agent_classifier.py`, mirroring the structure/style of
      `tests/unit/test_identity_classification.py` and `tests/unit/test_bot_filter.py`
      (parametrized, class-grouped, `@pytest.mark.unit`, pure-function, no DB/network):
      ```python
      """Tests for apps.api.services.agent_classifier.classify_agent."""

      import pytest
      from apps.api.services.agent_classifier import classify_agent


      class TestRecognizedVendors:
          @pytest.mark.parametrize("ua,expected_vendor", [
              ("Mozilla/5.0 (compatible; GPTBot/1.0; +https://openai.com/gptbot)", "openai"),
              ("ChatGPT-User/1.0", "openai"),
              ("OAI-SearchBot/1.0", "openai"),
              ("ClaudeBot/1.0", "anthropic"),
              ("anthropic-ai", "anthropic"),
              ("Claude-User/1.0", "anthropic"),
              ("Claude-SearchBot/1.0", "anthropic"),
              ("PerplexityBot/1.0", "perplexity"),
              ("Perplexity-User/1.0", "perplexity"),
              ("Bytespider", "bytespider"),
          ])
          @pytest.mark.unit
          def test_classifies_known_vendor_tokens(self, ua, expected_vendor):
              result = classify_agent(ua)
              assert result is not None
              assert result.vendor == expected_vendor
              assert result.verification_method == "ua-only"


      class TestDropOnlyTokensReturnNone:
          @pytest.mark.parametrize("ua", [
              "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
              "curl/7.88.1",
              "python-requests/2.31.0",
              "Mozilla/5.0 AppleWebKit/537.36 HeadlessChrome/120.0.0.0 Safari/537.36",
              "Scrapy/2.11.0",
              "ccbot",
              "bedrock-agentcore",
              "agentcore",
              "shap-user",
          ])
          @pytest.mark.unit
          def test_drop_only_tokens_return_none(self, ua):
              assert classify_agent(ua) is None


      class TestAC13ExclusionRobotsTxtOnlyTokens:
          @pytest.mark.parametrize("ua", ["google-extended", "applebot-extended"])
          @pytest.mark.unit
          def test_robots_txt_only_tokens_never_classified(self, ua):
              assert classify_agent(ua) is None


      class TestEmptyOrMissingUA:
          @pytest.mark.parametrize("ua", [None, "", "   "])
          @pytest.mark.unit
          def test_empty_or_none_returns_none(self, ua):
              assert classify_agent(ua) is None
      ```

---

## Exit Gate

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_agent_classifier.py -m unit -v
# Expected: all tests pass — recognized vendor tokens classify correctly (ua-only),
# drop-only/generic-bot tokens return None, AC13 robots.txt-only tokens return None,
# empty/None UA returns None.

docker compose -f infra/docker-compose.yml up -d postgres
PYTHONPATH=. .venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head
PYTHONPATH=. .venv/bin/python -m alembic -c apps/api/alembic.ini downgrade -1
PYTHONPATH=. .venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head
# Expected: migration applies cleanly, downgrade cleanly drops the table/indexes/constraint,
# re-upgrade succeeds — no drift, no error.
```

- Migration applies cleanly (up/down/up); classifier unit tests green.
- Phase report written to report destination above.

---

## Blockers That Would Justify BLOCKED Status

- Schema field shape conflicts with an existing model convention not yet reconciled (e.g. a
  discovered sibling JSONB list-column convention this plan didn't anticipate). — Resolved at
  VALIDATE: sibling convention found (`visitor.py`, `segment.py`) and reconciled in Step B1 above;
  no longer a blocker.
- Alembic head has moved since C1's confirmed revision and the new `down_revision` needs
  re-pointing before EXECUTE.

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [x] 1. RESEARCH — research-agent: prior phase reports read; test context loaded; plan drift checked
- [x] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written
- [x] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated with exact checklist + real
      verification commands; corrected stale `apps/api/alembic/versions/` references to the real
      `apps/api/migrations/versions/` path throughout
- [x] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md`
- [x] 5. EXECUTE — all checklist items done; Fully-Automated gates green; Hybrid migration cycle = Known-Gap (Docker unavailable, EVL to confirm)
- [x] 6. EVL — independent vc-tester re-run: 3/4 gates GREEN (classifier 24/24, registration smoke,
      full regression 716 passed/2 skipped/no regression); 1 gate (live-DB migration up/down/up)
      = KNOWN-GAP, Docker unavailable — same gap as EXECUTE, not newly introduced. EVL HANDOFF
      SUMMARY recorded in the phase report's `## EVL Confirmation` section.
- [x] 7. UPDATE PROCESS — phase report written, umbrella state updated; commit pending (vc-git-manager next)

**Validate-contract required before execute.** Schema/migration surface — VALIDATE may never be
skipped for this phase. Contract written below — Gate: PASS.

---

## Touchpoints

- `apps/api/models/agent_visit.py` (new)
- `apps/api/migrations/versions/` (new migration file)
- `apps/api/services/agent_classifier.py` (new)
- `apps/api/main.py` (one new `# noqa: F401` import line)
- `tests/unit/test_agent_classifier.py` (new)

---

## Public Contracts

- None externally visible yet — this phase is data-model + service-internal only. No API/route
  surface is exposed. `classify_agent()` is an internal service function consumed starting Phase 2.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_agent_classifier.py -m unit -v` — recognized vendor tokens classify to correct vendor + `"ua-only"` | Fully-Automated | AC1 (a recognized AI-agent visit is classified, not dropped) — classifier half of the proof; ingest persistence is Phase 2 |
| Same test file — drop-only/generic-bot tokens (`Googlebot`, `curl`, `python-requests`, headless/scrapy, `ccbot`, `bedrock-agentcore`, `agentcore`, `shap-user`) return `None` | Fully-Automated | AC3 (generic bots continue to be dropped exactly as today) — confirms classifier never claims these as agent visits |
| Same test file — `google-extended` / `applebot-extended` return `None` | Fully-Automated | AC13 (robots.txt-only tokens never appear as detected "visits") |
| Same test file — `None`/empty/whitespace UA returns `None` | Fully-Automated | Defensive coverage for AC1/AC13 (no crash or false-positive on missing UA) |
| `docker compose -f infra/docker-compose.yml up -d postgres` then `alembic -c apps/api/alembic.ini upgrade head` / `downgrade -1` / `upgrade head` | Hybrid (needs local Postgres per `TESTING.md`) | Schema-separation foundation for AC2 (human visitor data never polluted) — proves the new surface exists and is structurally isolated from `Visitor`/`Event`; full AC2 proof (no cross-writes) is Phase 2's ingest-wiring integration test |
| `PYTHONPATH=. .venv/bin/python -c "import apps.api.main; from apps.api.models.database import Base; assert 'agent_visits' in Base.metadata.tables"` | Fully-Automated | Registration/import smoke — proves `AgentVisit` is reachable from the model-import chain so Alembic autogenerate and `create_all` both see it (prerequisite for every later phase) |

---

## Test Infra Improvement Notes

- `tests/unit/test_agent_classifier.py` is new — no prior AI-vendor-specific classification test
  existed before this phase (confirmed by SPEC "Known Constraints / Risks" and RESEARCH test-gap
  analysis). This phase closes that specific gap; broader ingest-level coverage (AC1 full
  persistence proof, AC2 isolation proof) remains Phase 2's responsibility.

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/evallayer_22-07-26/phase-01-data-model-classifier_PLAN_22-07-26.md`
- Last completed step: Step 4 (PVL) — validate-contract written, Gate: PASS
- Validate-contract status: written (22-07-26) — Gate: PASS
- Supporting context files loaded: `evallayer_SPEC_22-07-26.md` (AC1/AC2/AC3/AC13, Resolved Open
  Question 1 + 6), `apps/api/models/database.py`, `apps/api/models/campaign.py`,
  `apps/api/models/visitor.py`, `apps/api/models/segment.py`,
  `apps/api/services/bot_filter.py`, `apps/api/services/identity_classification.py`,
  `apps/api/migrations/env.py`, `apps/api/alembic.ini`, `tests/unit/test_identity_classification.py`,
  `tests/unit/test_bot_filter.py`, `TESTING.md`
- Next step: Spawn vc-execute-agent for Step 5 (EXECUTE) against this plan, in checklist order
  A → B → C → D (A and B may run in either order/parallel since independent; C depends on B;
  D depends on A).

---

## Validate Contract

Status: PASS
Date: 22-07-26
date: 2026-07-22
generated-by: inner-pvl: phase-1

Gate: PASS — no FAILs; 1 CONCERN found and fixed in plan text before finalizing (see Plan updates
applied below); 0 unresolved concerns remain.

### Parallel strategy
Choice: parallel-subagents (for this VALIDATE fan-out) — see rationale below.
Signals: 4/7 — present: S2 (schema/migration surface), S4 (8-phase program classification),
S6 (high-risk class: schema/migration), S7 (5 files in blast radius, meets 5+ threshold).
Dominant signal: S6 (high-risk schema/migration class) drove the extra scrutiny on Section B/C,
but the fan-out itself needed no cross-agent coordination.
Agent count: 8 (4 Layer 1 dimension agents: infra fit, test coverage, breaking changes, security
surface; 4 Layer 2 section agents: Step A classifier, Step B model, Step C migration, Step D tests).
Rationale for overriding the raw 4/7→HIGH threshold: this is single-plan VALIDATE fan-out, not
phase-plan CREATION. Each Layer 2 section agent reviews one checklist step independently with no
mid-review communication needed — the textbook parallel-subagents case (per
`vc-agent-strategy-compare` strategy-by-fit rule: "parallel subagents: right for independent
per-section review with no cross-section communication needed"). Agent-team is reserved for
cases needing live coordination (e.g. cross-phase blast-radius negotiation during phase-plan
creation), which does not apply here — this phase's blast radius was already reconciled against
Phase 0/Phase 2 via the registry, read-only, before this fan-out ran.

### Plan updates applied
- [x] P1 — Corrected `page_paths` model field type from `Mapped[list]` to `Mapped[list[str]]` in
      Step B1's code block, to mirror the confirmed sibling JSONB list-column convention in
      `apps/api/models/visitor.py:29` and `apps/api/models/segment.py:22` (both type as
      `Mapped[list[str]]`). Added an inline VALIDATE-correction note in the plan text so
      execute-agent sees the reasoning, not just the diff. `nullable=False` retained (a defensible
      strengthening consistent with the migration's own `nullable=False` on the same column — not
      a "different shape").
- [x] P2 — Re-confirmed Alembic head (`b8f3c1d92a47`) is still current as of VALIDATE time (newest
      by mtime; nothing chains after it); added a VALIDATE re-confirmation note to Step C1. No
      change to the down_revision value — it was already correct.
- [x] P3 — Added an execute-agent note to Step A2 clarifying `VERIFICATION_METHODS` is a
      forward-declared constant not consumed by validation logic in this phase (Phase 4 will
      import and use it) — prevents an execute-agent from over-engineering enforcement that isn't
      requested.
- [x] P4 — Added an execute-agent note to Step A4 explaining that `bot_filter.py`'s existing
      `_BOT_PATTERN` also matches several of the same vendor tokens (e.g. `bytespider`) and that
      reconciling drop-vs-classify ordering is explicitly out of scope for Phase 1 (SPEC AC4 /
      Phase 2's filter-ordering requirement) — prevents scope creep into Phase 2 territory during
      EXECUTE.
- [x] P5 — Blast Radius section: added a confirmation line noting the claim is registered in
      `phase-blast-radius-registry.md` (newly created this VALIDATE pass — first phase to write to
      it) and confirmed disjoint from Phase 0 and Phase 2.

### Execute-agent instructions
- Step C (migration file creation): before writing the new revision file, re-run
  `ls -t apps/api/migrations/versions/*.py | head -1` to re-confirm `b8f3c1d92a47` is still the
  newest file by mtime. If a newer migration exists on `main`, re-point `down_revision` to that
  new head instead of hand-editing chain order — do not silently proceed with a stale
  `down_revision`.
- Step B (model file): use the corrected `Mapped[list[str]]` type shown in the plan text above
  (not the pre-VALIDATE `Mapped[list]` version) — this is the authoritative version.
- Step D (tests): run `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_agent_classifier.py -m unit -v`
  immediately after writing the test file and the classifier — do not wait until all 4 steps are
  done to get first signal.
- General: do not modify `apps/api/services/bot_filter.py`, `apps/api/routers/events.py`, or
  `apps/api/config.py` in this phase under any circumstance — those are Phase 2's blast radius,
  confirmed disjoint in the registry.

### Test gates (run after each section; regression suite after all sections)

**Step A/D — Classifier + tests**
- Fully-Automated: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_agent_classifier.py -m unit -v` exits 0
  Proves: AC1 (recognized vendor classification), AC3 (drop-only tokens return None), AC13
  (google-extended/applebot-extended exclusion), defensive None/empty-UA handling.
  Failing stub (TDD red-first, per `vc-test-coverage-plan`):
  ```
  test("should classify recognized vendor tokens to correct vendor with ua-only confidence", () => {
    throw new Error("NOT IMPLEMENTED — TDD stub: classify_agent returns AgentClassification for known vendor UAs")
  })
  ```
  (Python-native equivalent: the parametrized `test_classifies_known_vendor_tokens` case in the
  plan's D1 code block IS the red-first target — write `agent_classifier.py` to turn it green.)

**Step B/C — Model + migration**
- Fully-Automated: `PYTHONPATH=. .venv/bin/python -c "import apps.api.main; from apps.api.models.database import Base; assert 'agent_visits' in Base.metadata.tables"` exits 0
  Proves: `AgentVisit` reachable from the model-import chain (registration smoke).
  Failing stub:
  ```
  test("should register AgentVisit on Base.metadata via apps.api.main import chain", () => {
    throw new Error("NOT IMPLEMENTED — TDD stub: add AgentVisit import to apps/api/main.py")
  })
  ```
- Hybrid: `docker compose -f infra/docker-compose.yml up -d postgres` then
  `PYTHONPATH=. .venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head` →
  `downgrade -1` → `upgrade head`, all exit 0
  Precondition: local Postgres container running (per `TESTING.md`).
  Proves: schema-separation foundation for AC2; migration rollback-tested (up/down/up, no drift).

**Regression suite (after all sections complete)**
- `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/ -v` exits 0 (no regression in existing
  unit suite, notably `test_bot_filter.py` and `test_identity_classification.py` remain green and
  unmodified)

What this coverage does NOT prove:
- AC1's full ingest-to-persistence path (no `/events/ingest` integration exists yet — Phase 2)
- AC2's full "no cross-writes" proof (no ingest code exists yet to write to either surface —
  Phase 2's integration test is the actual proof; this phase only proves structural isolation)
- AC4 (filter-ordering vs datacenter/proxy-VPN filters) — no ingest wiring exists yet (Phase 2)
- Any dashboard/API-visible behavior (Phase 3) or verification-tier upgrade beyond `"ua-only"`
  (Phase 4) — `VERIFICATION_METHODS` is declared but not exercised beyond the one literal value
- Live/non-mock behavior of any kind — this phase has no external calls (AC14 is N/A here, not a
  gap: classifier is pure, no external calls to mock)

### High-risk pack
Required: yes — schema/migration is one of the 6 high-risk classes (net-new table + migration).
Required evidence per `vc-risk-evidence-pack`:
- `risk-gate.json` — riskClass: "schema/migration", workDescription: "add agent_visits table",
  approver: vc-validate-agent (this pass), mustStopBeforeFinalize: true
- `verification.json` — must record the up/downgrade/up cycle result (PASS/FAIL) from the Hybrid
  gate above, plus the registration smoke test result
- `review-decision.json` — APPROVE/REJECT with rationale, written by execute-agent (or EVL) once
  the migration cycle is confirmed green
- `context-snippets.json` — cite `apps/api/migrations/versions/b8f3c1d92a47_...py:22-23` (head
  confirmation) and the new migration file's `upgrade()`/`downgrade()` bodies
- `adversarial-validation.json` — not required (no auth-bypass/privilege-escalation/secret
  surface introduced; net-new isolated table with no FK to sensitive data yet)
Colocate artifacts in this task folder's `harness/` subdir per task-folder colocation rule:
`process/features/evallayer/active/evallayer_22-07-26/harness/`.

### Backlog artifacts to create during durable capture
- None required from this phase — all findings were resolved in-plan (see Plan updates applied).
  The two structural deferrals below are already tracked in-program (umbrella SPEC), not new
  backlog items:
  - AC2 full isolation proof — tracked as Phase 2 scope (not this phase's gap)
  - AC4 filter-ordering — tracked as Phase 2 scope (not this phase's gap)

### Known gaps on record
- None new. Test Infra Improvement Notes section (above, pre-existing) already documents that
  broader ingest-level coverage is Phase 2's responsibility — this is a scope boundary, not a gap
  in this phase's own deliverable.

### Dimension findings

- Infra fit: PASS — no container/port/runtime surface touched; all target paths (apps/api/models/,
  apps/api/migrations/versions/, apps/api/services/, apps/api/main.py, tests/unit/) confirmed to
  exist on disk; docker compose `postgres` service name confirmed correct.
- Test coverage: PASS — pytest markers/testpaths confirmed in pyproject.toml; style-mirror targets
  (test_identity_classification.py, test_bot_filter.py) confirmed to exist; all Fully-Automated and
  Hybrid commands confirmed real and runnable; new test file confirmed non-colliding.
- Breaking changes: PASS — net-new table, no existing consumer; no API/route surface exposed this
  phase; main.py edit is additive-only; migration down_revision confirmed to point at the actual
  current head with no fork risk.
- Security surface: PASS — no auth/billing/secrets touched; `ip_address` column follows the same
  storage convention already used by `Visitor.ip_address` (plaintext) and is out of scope for the
  active `pii-at-rest` program (which targets only email/full_name/social-handle columns on 4
  named tables) — not a new gap introduced by this phase.
- Section A — Classifier: PASS — mechanically feasible, no collision; advisory note added
  (VERIFICATION_METHODS forward-declared, not consumed until Phase 4).
- Section B — Model: CONCERN found and FIXED in plan text — `page_paths` typed `Mapped[list]`
  conflicted with the confirmed sibling JSONB list-column convention (`visitor.py`, `segment.py`);
  corrected to `Mapped[list[str]]` (see Plan updates applied P1). Resolved before finalizing — 0
  unresolved concerns remain in this section.
- Section C — Migration: PASS — down_revision confirmed against actual head; up/down/up rollback
  test specified; high-risk class handled per `vc-risk-evidence-pack`.
- Section D — Tests: PASS — mirrors confirmed style conventions; AC2 full-isolation proof correctly
  scoped out to Phase 2 (documented, not a silent gap).

Totals: 0 FAILs / 1 CONCERN (fixed in plan) / 7 PASSes → Net Gate: PASS.

### Accepted by
Accepted by: session (autonomous, /goal execution) — 1 CONCERN found (page_paths type-hint
convention mismatch) was fixed in plan text directly (not deferred), so no concern required
acceptance as a residual; net gate is a clean PASS.
