---
name: plan:marketing-claims-gap-phase-2-icp-fit-scoring
description: "Marketing Claims Gap — Phase 2: deterministic ICP-fit scoring of identified visitors against the site's reviewed ICP profile"
date: 16-08-26
metadata:
  node_type: memory
  type: plan
  feature: campaigns-outreach
  phase: phase-2
---

# Phase 2 — ICP-Fit Scoring

**Program:** marketing-claims-gap
**Umbrella plan:** `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/marketing-claims-gap-umbrella_PLAN_16-08-26.md`
**Date**: 16-08-26
**Complexity**: COMPLEX
**Status**: 🔨 CODE DONE (EXECUTE complete 17-08-26; Hybrid gates BLOCKED-infra — no :5433 listener)
**Report destination:** `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-2-icp-fit-scoring_REPORT_16-08-26.md`

---

## Overview

Beam's copy promises the product tells you which anonymous visitors fit your ideal customer profile.
The ICP data now exists — the (uncommitted) site-analysis feature writes a reviewed
`Site.site_profile` JSONB — but nothing scores a visitor against it. This phase is greenfield: build
a pure, deterministic ICP-fit scorer, persist a 0-100 `icp_fit`, and surface it where it costs the
least: the conviction copy the dashboard already renders.

Two facts shape the whole design:

1. **Provider free-text never string-equals LLM-generated ICP text.** `EnrichmentProfile.job_title`
   is whatever Hunter/Apollo/PDL returned; `site_profile.icp.personas[].role` is whatever Gemini
   wrote. `"VP of Engineering"` vs `"Engineering leader"` will never match with `==`. The matcher
   must normalize and score by keyword overlap, not equality.
2. **No per-visitor LLM call.** Cost and latency rule it out, and it would break the deterministic,
   pure-function philosophy `conviction.py` already follows.

Context: `process/context/all-context.md` (router), `process/context/tests/all-tests.md`,
`process/features/campaigns-outreach/_GUIDE.md`,
`process/features/visitors-identity/_GUIDE.md`.

---

## Entry Gate (BLOCKING)

**Phase 0 — operator precondition.** The entire site-analysis feature is UNCOMMITTED working-tree
code and this phase reads its output as its only ICP source:

- `apps/api/services/site_analysis.py`, `apps/api/services/site_content.py`,
  `apps/api/schemas/site_analysis.py` (new, untracked)
- `apps/api/models/site.py` (+5 `site_profile*` columns, modified)
- `apps/api/routers/sites.py` (modified)
- `apps/api/migrations/versions/c5e1a9b73d20_add_site_profile.py` (new, untracked)

Phase 2 RESEARCH MUST NOT start until either (a) those files are committed, or (b) the user
explicitly states the tree is frozen and accepts the risk. Record the SHA or the freeze decision in
the phase report.

Rationale, not paranoia: a concurrent-session rebase in this exact worktree previously swept
untracked files into an unrelated commit and reverted tracked-file edits.

Verification: `git status --short apps/api/services/site_analysis.py apps/api/models/site.py apps/api/migrations/versions/c5e1a9b73d20_add_site_profile.py` returns empty.

Secondary entry condition: local Postgres reachable on `:5433`
(`lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`).

---

## Locked Decisions

| # | Decision | Alternative considered (rejected) |
|---|---|---|
| D1 | Score against `Site.site_profile` (the **reviewed** column) ONLY. Never `site_profile_candidate` (unreviewed LLM output). | Falling back to the candidate when reviewed is null — rejected: ships unreviewed LLM inference as a product signal. |
| D2 | `icp_fit` is a **separate 0-100 score**, not a multiplier on `intent_score`. | Multiplying intent_score — rejected: identity resolution orders by `intent_score.desc()`, so perturbing it directly reshapes provider budget burn (a known hazard). |
| D3 | New pure module `apps/api/services/icp_fit.py` mirroring `traffic_fit.py`'s structure: a pure estimate function + a pure verdict function + one thin DB-touching function. | Inlining scoring into `visitor_aggregator.py` — rejected: untestable, and couples scoring to the aggregation transaction. |
| D4 | Deterministic normalized/keyword matcher: lowercase, strip punctuation, tokenize, drop stopwords, score weighted keyword overlap per dimension (role, seniority, company size band, industry, geography). No LLM, no embedding call. | Per-visitor LLM classification — rejected on cost/latency. Embeddings — rejected: new infra dependency for v1. |
| D5 | **(rewritten after outer PVL, gap G-1)** Persist **`Visitor.icp_fit`** — a nullable `Float` column on the `Visitor` model (`apps/api/models/visitor.py`), written ONLY by `aggregate_visitors_for_site(db, site_id, since=None)` on its full-recompute branch (`visitor_aggregator.py:499` — the `if since is None:` loop that calls `_upsert_visitor`). This is an exact like-for-like mirror of `intent_score`, which is a `Visitor` column (`models/visitor.py:64`) whose sole writer is that same `since=None` branch (`visitor_aggregator.py:597-600` documents the deliberate absence on the incremental path). It keeps the D7 staleness precedent honest instead of inventing a new one. | (b) Writing `IdentifiedVisitor.icp_fit` from the resolution/enrichment path — **rejected**: `visitor_aggregator.py` contains zero `IdentifiedVisitor` references, so this would introduce new cross-table transaction semantics between aggregation and resolution for no benefit. (c) Compute-on-read in the detail endpoint — **rejected**: the score would not be sortable or filterable, and it repeats work per render. |
| D6 | Flag `icp_fit_enabled`, default OFF. Flag OFF **or** `site_profile` NULL ⇒ `icp_fit` is `None`. No fallback score, no default of 0 (0 means "scored and poor fit", which is a different claim). | Defaulting to 0 or 50 — rejected: fabricates a signal. |
| D7 | Cheapest visible surface = an ICP-fit clause in `conviction.build_conviction` (`conviction.py:35`), which is already pure and already receives `job_title`/`company_name`. Zero extra DB work. | New dashboard panel — deferred; the conviction string is already rendered everywhere. |
| D8 | Score in Python. Do NOT add a JSONB content-query or filter on `site_profile` — its migration explicitly assumed the column is never content-queried. If a query becomes necessary later, plan a GIN index with explicit rationale. | JSONB containment filters — rejected per that assumption. |
| D10 | **UI/conviction copy uses ONLY the fixed band vocabulary from `icp_fit_verdict` (B6)** — e.g. "strong ICP fit" / "partial ICP fit" / "weak ICP fit". Raw LLM-authored `site_profile` strings (persona `role`, `industries[]`, `size_band`, `category`) are NEVER interpolated into the conviction line, the E3 tooltip, or any other rendered copy. `site_profile` is LLM output derived from fetched third-party page content — treat it as untrusted display text, not just untrusted prompt text. | Rendering the matched persona role verbatim ("looks like your 'VP of Engineering' persona") — rejected: injects attacker-influenceable third-party text straight into the dashboard. |
| D11 | **(locked after outer PVL cycle 2, gap F-2.) Geography is scored from `Visitor.country_code` ONLY**, via an explicit ISO-3166 alpha-2 code → country-name + macro-region static `dict` defined inside `icp_fit.py` (pure, no I/O, no new dependency). The expanded name/region tokens are matched against `firmographics.geography[]` with the same B1 normalize + keyword-overlap machinery. `country_code` NULL/unknown ⇒ the geography dimension returns `None` (dropped from both numerator and denominator), **never 0**. | (i) Drop geography from v1 — rejected: it is the only dimension independent of `EnrichmentProfile`, so dropping it collapses the ≥2-dimension floor into "score only when enrichment exists". (iii) Join `IdentifiedVisitor` for real `city`/`region`/`country` — rejected: that is exactly the cross-table coupling D5's rejected-option (b) rules out, and `IdentifiedVisitor` exists only for resolved visitors so it does not rescue the sparse case. |
| D9 | If the ICP text is fed to any prompt (e.g. the segmenter at `agents/segmenter.py:20-53`), it MUST pass through `agents/prompt_safety.py` `wrap_untrusted` — `site_profile` is LLM-generated text. | Direct interpolation — rejected: prompt-injection surface. |

---

## Blast Radius

Risk class: schema/migration (one additive nullable column) + public API contract (additive
detail-only field). No auth, no billing, no send path, no secrets.

- `apps/api/config.py` — **declare `icp_fit_enabled: bool = False` in `Settings` (C0; gap F-4).** Without this the flag has no home and every flag-gated gate is unrunnable.
- `apps/api/services/icp_fit.py` — NEW, pure scorer
- `apps/api/models/visitor.py` — add `Visitor.icp_fit` (nullable Float; D5)
- `apps/api/migrations/versions/<new>_add_visitor_icp_fit.py` — new revision
- `apps/api/services/visitor_aggregator.py` — write `icp_fit` on the full-recompute path
- `apps/api/services/conviction.py` — ICP-fit clause
- `apps/api/routers/visitors.py` — **detail-endpoint data injection ONLY** (one `data["icp_fit"] = ...` line in the detail handler; the list path at `:271` and `VisitorOut` are untouched)
- `apps/api/schemas/visitors.py` — `icp_fit` on **`VisitorDetailOut`** only
- `apps/web/src/lib/api-types.ts` + visitor detail UI — display
- `tests/unit/test_icp_fit.py` (NEW), `tests/unit/test_conviction.py` (NEW — none exists today),
  `tests/integration/test_icp_fit_persistence.py` (NEW)

Approx 11 files + 1 migration.

---

## Touchpoints

Same as Blast Radius. Read-only touchpoints: `apps/api/services/site_analysis.py:239` (the ICP
sanitizer — the authoritative shape source), `apps/api/models/enrichment.py:23-27`
(`job_title`/`seniority_level`/`company_size`/`industry`), `apps/api/models/visitor.py:46`
(`Visitor.country_code`, `String(5)` — the ONLY geo field on `Visitor`, and the sole geography input
per D11), `apps/api/models/visitor.py:196-250` (**the `IdentifiedVisitor` class body** — where
`city`/`region`/`country` actually live; read-only reference, NOT scored, per D11), `apps/api/services/traffic_fit.py` (structural template), `apps/api/config.py:1415` (`site_analysis_enabled: bool = False` — the declaration precedent C0 mirrors) and `apps/api/config.py:1455` (`model_config` carries `"extra": "ignore"`, which is WHY an undeclared flag env var is silently discarded). **`config.py` is a WRITE touchpoint via C0, not read-only.**

---

## Public Contracts

- `VisitorDetailOut` gains optional **`icp_fit: float | None`** — declared `float` to match the
  nullable `Float` column (D5/C1). B5 returns `round(...)`, so values are whole numbers in practice,
  but the declared type is `float` so pydantic performs **no silent int-coercion** of a stored float.
- The detail endpoint (`routers/visitors.py`) explicitly injects `icp_fit` into its response dict
  (E1b). Without that injection the field is permanently `null` — see E1b. **It goes on `VisitorDetailOut`, never on
  `VisitorOut`** — adding a field to the wrong schema class caused the `GET /visitors` 500 (P0) that
  cost this repo a full Docker gate run.
- `conviction.build_conviction`'s **signature is UNCHANGED**: it stays `build_conviction(d: dict) -> str | None`. The new clause reads `d.get("icp_fit")` from the dict that is already passed positionally. **Do NOT add a keyword argument** (gap H-1): both call sites pass a single positional dict (`routers/visitors.py:271` `v.model_dump()`, `:784` `data`), so a kwarg-based implementation would never be supplied at `:784` and the clause would never render — re-creating the F-1 unreachable-surface bug verbatim.
- `intent_score` semantics are UNCHANGED. Identity-resolution ordering
  (`order_by(intent_score.desc())`) is untouched.
- `Site.site_profile` is read-only from this phase's perspective.
- With `icp_fit_enabled=False`, every surface behaves exactly as it does today.

---

## Implementation Checklist

### Step A — Confirm the ICP contract

- [x] A1. Read `apps/api/services/site_analysis.py:239` (sanitizer) and `apps/api/schemas/site_analysis.py` and transcribe the EXACT schema-v1 shape into a module docstring in `icp_fit.py`: `icp: {personas[<=3]: {role, pain}, firmographics: {size_band, industries[], geography[]}}` plus `category` and `sub_industry`. Do not work from this plan's summary — read the source.
- [x] A2. Record what the sanitizer guarantees (max lengths, list caps, allowed keys) so the scorer can trust or defend against each field.
- [x] A3. Confirm no other writer populates `Site.site_profile`.

### Step B — Pure scorer (`apps/api/services/icp_fit.py`)

- [x] B1. `normalize(text) -> tuple[str, ...]`: lowercase, strip punctuation, tokenize, drop a small stopword set. Pure, no I/O.
- [x] B2. `score_role(profile_titles, icp_personas) -> float | None` — weighted keyword overlap between `EnrichmentProfile.job_title`/`seniority_level` and `personas[].role`. Returns `None` when either side is absent.
- [x] B3. `score_firmographics(profile, firmographics) -> float | None` — industry keyword overlap AND size-band keyword overlap. **`size_band` is `str | None` free LLM text, not an enum** (`apps/api/schemas/site_analysis.py`), so match it with the SAME normalize+keyword-overlap machinery as industry (B1). Set/equality membership against `EnrichmentProfile.company_size` will match nothing — do not write it.
- [x] B4. `score_geography(country_code, geography) -> float | None` — **input is `Visitor.country_code` (ISO-3166 alpha-2, `String(5)`), NOT city/region/country: those columns are on `IdentifiedVisitor`, not `Visitor` (D11).** Expand the code through a module-level `_ISO_COUNTRY: dict[str, tuple[str, ...]]` map (code → country-name + macro-region tokens, e.g. `"US" -> ("united", "states", "usa", "north", "america")`), then keyword-overlap those tokens against `firmographics.geography[]` via B1. `country_code` NULL, empty, or absent from the map ⇒ return `None` (dropped from both sides), never 0 — a bare `"us"` vs `"United States"` comparison scores 0 and would drag the weighted average down.
- [x] B5. `estimate_icp_fit(...) -> IcpFitEstimate` — combines the per-dimension scores into 0-100.
  - **Degradation rule (stated inline; do not go looking for a precedent file — see the note under B8):** each dimension contributes `weight_d * score_d` to the numerator and `weight_d` to the denominator. A dimension returning `None` is dropped from BOTH the numerator AND the denominator — it is never scored as 0, and it never shrinks the achievable maximum. Final score = `round(100 * numerator / denominator)`.
  - **Minimum-scored-dimensions floor (added after outer PVL, gap G-2):** if FEWER THAN 2 dimensions returned a non-`None` score, return `None`. Rationale: enrichment lands after resolution, which runs after aggregation, so at full-recompute time most visitors have NO `EnrichmentProfile` row at all — role and firmographics are both `None` and the drop-from-both rule would otherwise yield a **geography-only** number presented to the user as "ICP fit". One dimension is not a fit assessment.
  - If ALL dimensions are `None`, return `None`, not 0 (subsumed by the floor, but assert it explicitly in tests).
- [x] B6. `icp_fit_verdict(estimate) -> str` — a short human phrase band (e.g. "strong fit" / "partial fit" / "weak fit") for conviction copy. Pure.
- [x] B7. Deterministic tie-break / stable ordering everywhere a list is reduced; the same inputs must always produce the same integer.
- [x] B8. Zero DB-session usage, zero network/LLM imports, zero ORM write-path imports in the pure functions.
  **AST-purity test (write from scratch — stated inline):** in `tests/unit/test_icp_fit.py`, parse `apps/api/services/icp_fit.py` with `ast.parse`, walk every `ast.Import` / `ast.ImportFrom`, and assert no imported module name matches a forbidden set (`sqlalchemy`, `httpx`, `requests`, `redis`, `apps.api.database`, `apps.api.models.*`, `apps.api.services.gemini_client`). **Do not cite or look for `apps/api/services/roster_ranking.py` or `tests/unit/test_roster_ranking.py` — neither exists on disk** (only a stale `__pycache__/roster_ranking.cpython-311.pyc`; `all-context.md` records roster-precision Part A as shipped-but-uncommitted and a concurrent-session rebase ate it). This plan is self-contained; nothing here depends on that file.

### Step C — Schema

- [x] C0. **(added after outer PVL cycle 3, gap F-4 — MUST land before Step D.)** Declare the flag in `apps/api/config.py`: `icp_fit_enabled: bool = False`, placed beside the existing `site_analysis_*` block (precedent: `site_analysis_enabled: bool = False` at `config.py:1415`). Default OFF. Add a comment stating it gates ONLY the aggregation second pass (`_score_icp_fit_for_site`) and nothing else.
  **Three breakage modes this prevents, all certain rather than speculative** (verified: `grep -rn "icp_fit" apps/` returns zero matches repo-wide):
  1. D2's `settings.icp_fit_enabled` guard raises `AttributeError` inside the scheduled aggregation sweep — a background job.
  2. `monkeypatch.setattr(settings, "icp_fit_enabled", True)` (F3/AC-6/AC-7/AC-16 — the single toggle the whole Hybrid tier rests on) raises `AttributeError`; pytest refuses to set an attribute that does not exist unless `raising=False` is passed.
  3. The Exit Gate's `ICP_FIT_ENABLED=true` env var is SILENTLY DISCARDED — `Settings.model_config = {"env_file": (...), "extra": "ignore"}` (`config.py:1455`) drops undeclared env keys with no error. This is the exact flag-off-vacuity trap this plan's own Test Infra note warns about (ip-org G8/G10 errata class).

- [x] C1. **(rewritten after outer PVL cycle 2, gap F-3.)** Add `icp_fit: Mapped[float | None] = mapped_column(Float, nullable=True)` to **`Visitor`** in `apps/api/models/visitor.py`, mirroring `intent_score` (`models/visitor.py:64`). **NOT `IdentifiedVisitor`, and NOT `int`** — D5, the Blast Radius, D1's write step and AC-7 all specify a nullable `Float` on `Visitor`; the C3 migration must target the `visitors` table.
- [x] C2. Re-derive the live head FIRST: `DATABASE_URL=postgresql+asyncpg://...@localhost:5433/... .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads`. Phase 1 landed a revision — do NOT chain off a head recorded in any plan.
- [x] C3. Create the migration chaining off the C2 head. Additive nullable column, no backfill.
- [ ] C4. **BLOCKED-infra 17-08-26** — no listener on :5433 (`lsof -nP -iTCP -sTCP:LISTEN | grep -E ':5433|:6379'` → empty); Docker daemon down. Offline `--sql` verified clean both directions instead (`ADD COLUMN icp_fit FLOAT` / `DROP COLUMN icp_fit`). Live round-trip on `:5433` with `DATABASE_URL` pinned: `upgrade head` → `downgrade -1` → `upgrade head`. Never bare alembic — repo `.env` points at Supabase PROD.

### Step D — Persistence

- [x] D1. **(rewritten after outer PVL, gaps G-1/G-6.)** In `apps/api/services/visitor_aggregator.py`, add ONE function — `_score_icp_fit_for_site(db, site_id)` — that runs as a **second pass over the site's visitors, AFTER the `since is None` upsert loop and its `await db.commit()`** — **anchor by SYMBOL, not line number (gap G-A):** place the call immediately after the `since is None` loop's `await db.commit()` (~`:529`), beside the existing post-commit `await revive_returning_unresolvable(...)` call (~`:533`); Phase 1 and Phase 3 both touch this region, so re-locate by those two symbols at EXECUTE time rather than trusting either line number, and call it ONLY from the `since is None` branch of `aggregate_visitors_for_site`. Never from the incremental branch.
  The function must:
  1. Load `Site.site_profile` once (single SELECT). If `None` → return immediately, write nothing.
  2. **BULK-load** every `EnrichmentProfile` for the site in ONE query keyed `(site_id, visitor_id)` and build an in-memory dict `{visitor_id: profile}`. A per-visitor lookup here is an N+1 inside the aggregation path and is explicitly forbidden.
  3. **(rewritten after outer PVL cycle 2, gap F-2 / D11.)** Select the site's `Visitor` rows — `id`, `visitor_id`, **`country_code`** — in one query and join them to that dict in Python. **Do NOT select `city`/`region`/`country`: those columns do not exist on `Visitor` (they are `IdentifiedVisitor` columns, `models/visitor.py:202-204`) and the query would fail at build time.** `country_code` is the sole geography input (D11).
  4. Call the pure `estimate_icp_fit(...)` per visitor and collect `{visitor_id: score}` for non-`None` results only.
  5. Write with ONE bulk `UPDATE` (executemany / `bindparam` update), then commit. Visitors whose score is `None` are skipped entirely — their `icp_fit` is left untouched/NULL, never set to 0.
  Total added queries: 3 reads + 1 write, independent of visitor count.
  6. **(added PVL supplement cycle 4, gap H-7.) WRAP THE CALL IN try/except + `logger.warning`.** The call site sits AFTER the `since is None` commit (~`:529`) but BEFORE `await _resolve_companies(db, site_id)` (~`:549`) on the same branch, so an unhandled raise (malformed `site_profile`, scorer bug, DB hiccup on the bulk UPDATE) propagates out of `aggregate_visitors_for_site`, is swallowed by the scheduler's blanket `except Exception` (`jobs/scheduler.py:502-504`), and the whole site is logged `aggregation_sweep_site_failed` and returned `("skipped", 0)` — a best-effort cosmetic score would suppress IP→company resolution for that site. Mirror `_advance_watermark`'s in-file never-fails-the-run posture (`visitor_aggregator.py:560-575`: try / `await db.rollback()` / `logger.warning("aggregation_watermark_advance_failed", site_id=..., error=str(exc))`). Concretely: `try: await _score_icp_fit_for_site(db, site_id)` / `except Exception as exc: await db.rollback(); logger.warning("icp_fit_pass_failed", site_id=site_id, error=str(exc))`. The rollback is required — an aborted transaction would otherwise poison `_resolve_companies` downstream.
- [x] D2. Guard on `settings.icp_fit_enabled` AND `site_profile is not None`; otherwise write nothing (leave `icp_fit` untouched/NULL). Do not write 0.
- [x] D3. Document the D7 staleness caveat in a code comment at the call site, next to the existing `# DELIBERATELY ABSENT (D7)` block at `visitor_aggregator.py:597`: incremental aggregation does not recompute `icp_fit`, exactly as `avg_time_on_page` and `intent_score` behave today.
  **State the sharper, user-visible form explicitly (gap H-3) — this is a NAMED RESIDUAL, not a bug introduced here:** `icp_fit` **lags enrichment by up to one full-recompute sweep interval.** Role and firmographics both come from the same `EnrichmentProfile` row, and B5's ≥2-dimension floor means a visitor usually needs that row before any score exists at all — but enrichment lands after resolution, which runs after aggregation. So a visitor's `icp_fit` stays NULL until the first FULL-recompute sweep that runs AFTER their enrichment row lands. The lag is **bounded** by the scheduled repair sweep's interval — that sweep calls `aggregate_visitors_for_site(db, site_id, since=None)` at `jobs/scheduler.py:500`. Record this bound in the phase report as a named residual; AC-7's gate seeds enrichment BEFORE aggregating, so it proves the write path but deliberately does NOT prove the production ordering.
- [x] D4. Do NOT introduce any JSONB filter/containment query against `site_profile` (D8).

### Step E — Surface

- [x] E1. Add an ICP-fit clause to `conviction.build_conviction` (`conviction.py:35`), rendered ONLY when `icp_fit` is not `None`. Keep the function pure — the score arrives **inside the already-passed dict** (`d.get("icp_fit")`); the signature is UNCHANGED and NO keyword argument is added (H-1). Do not fetch anything inside. The clause text uses ONLY the `icp_fit_verdict` band vocabulary (D10); never interpolate raw `site_profile` strings.
  **LOCKED PLACEMENT (orchestrator decision, outer PVL cycle 3, gap F-5) — APPEND AFTER THE `parts[:3]` SLICE, beside `intent {score}`.** The final line is `head(≤3 parts) + "intent {score}" + ICP band clause when icp_fit is not None`. Concretely: keep `head = parts[:3]`, keep `head.append(f"intent {score}")`, then `if d.get("icp_fit") is not None: head.append(icp_fit_verdict(...))`, then join. Why this and nothing else:
  - It **displaces nothing** — the existing three behavioural parts and the intent number are untouched.
  - Existing non-ICP output is **byte-identical** to today, so F2's characterization tests stay valid and cannot be invalidated by this change.
  - It is **structurally un-truncatable** — appending after the slice means the clause can never be dropped for enriched, engaged visitors (which is exactly the F-5 failure: `build_conviction` builds up to four `parts`, slices `parts[:3]`, and a fifth part would vanish for precisely the visitors that can carry a score).
  - Deterministic: position is fixed, not data-dependent.
  **Rejected alternatives (recorded, do not revisit):** (i) fixed-index insert into `parts` (e.g. right after the who-they-are part) — rejected: it displaces one existing part out of the `[:3]` window, changing today's output and breaking F2's characterization baseline; (ii) raise the `[:3]` cap for the detail path — rejected: it changes existing conviction lines for every already-shipped visitor, a silent copy regression well outside this phase's blast radius.
  **F2's characterization tests are written against THIS chosen behavior** — capture today's output first, then assert it is unchanged when `icp_fit` is absent, then assert the appended clause when present.
  **The `icp_fit is not None` condition is NECESSARY, NOT SUFFICIENT (added PVL supplement cycle 4, gap H-6).** `build_conviction` returns `None` BEFORE any join when `not parts and score < HIGH_INTENT` (`conviction.py:73-74`; `HIGH_INTENT = 40` at `:22`). That early-return guard is **deliberately UNCHANGED by this phase** — the ICP clause is appended to `head`, which is only built after the guard, so **a non-`None` `icp_fit` never resurrects a null conviction**. A visitor scored on firmographics + geography alone (no `job_title`/`company_name`, `total_sessions < 2`, no hot page, no depth, intent < 40) satisfies B5's ≥2-dimension floor yet still gets no conviction line at all, by design. Do NOT weaken or bypass the guard to make the clause render.
  **This clause is DETAIL-PATH-ONLY, by design.** `build_conviction` is called from BOTH `routers/visitors.py:271` (the LIST path, on a `VisitorOut.model_dump()`) and `routers/visitors.py:784` (the DETAIL path). Because `icp_fit` is exposed on `VisitorDetailOut` only (E2), the list path passes no `icp_fit` key and the clause is simply absent there. That is the intended behavior — the list conviction string is unchanged.
  ⚠️ **DO NOT "fix" the missing list-path clause by moving `icp_fit` onto `VisitorOut`.** Adding a field to the wrong schema class is exactly what caused the `GET /visitors` 500 P0 in this repo (fields present on `VisitorOut` that the canonical-alias select did not provide → `AttributeError` in prod). If the list path genuinely needs the score later, that is a separate plan with its own select-column change.
- [x] E1b. **(added after outer PVL cycle 2, gap F-1 — WITHOUT THIS STEP THE FEATURE IS UNREACHABLE.)** In `apps/api/routers/visitors.py`, inject the score into the detail endpoint's response dict. The handler seeds `data = VisitorOut.model_validate(visitor).model_dump()` (`:693`), so a `VisitorDetailOut`-only field is absent from `data` unless explicitly added — `build_conviction(data)` (`:784`) would never see it AND `return VisitorDetailOut(**data)` would fall back to the field default, leaving the API field permanently `null`.
  Add **one line** — `data["icp_fit"] = visitor.icp_fit` — anywhere between the `data = VisitorOut.model_validate(...)` seed (`:693`) and the `data["conviction"] = build_conviction(data)` call (`:784`), mirroring the existing `data.update({...})` blocks (`:742` from `IdentifiedVisitor`, `:762` from `EnrichmentProfile`).
  **Touch NOTHING else in this file.** Do not add `icp_fit` to `VisitorOut`, and do not touch the list-path `build_conviction` call at `:271` — that is the `GET /visitors` 500 P0 re-creation path (E1's warning).
- [x] E2. Add `icp_fit` to `VisitorDetailOut` in `apps/api/schemas/visitors.py`. **Not** `VisitorOut`.
- [x] E3. Add `icp_fit?: number` to the visitor detail type in `apps/web/src/lib/api-types.ts` and display it on the visitor detail view with the verdict band, plus a tooltip explaining it is computed from the site's reviewed ICP.
  **NAMED RENDER SITE (added PVL supplement cycle 4, gap H-10):** `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` — the existing conviction block renders `{visitor.conviction}` at `:702-707`, immediately below `<IntentRing score={visitor.intent_score} />` at `:697`. That is the band chip's home. Tooltip precedent in the same file: `candidateTooltip` (`:480`) rendered via `title=` (`:594`) — a plain string, no new component needed.
  **Gate split:** the band/tooltip STRING is gated automatically by the F8 vitest leg (band vocabulary only). The remaining VISUAL PLACEMENT (does the chip sit correctly beside the IntentRing, does the existing conviction render not regress) is a **NAMED RESIDUAL, Agent-Probe tier** — record it as such in the phase report; there is no Playwright leg in this phase.
- [x] E4. If (and only if) `site_profile` text is injected into the segmenter prompt (`agents/segmenter.py:20-53`), route it through `prompt_safety.wrap_untrusted` (D9). Otherwise skip and record that no prompt injection point was added.

### Step F — Tests

- [x] F1. `tests/unit/test_icp_fit.py`: normalization; per-dimension scoring; the drop-from-both-sides degradation rule; all-None ⇒ `None`; determinism (same input twice ⇒ identical output); the realistic mismatch case ("VP of Engineering" vs "Engineering leader" scores > 0).
- [x] F2. `tests/unit/test_conviction.py` — NEW FILE; no `test_conviction*.py` exists anywhere today. Cover the pre-existing behavior first (characterization), then the new ICP clause, then absence-of-clause when `icp_fit is None`.
  **MANDATORY CASE (added PVL supplement cycle 4, gap H-6):** a visitor with `icp_fit` set to a real score but NO behavioural parts and `intent_score < 40` (no `job_title`/`company_name`, `total_sessions < 2`, no hot page, no depth) ⇒ `build_conviction` returns `None`. This pins the `conviction.py:73-74` early-return guard as unchanged and proves the ICP clause never resurrects a null conviction.
- [x] F3. `tests/integration/test_icp_fit_persistence.py`: with the flag ON and a real `site_profile`, a full recompute writes a non-null `Visitor.icp_fit`; with the flag OFF, it writes nothing; with `site_profile` NULL, it writes nothing.
  **Flag toggle mechanism (fixed after outer PVL, gap G-5):** each case flips the flag PER TEST with `monkeypatch.setattr(settings, "icp_fit_enabled", True/False)` — the repo idiom (see `tests/unit/test_ads_stub_501.py:48`). A process-level `ICP_FIT_ENABLED=true` env var CANNOT express the OFF case in the same process; the env var is reserved for the whole-suite Exit Gate run only.
  **The flag-ON case is mandatory** — a suite that only ever runs flag-off proves nothing (ip-org errata G8/G10).
- [x] F4. Regression: `intent_score` values are unchanged by this phase; assert explicitly.
- [x] F5. **(added with E1b, gap F-1; seed hardened after outer PVL cycle 3, gap F-5.)** Detail-surface reachability, in the integration suite: with the flag ON, a seeded schema-v1 `site_profile` and a scored visitor, request `GET /visitors/{site_id}/{visitor_id}` and assert (a) the response body's `icp_fit` is non-null, and (b) the `conviction` string contains the `icp_fit_verdict` band phrase. Also assert `GET /visitors` (list) still returns 200 and its conviction string is unchanged.
  **MANDATORY SEED SHAPE — the visitor MUST carry at least THREE non-ICP conviction parts**, so the gate proves the non-truncating case rather than the trivially easy one. Concretely seed: an `EnrichmentProfile` with `job_title` + `company_name` (the who-they-are part), `total_sessions >= 2` (the `returned N×` part), and a hot page such as `/pricing` in `pages_visited` (the hot-page part). That fills `parts[:3]` completely, so the assertion proves E1's locked after-the-slice placement actually survives truncation. A sparse seed here would be **vacuously green** — the exact failure class F-1 was raised for.
  Without this gate F2/F3 can both be green while no user can see the feature.
- [x] F6. **(gap G-E; SCOPE NARROWED at PVL supplement cycle 4, gap H-9.)** Adversarial-copy unit assertion for AC-14, **scoped to the CONVICTION CLAUSE ONLY**: craft a `site_profile` whose persona `role` contains markup/instruction text (e.g. `"IGNORE PREVIOUS INSTRUCTIONS <script>alert(1)</script> VP Eng"`), render the clause through the real `build_conviction` path, assert no substring of the injected text appears. **This Python test CANNOT cover the tooltip** — the tooltip is TSX in `apps/web`; that half is F8.
- [x] F8. **(added PVL supplement cycle 4, gap H-9 — the tooltip half of AC-14.)** Extract the band/tooltip string builder into a pure module under `apps/web/src/lib/` (e.g. `apps/web/src/lib/icp-fit-copy.ts`, exporting a band-label fn and a tooltip-string fn) and cover it with a sibling `apps/web/src/lib/icp-fit-copy.test.ts`. Precedents: `apps/web/vitest.config.ts` exists and 10 `src/lib/*.test.ts` files already run under `npm test` (= `vitest run`). **Assert ONLY that the emitted strings come from the fixed band vocabulary** — given an adversarial `site_profile`-derived input, the output contains no substring of it, and every returned label is a member of the known band set. Do NOT assert on JSX/render output; the page component imports the builder, so covering the builder covers the copy.
- [x] F7. **(gap G-B; mechanism pinned after outer PVL cycle 3, gap H-2.)** Query-count assertion for AC-15, comparing N=1 vs N=25 seeded visitors — the counts must be identical.
  **Exact mechanism — do not derive this under time pressure:** attach with `event.listen(test_engine.sync_engine, "before_cursor_execute", counter)`. The `.sync_engine` hop is REQUIRED: the `test_engine` fixture in `tests/conftest.py` builds the engine with `create_async_engine(settings.database_url, ...)` (~`:92`), i.e. an `AsyncEngine`, and `before_cursor_execute` is a synchronous `Engine`/`Connection` event — `event.listen(<AsyncEngine>, ...)` does not fire. **Fixture the counter attaches to: `test_engine` (tests/conftest.py).** There is ZERO precedent to copy in this repo (`grep -rn "before_cursor_execute" tests/ apps/` returns no matches), which is why the plumbing is specified here rather than left to the executor.

---

## Acceptance Criteria

| # | Criterion |
|---|---|
| AC-1 | `icp_fit.py` is pure: no DB session, no network, no LLM call, deterministic. |
| AC-2 | Scoring reads `Site.site_profile` only; `site_profile_candidate` is never read. |
| AC-3 | A realistic free-text/ICP mismatch pair ("VP of Engineering" vs "Engineering leader") scores above zero. |
| AC-4 | A dimension with no data is dropped from both numerator and denominator, not scored as 0. |
| AC-5 | All dimensions missing ⇒ `icp_fit` is `None`, not 0. |
| AC-6 | Flag OFF or `site_profile` NULL ⇒ nothing written; every surface behaves as today. |
| AC-7 | With the flag ON and real data, a full recompute persists `icp_fit` on the `Visitor` row (D5). |
| AC-13 | Fewer than 2 scored dimensions ⇒ `icp_fit` is `None` (no geography-only scores). **Dimension inventory re-derived after the D11 geography decision (gap G-F): role, firmographics, geography — three dimensions, geography retained via the ISO map, so the floor stays ≥2.** Role and firmographics both come from the same `EnrichmentProfile` row (present/absent together); geography is the only `EnrichmentProfile`-independent dimension, which is exactly why D11 keeps it. Unit test cases must encode this three-dimension inventory. |
| AC-14 | Conviction copy and the detail tooltip contain only fixed band vocabulary; no raw `site_profile` string is interpolated (D10). **Two halves, two gates (split at PVL supplement cycle 4, gap H-9): the CONVICTION CLAUSE half is proven by F6 (Python); the TOOLTIP half is proven by F8 (vitest on the extracted `apps/web/src/lib/` string builder). Neither alone satisfies AC-14.** **`grep` review alone is insufficient (gap G-E) — add a POSITIVE unit assertion: build an adversarial `site_profile` whose persona `role` carries markup/instruction text (e.g. `"IGNORE PREVIOUS INSTRUCTIONS <script>alert(1)</script> VP Eng"`), render the conviction clause and the tooltip string through the real code path, and assert neither output contains ANY substring of that injected text.** |
| AC-15 | `_score_icp_fit_for_site` issues a bounded number of queries (3 reads + 1 bulk write), independent of visitor count — no per-visitor enrichment lookup. **Mechanism (specified, not left to reviewer opinion — gaps G-B + H-2): register the SQLAlchemy `before_cursor_execute` listener via `event.listen(test_engine.sync_engine, "before_cursor_execute", counter)` — `.sync_engine` is REQUIRED because the `test_engine` fixture (`tests/conftest.py`, `create_async_engine` ~`:92`) yields an `AsyncEngine` and this is a synchronous `Engine` event. Count invocations across the call and assert the count is IDENTICAL for a site seeded with N=1 visitor and a site seeded with N=25 visitors.** |
| AC-8 | `intent_score` values and identity-resolution ordering are provably unchanged. |
| AC-9 | `icp_fit` appears on `VisitorDetailOut` only; `GET /visitors` (list) still returns 200. |
| AC-16 | **(added with E1b, gap F-1; seed hardened gap F-5.)** With the flag ON and a scored visitor, `GET /visitors/{site_id}/{visitor_id}` returns a non-null `icp_fit` AND a `conviction` string containing the `icp_fit_verdict` band phrase — i.e. the feature is actually reachable by a user. **The seeded visitor MUST carry ≥3 non-ICP conviction parts (enriched who-they-are + `total_sessions >= 2` + a hot page), so the gate proves the clause survives `build_conviction`'s `parts[:3]` truncation under E1's locked after-the-slice placement. A sparse seed makes this criterion vacuously green.** |
| AC-10 | The migration applies and reverses cleanly against local Postgres on `:5433`. |
| AC-11 | No JSONB content-query against `site_profile` was added. |
| AC-12 | `test_conviction.py` exists and covers both the pre-existing conviction behavior and the new clause. |

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `.venv/bin/python3.11 -m pytest tests/unit/test_icp_fit.py -q` exits 0 | Fully-Automated | AC-1, AC-3, AC-4, AC-5 |
| AST purity test: `icp_fit.py` imports no session/network module | Fully-Automated | AC-1 |
| `.venv/bin/python3.11 -m pytest tests/unit/test_conviction.py -q` exits 0 | Fully-Automated | AC-12 |
| `.venv/bin/python3.11 -m pytest tests/integration/test_icp_fit_persistence.py -q` exits 0 — **precondition: `ICP_FIT_ENABLED=true` for the flag-ON cases, and a seeded `site_profile`; PG on :5433 up** | Hybrid | AC-6, AC-7 |
| `grep -rn "site_profile_candidate" apps/api/services/icp_fit.py apps/api/services/visitor_aggregator.py` returns nothing | Fully-Automated | AC-2 |
| `grep -rn "site_profile" apps/api/ \| grep -iE "contains\|jsonb_\|->>.*=.*"` reviewed and empty of new content-queries | Fully-Automated | AC-11 |
| Integration: `GET /visitors` list endpoint returns 200 after the schema change | Hybrid — precondition: PG :5433 up | AC-9 |
| `DATABASE_URL=<localhost:5433> ... alembic upgrade head / downgrade -1 / upgrade head` | Hybrid — precondition: local PG up; `DATABASE_URL` pinned (bare alembic hits PROD) | AC-10 |
| Intent-score regression assertion in the integration suite | Fully-Automated | AC-8 |
| Unit case: one scored dimension ⇒ `None`; two ⇒ an int | Fully-Automated | AC-13 |
| `grep -n` review of the conviction clause + tooltip source: only `icp_fit_verdict` output is interpolated (necessary but NOT sufficient — F6 is the proving gate) | Fully-Automated | AC-14 |
| Integration: `GET /visitors/{site_id}/{visitor_id}` with flag ON returns non-null `icp_fit` AND a `conviction` containing the band phrase (F5) | Hybrid — preconditions: PG :5433 up; `icp_fit_enabled` DECLARED in `config.py` (C0); per-case `monkeypatch.setattr(settings, "icp_fit_enabled", True)`; seeded schema-v1 `site_profile`; **seeded visitor carries ≥3 non-ICP conviction parts** | AC-16 |
| `grep -n "icp_fit_enabled" apps/api/config.py` returns the declaration (C0) | Fully-Automated | AC-6, AC-7, AC-16 (precondition for every flag-gated gate) |
| Unit: adversarial `site_profile` persona role ⇒ rendered **conviction clause** contains none of the injected text (F6) | Fully-Automated | AC-14 (clause half) |
| `cd apps/web && npm test` — vitest on `src/lib/icp-fit-copy.test.ts`: band/tooltip builder emits ONLY fixed band vocabulary, no `site_profile` substring (F8) | Fully-Automated | AC-14 (tooltip half) |
| Unit/integration: force `_score_icp_fit_for_site` to raise ⇒ the aggregation sweep still completes and `_resolve_companies` still runs (D1.6 try/except) | Fully-Automated | Sweep resilience (H-7) |
| Unit: `build_conviction` returns `None` for a scored visitor with no behavioural parts and intent < 40 — the ICP clause does NOT resurrect a null conviction (F2 case, H-6) | Fully-Automated | AC-12 |
| Integration: `before_cursor_execute` counter attached via `event.listen(test_engine.sync_engine, ...)`, N=1 vs N=25 seeded visitors ⇒ identical count (F7) | Hybrid — precondition: PG :5433 up | AC-15 |
| Unit: `score_geography` returns `None` (not 0) for NULL/unmapped `country_code`; scores > 0 for `"US"` vs `"United States"` via the ISO map (D11) | Fully-Automated | AC-4, AC-13 |
| Agent probe: open a visitor detail page with a scored visitor; judge whether the conviction clause reads truthfully and does not overclaim | Agent-Probe | AC-12 (copy quality — cannot be mechanically asserted) |

Failing stub (AC-3/AC-4/AC-5, fully-automated):

```
test("estimate_icp_fit scores fuzzy role matches, drops missing dimensions, returns None when all absent", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: icp_fit scoring core")
})
```

Failing stub (AC-6/AC-7, fully-automated portion):

```
test("icp_fit written only when flag ON and site_profile present", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: icp_fit persistence gating")
})
```

Failing stub (AC-12, fully-automated):

```
test("build_conviction renders ICP clause only when icp_fit is not None", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: conviction ICP clause")
})
```

---

## Test Infra Improvement Notes

- `test_conviction.py` does not exist anywhere in the repo — `conviction.py` is consumed by the
  dashboard with zero coverage. F2 closes this; write characterization tests for the existing
  behavior before adding the new clause.
- Flag-off vacuity is the dominant risk here. Every integration gate must name whether it runs with
  `ICP_FIT_ENABLED` on or off, and at least one must run ON.
- Docker IS available at `/Applications/Docker.app/Contents/Resources/bin/docker` (off `PATH`);
  detect via `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`.
- Unit tests assume no local Redis on 6379; a stray container makes some unit tests self-poison. If
  unit tests fail deterministically cross-run, check listeners before blaming code.
  **This hazard is LIVE right now** — 6379 has a listener in this worktree. The unit-baseline
  capture step must run the `lsof` listener check first and record the result in the phase report;
  a baseline taken without that record is not comparable.
- **Surface-reachability gap class (found at outer PVL cycle 2):** a unit test that constructs its own
  dict for `build_conviction`, plus an integration test that asserts DB state, can BOTH be green while
  the feature is invisible to every user. Any future phase adding a `VisitorDetailOut`-only field must
  carry an end-to-end response-body gate (F5 here), not just a scorer test plus a persistence test.
- **Undeclared-flag vacuity (found at outer PVL cycle 3):** `Settings.model_config` carries `"extra": "ignore"` (`config.py:1455`), so a `FOO_ENABLED=true` env var for a flag that was never declared in `Settings` is dropped with NO error — the suite runs entirely flag-OFF and passes. Any future phase introducing a feature flag must declare it in `config.py` in the same plan and add a `grep` gate proving the declaration exists.
- **`before_cursor_execute` has zero precedent in this repo** (`grep -rn "before_cursor_execute" tests/ apps/` → no matches). The `AsyncEngine` → `.sync_engine` hop is easy to get wrong; F7 is the first instance, so treat it as reusable infra for future query-count gates.
- **Cross-runtime coverage split (found at outer PVL cycle 4):** a copy-safety rule spanning Python-rendered AND TSX-rendered text cannot be proven by one Python assertion. The cheap fix used here (F8) is to extract the string builder into `apps/web/src/lib/` and cover it with vitest — `apps/web` already has `vitest.config.ts` and 10 `src/lib/*.test.ts` files. Any future phase whose copy rule crosses the api/web boundary should do the same rather than declaring the web half a known-gap.
- **Best-effort passes inside a shared sweep need exception containment (H-7).** `aggregate_visitors_for_site` has a blanket caller-side `except Exception` (`jobs/scheduler.py:502-504`), so any new pass added mid-function can silently skip everything downstream of it. `_advance_watermark` (`:560-575`) is the in-file precedent for the correct posture.
- `roster_ranking.py` / `test_roster_ranking.py` are NOT on disk (only a stale `.pyc`). The
  degradation rule and the AST-purity test are restated inline in B5/B8 so this plan needs no
  external precedent file.

---

## Exit Gate

```bash
git status --short apps/api/services/site_analysis.py apps/api/models/site.py apps/api/migrations/versions/c5e1a9b73d20_add_site_profile.py
# Expected: empty (Phase 0 precondition met) — or a recorded freeze decision in the phase report

lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'
# Expected: listener on 5433.
# ALSO REQUIRED (gap G-10): record whether 6379 has a listener BEFORE capturing the unit
# baseline, and write that state into the phase report. Redis IS currently listening in this
# worktree, and a stray Redis makes some unit tests self-poison db15 cache and fail
# deterministically cross-run. Either stop the container first, or record it and treat any
# cache-shaped unit failure as environmental until proven otherwise.

.venv/bin/python3.11 -m pytest tests/unit -q
# Expected: exit 0, no new failures vs this session's baseline
# (baseline captured WITH the 6379 listener state recorded, per the note above)

ICP_FIT_ENABLED=true .venv/bin/python3.11 -m pytest tests/integration -q
# Expected: exit 0 — and the icp_fit persistence tests actually exercised the ON path

DATABASE_URL=postgresql+asyncpg://USER:PW@localhost:5433/DB .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads
# Expected: single head equal to the new icp_fit revision

node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-2-icp-fit-scoring_PLAN_16-08-26.md
# Expected: failures: []
```

- All checklist items checked
- AC-1..AC-16 met or recorded as known-gaps with rationale
- Phase report written; execution changes committed before Phase 3 starts

---

## Phase Completion Rules

- 🔨 CODE DONE — checklist complete, unit tests green.
- 🧪 TESTING — Fully-Automated + Hybrid gates run with the flag ON for at least the persistence path.
- ✅ VERIFIED — all gates green with preconditions satisfied, validate-contract recorded, AND the
  User Confirmation required: the user has user-confirmed the conviction copy reads truthfully (AC-12 agent probe). A gate that passes
  only because `icp_fit_enabled` is OFF does not count toward VERIFIED.
- 🚧 BLOCKED — see Blockers below.

Code-only completion is `CODE DONE`, never `VERIFIED`.

---

## Blockers That Would Justify BLOCKED Status

- Phase 0 unmet: the site-analysis working tree is still uncommitted and the user has not explicitly
  frozen it. This is a hard entry gate — do not proceed and do not commit those files on the
  agent's own authority.
- `Site.site_profile` shape differs materially from the schema-v1 shape recorded in A1 — re-plan the
  matcher rather than guessing at fields.
- `alembic heads` returns more than one head — re-chain off the true live head; stop if ambiguous.
- Achieving a useful score would require per-visitor LLM calls — that violates D4; stop and re-scope
  rather than adding a hot-path model call.

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner
loop `R → I → P → PVL → E → EVL → UP` SKIPS SPEC.

- [x] 0. ENTRY GATE — Phase 0 precondition recorded (site-analysis committed, or freeze accepted)
- [ ] 1. RESEARCH — research-agent: prior phase reports read; test context loaded; plan drift checked
- [ ] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: this phase plan updated; Inner Loop Refresh Note if sections changed (or "n/a — research clean")
- [ ] 4. PVL — vc-validate-agent: full V1–V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md`
- [x] 5. EXECUTE — all checklist items done; per-section test gates run and green (or gaps documented)
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate Contract`
reads "(placeholder — vc-validate-agent writes this section before EXECUTE)", the orchestrator must
spawn vc-validate-agent first. A partial contract missing Plan updates applied / Execute-agent
instructions / Test gates is treated as a placeholder.

---

## Resume and Execution Handoff

1. Selected plan file path: `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-2-icp-fit-scoring_PLAN_16-08-26.md`
2. Last completed step: not started (blocked on Phase 0 entry gate)
3. Validate-contract status: **CONDITIONAL as of PVL cycle 4 re-validate (outer-pvl, 2026-08-16)** — 0 FAILs, 6 CONCERNs (H-5 environmental Redis; H-6 conviction early-return not an iff; H-7 no exception containment for the new sweep pass; H-8 umbrella shared-file table stale re `config.py`; H-9 AC-14 tooltip half unprovable in a Python test; H-10 E3 web display unnamed + ungated). Both cycle-3 FAILs are RESOLVED and re-verified against source: F-4 → Step C0 declares `icp_fit_enabled: bool = False` (precedents `config.py:1415` and `:1455` confirmed exact); F-5 → E1's append-after-the-`parts[:3]`-slice placement is structurally un-truncatable against real `conviction.py:76-78`, and the AC-16/F5 ≥3-non-ICP-part seed is confirmed achievable through the detail dict. All four cycle-3 CONCERNs (H-1 kwarg, H-2 `.sync_engine`, H-3 sweep-lag residual) are RESOLVED. NOT self-accepted — acceptance or supplement cycle 4 is the orchestrator's call. **(Prior cycle-2/3 notes follow.)** Validate-contract status: BLOCKED as of PVL cycle 2 (outer-pvl).
4. Supporting context files loaded: `process/context/all-context.md`,
   `process/context/tests/all-tests.md`, umbrella plan, Phase 1 report (once written)
5. Next step: re-run PVL from V1 against this supplemented plan. Confirm the Phase 0 entry
   gate before RESEARCH (Step 1). Do not `ENTER EXECUTE MODE` until PVL writes a PASS contract.

---

## Next Step

PVL cycle 4 re-validate is complete: **Gate: CONDITIONAL**, 0 FAILs, 6 CONCERNs (H-5…H-10). The
orchestrator chooses between (a) accepting H-6…H-10 as documented residuals and proceeding, or
(b) running PVL supplement cycle 4 against the SUPPLEMENT REQUEST in the contract below. Then
confirm the Phase 0 entry gate and run the inner loop from RESEARCH.
`ENTER EXECUTE MODE` only after this CONDITIONAL is explicitly accepted (3 fix cycles are already
recorded in `results.tsv`, so the mechanical gate is satisfied).

---

## Execute Anchor Note

This file IS the primary execute anchor for this phase (filename begins with `phase-` but this is a
direct `*_PLAN_*.md` artifact, not a legacy multi-file plan). Supporting phase files: the umbrella
plan `marketing-claims-gap-umbrella_PLAN_16-08-26.md` and the sibling phase plans in the same task
folder — pass them as context only, never as the execute target.

---
## Validate Contract

Status: CONDITIONAL
Date: 16-08-26
date: 2026-08-16
generated-by: outer-pvl
supersedes: 2026-08-16 (outer-pvl) — re-validated from V1 after PVL supplement cycle 3 (2 FAILs + 4 CONCERNs addressed); this contract has current evidence

Parallel strategy: sequential
Rationale: 5/7 signals (S1 multi-package `apps/api` + `apps/web` + `tests`, S2 schema + public-API surface, S4 phase program, S6 high-risk class schema/migration + public API, S7 11 files + 1 migration). Score is HIGH, but this phase's steps are strictly serial (config flag → schema → persistence → surface → tests) and both shared files (`api-types.ts`, and now `config.py` — see H-8) are additive-only against a phase that lands first. One opus execute-agent working the checklist in order beats any fan-out.

Fan-out note: this validate-agent has no Agent tool in this environment, so the Layer 1 / Layer 2 fan-out ran sequentially in-session rather than as parallel subagents. Every finding below is backed by a source read cited inline.

### What supplement cycle 3 actually fixed (each re-verified against source this cycle)

Both cycle-3 FAILs and all four CONCERNs are genuinely resolved. Every claim was re-checked against the file, not against the prior contract:

- **F-4 (flag has no home) → RESOLVED.** New Step C0 declares `icp_fit_enabled: bool = False` in `apps/api/config.py`, `config.py` is now in BOTH the Blast Radius (line 94) and Touchpoints (line 117, explicitly marked a WRITE touchpoint). Both cited precedents are exact: `site_analysis_enabled: bool = False` is literally at `config.py:1415`, and `model_config = {"env_file": ("../../.env", ".env"), "extra": "ignore"}` is literally at `config.py:1455` — so C0's three stated breakage modes (AttributeError in the sweep, `monkeypatch.setattr` raising, env var silently discarded) are all correctly diagnosed. `grep -rn "icp_fit" apps/ tests/` still returns zero matches, confirming greenfield.
- **F-5 (clause truncated away) → RESOLVED, and the fix is verified structurally sound against source.** `conviction.py` is exactly as described: at most four `parts` accumulate (who-they-are `:42-49`; `returned N×` `:52-54`; hot page / page count `:57-62`; `read deeply` `:65-68`), then `head = parts[:3]` (`:76`), `head.append(f"intent {score}")` (`:77`), `" · ".join(head)` (`:78`). E1's LOCKED append-after-the-slice placement is therefore un-truncatable by construction — `parts[:3]` returns a new list, so appending to `head` cannot be re-sliced — and existing non-ICP output stays byte-identical, so F2's characterization baseline holds. The two rejected alternatives are correctly characterised.
- **AC-16 / F5 seed hardening → RESOLVED and mechanically achievable.** The mandated ≥3-non-ICP-part seed fills `parts[:3]` exactly: `job_title` + `company_name` reach the detail dict via `data.update({...})` from `EnrichmentProfile` (`routers/visitors.py:761-772`); `total_sessions` and `pages_visited` reach it via `VisitorOut.model_validate(visitor).model_dump()` (`:693`) — both fields are on `VisitorOut` (`schemas/visitors.py:15,18`); and `"pricing"` is a real `_HOT_PAGES` needle (`conviction.py:12`). So the gate genuinely proves the non-truncating case rather than the easy one.
- **H-1 (kwarg contradiction) → RESOLVED.** Public Contracts now states the signature is UNCHANGED and the clause reads `d.get("icp_fit")`; the kwarg option is deleted from both Public Contracts and E1. Source confirms `def build_conviction(d: dict) -> str | None` (`conviction.py:35`) and both call sites pass one positional dict (`routers/visitors.py:271`, `:784`).
- **H-2 (query-counter plumbing) → RESOLVED.** F7/AC-15 now pin `event.listen(test_engine.sync_engine, "before_cursor_execute", counter)` and name the fixture. Source confirms `test_engine` is built with `create_async_engine(...)` at `tests/conftest.py:92`, and `grep -rn "before_cursor_execute" tests/ apps/` still returns zero matches — the plumbing genuinely had to be specified here.
- **H-3 (staleness understated) → RESOLVED.** D3 now carries the bounded residual. The bound is exact: `aggregate_visitors_for_site(db, site_id, since=None)` is at `jobs/scheduler.py:500`, and it is the ONLY `since=None` caller in the repo (`tasks/aggregation_tasks.py:43` and `routers/events.py:952` both pass a real `since`), so "one full-recompute sweep interval" is a true upper bound rather than a guess.
- Persistence anchors re-verified live this cycle: `if since is None:` loop `visitor_aggregator.py:499`, `await db.commit()` `:529`, `await revive_returning_unresolvable(...)` `:533`, `# DELIBERATELY ABSENT (D7)` `:597`. `Visitor.country_code` `models/visitor.py:46`; `intent_score: Mapped[float] = mapped_column(Float, default=0.0)` `:64`. `Index("uq_enrichment_site_visitor", "site_id", "visitor_id", unique=True)` `models/enrichment.py:15`. `Firmographics{size_band: str|None, industries[], geography[]}` `schemas/site_analysis.py:25-28`. `monkeypatch.setattr(settings, "ad_audiences_enabled", True)` idiom `tests/unit/test_ads_stub_501.py:48`.
- One new positive finding: the watermark is untouched by this phase — `_advance_watermark` runs only `if since is not None` (`visitor_aggregator.py:539`), so the new `since is None`-only second pass cannot perturb incremental-aggregation bookkeeping.

Zero FAILs this cycle. Six CONCERNs — four of them new, in surfaces the prior three cycles never opened (the web display leg, the sweep's exception path, and the umbrella's shared-file table).

### Test gates

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1, AC-3, AC-4, AC-5 | Pure scorer: normalization; fuzzy role overlap ("VP of Engineering" vs "Engineering leader" > 0); a `None` dimension dropped from BOTH numerator and denominator; all-`None` ⇒ `None`; byte-identical output on repeat input | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_icp_fit.py -q` exits 0 | B |
| AC-1 | `icp_fit.py` imports no DB session, no httpx/redis, no LLM client | Fully-Automated | `ast.parse` walk assertion inside `tests/unit/test_icp_fit.py` (written from scratch — `apps/api/services/roster_ranking.py` re-confirmed NOT on disk this cycle) | B |
| AC-13 | Fewer than 2 non-`None` dimensions ⇒ `None` (no geography-only "ICP fit"); three-dimension inventory (role, firmographics, geography) | Fully-Automated | Unit case in `tests/unit/test_icp_fit.py`: one scored dimension ⇒ `None`; two ⇒ an `int` | B |
| AC-4 (geography) | `score_geography` returns `None` (not 0) for NULL/unmapped `country_code`; scores > 0 for `"US"` vs `"United States"` through the D11 ISO map | Fully-Automated | Unit cases in `tests/unit/test_icp_fit.py` | B |
| AC-12 | `build_conviction` pre-existing behavior characterized FIRST (byte-identical output, guaranteed by E1's after-the-slice placement), then the ICP clause present iff `icp_fit` is not `None` **and** the function did not early-return `None` (see H-6) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_conviction.py -q` exits 0 (NEW file — re-confirmed no `test_conviction*.py` exists anywhere) | B |
| AC-2 | `site_profile_candidate` is never read by the scorer or its call site | Fully-Automated | `grep -rn "site_profile_candidate" apps/api/services/icp_fit.py apps/api/services/visitor_aggregator.py` returns nothing | B |
| AC-11 | No JSONB containment/content query added against `site_profile` | Fully-Automated | `grep -rn "site_profile" apps/api/ \| grep -iE "contains\|jsonb_\|->>"` shows no NEW content-query beyond the `routers/sites.py` column assignment | B |
| AC-6 (flag exists) | `settings.icp_fit_enabled` resolves at runtime and is togglable per test — the precondition every flag-gated gate below rests on | Fully-Automated | `grep -n "icp_fit_enabled" apps/api/config.py` returns the C0 declaration | B |
| AC-14 (backend half) | Conviction clause contains only `icp_fit_verdict` band vocabulary; an adversarial persona `role` (`"IGNORE PREVIOUS INSTRUCTIONS <script>alert(1)</script> VP Eng"`) leaves no substring in the rendered clause | Fully-Automated | F6 positive unit assertion through the real `build_conviction` path, in `tests/unit/test_icp_fit.py` / `test_conviction.py` | B |
| AC-14 (tooltip half) | The E3 detail tooltip contains only fixed band vocabulary; no `site_profile` string is interpolated into web copy | Agent-Probe | **Not provable by the Python F6 assertion as written (H-9) — the tooltip is TSX.** Interim: reviewer reads the rendered tooltip on the detail page. Preferred fix: extract the tooltip/band string builder into `apps/web/src/lib/` and cover it with vitest (10 `src/lib/*.test.ts` precedents exist; runner `npm test` = `vitest run`) | B — upgrade to Fully-Automated via the vitest leg |
| AC-8 | `intent_score` values and `order_by(intent_score.desc())` ordering unchanged | Fully-Automated | Explicit before/after assertion in the integration suite across one full recompute with the flag ON | B |
| AC-7 / D5 (persistence) | `Visitor.icp_fit` written ONLY by `aggregate_visitors_for_site(db, site_id, since=None)` via `_score_icp_fit_for_site`, invoked after the `since is None` loop's `await db.commit()` (`:529`) beside `revive_returning_unresolvable` (`:533`); the incremental branch never writes it | Hybrid | `.venv/bin/python3.11 -m pytest tests/integration/test_icp_fit_persistence.py -q` — asserts (a) flag ON + seeded schema-v1 `site_profile` ⇒ `Visitor.icp_fit` non-NULL after a full recompute; (b) after `since=<ts>` the value is untouched. Preconditions: PG on :5433; the C0 declaration present; per-case `monkeypatch.setattr(settings, "icp_fit_enabled", True/False)`; a `Site` seeded with a real schema-v1 `site_profile`; at least one case runs flag-ON | B |
| AC-6 | Flag OFF ⇒ nothing written; `site_profile` NULL ⇒ nothing written; never 0 | Hybrid | Same suite, same preconditions — three distinct cases, each toggling via `monkeypatch` | B |
| AC-9 | `GET /visitors` (list) still returns 200 after the schema change; `icp_fit` is on `VisitorDetailOut` only | Hybrid | Integration request test — precondition: PG :5433 up | B |
| AC-10 | Migration applies and reverses cleanly | Hybrid | `DATABASE_URL=postgresql+asyncpg://<user>:<pw>@localhost:5433/<db> .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head` → `downgrade -1` → `upgrade head`. **Precondition: `DATABASE_URL` pinned to localhost:5433 — bare alembic reads `.env`, which points at Supabase PROD.** C2's re-derive-the-live-head-first rule stays mandatory (Phase 1 will move it) | B |
| AC-16 | With the flag ON and a visitor carrying ≥3 non-ICP conviction parts, `GET /visitors/{site_id}/{visitor_id}` returns non-null `icp_fit` AND a `conviction` containing the band phrase | Hybrid | Integration request test (F5) — preconditions: PG :5433 up; C0 declaration present; per-case `monkeypatch.setattr(settings, "icp_fit_enabled", True)`; seeded schema-v1 `site_profile`; **seed = `EnrichmentProfile` with `job_title` + `company_name`, `total_sessions >= 2`, `/pricing` in `pages_visited`** (all three verified reachable through the detail dict this cycle) | B |
| AC-15 | `_score_icp_fit_for_site` issues a bounded query count (3 reads + 1 bulk write), independent of visitor count | Hybrid | `event.listen(test_engine.sync_engine, "before_cursor_execute", counter)` — `.sync_engine` REQUIRED (`tests/conftest.py:92` yields an `AsyncEngine`); N=1 vs N=25 seeded visitors ⇒ identical count. Precondition: PG :5433 up | B |
| — (sweep resilience) | An exception inside `_score_icp_fit_for_site` must not abort the rest of the sweep for that site (`_resolve_companies` runs AFTER it) | — | **No gate specified (H-7).** Add a try/except-and-log wrapper mirroring `_advance_watermark`'s never-fails-the-run posture (`visitor_aggregator.py:560-575`), plus one unit/integration case forcing the scorer to raise and asserting the sweep still completes | D — named residual until the wrapper + case land |
| — (E3 web display) | The visitor detail view renders the score + band and does not regress the existing conviction render | — | **No automated gate today (H-9/H-10).** `apps/web` HAS vitest (`npm test`) with 10 `src/lib/*.test.ts` precedents and Playwright e2e; the render site is `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx:702-707` | D — named residual; upgradeable to Fully-Automated with one vitest file |
| AC-12 (copy quality) | Conviction clause reads truthfully and does not overclaim | Agent-Probe | Open a visitor detail page for a scored visitor; judge the rendered conviction string and the ICP tooltip | D |

gap-resolution legend: A — proven now; B — gate added by this plan's checklist; C — deferred to a named later phase; D — backlog test-building stub (named residual).

Legacy line form (for existing validate-contract consumers):

- Pure scorer: [Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_icp_fit.py -q`]
- Conviction: [Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_conviction.py -q`]
- Flag declaration (C0): [Fully-automated: `grep -n "icp_fit_enabled" apps/api/config.py`]
- Static guards (AC-2, AC-11) + adversarial backend copy (AC-14 backend half): [Fully-automated: grep assertions + F6 unit assertion]
- Persistence gating + full-vs-incremental branch (AC-6, AC-7): [hybrid: `.venv/bin/python3.11 -m pytest tests/integration/test_icp_fit_persistence.py -q` + preconditions: PG :5433 up, C0 declaration present, per-case `monkeypatch.setattr`, seeded schema-v1 `site_profile`]
- Query-count bound (AC-15): [hybrid: `before_cursor_execute` counter on `test_engine.sync_engine` at N=1 vs N=25 + precondition: PG :5433 up]
- List-endpoint regression (AC-9): [hybrid: integration request test + precondition: PG :5433 up]
- Detail-surface reachability (AC-16): [hybrid: `GET /visitors/{site_id}/{visitor_id}` body + conviction band assertion, ≥3-non-ICP-part seed + precondition: PG :5433 up]
- Migration round-trip (AC-10): [hybrid: alembic up/down/up + precondition: `DATABASE_URL` pinned to localhost:5433]
- Conviction copy quality: [agent-probe: visitor detail page read-through]
- E3 web display + tooltip vocabulary (AC-14 tooltip half): [known-gap: no automated gate today — H-9/H-10; `apps/web` vitest + Playwright both available, one `src/lib` test closes it]
- Sweep resilience of the new second pass: [known-gap: no gate and no try/except specified — H-7]

### Dimension findings

- Infra fit: CONCERN — the flag now has a real home (C0; both cited `config.py` line numbers exact) and every persistence anchor re-verified live (`:499`, `:529`, `:533`, `:597`). New residual: the second pass is inserted upstream of `await _resolve_companies(db, site_id)` inside the same function with no exception containment, so a scorer raise turns a working sweep into a skipped one for that site (H-7). The in-file precedent for the fix (`_advance_watermark`'s try/except-and-log) is two functions away.
- Test coverage: CONCERN — every named command is real and runnable (validator 0 failures / 0 warnings; PG :5433 and Redis :6379 both confirmed listening this cycle; `monkeypatch` idiom verified at `tests/unit/test_ads_stub_501.py:48`; `.sync_engine` hop verified necessary at `tests/conftest.py:92`), and the two gates that were unrunnable last cycle (AC-6/AC-7 via F-4, AC-16 via F-5) are now both expressible and non-vacuous. Residuals: the E3 web display leg has ZERO automated gate, and F6's tooltip half cannot execute in a Python test (H-9/H-10). Redis on 6379 is live for a fourth consecutive cycle (H-5).
- Breaking changes: CONCERN — the column is additive/nullable and mirrors `intent_score` exactly; `build_conviction`'s signature is now explicitly UNCHANGED and existing output is byte-identical under E1's locked placement; `icp_fit` lands on `VisitorDetailOut` only, so the `GET /visitors` 500 P0 path stays structurally avoided; the watermark is provably untouched (`_advance_watermark` runs only when `since is not None`). Residual: C0 makes `apps/api/config.py` a shared file with Phase 3 (`campaign_benchmark_enabled`), while the umbrella's `## Pre-PVL Conflict Resolution` still says "No other shared files identified" (H-8).
- Security surface: CONCERN — no auth, billing, secrets, or send-path surface; `site_profile` stays read-only; D10's fixed-band-vocabulary rule is right and F6 now proves the backend half positively rather than by grep. Residual: the tooltip half of D10/AC-14 — the one place LLM-derived text would reach a browser — has no executable assertion (H-9). Upstream defense in depth is real (`sanitize_profile` at `services/site_analysis.py:239` runs `clean_text`, caps lengths, drops unknown keys), which is why this is a CONCERN and not a FAIL.
- Section A (confirm the ICP contract): PASS — shape re-verified: `Firmographics{size_band: str|None, industries[], geography[]}` (`schemas/site_analysis.py:25-28`), `Icp{personas[≤3]}` (`:31-32`), `sanitize_profile` (`services/site_analysis.py:239`). Read-only step, no risk.
- Section B (pure scorer): PASS — all inputs confirmed present (`models/enrichment.py:23-27`, `models/visitor.py:46`, `firmographics.geography[]`); the drop-from-both-sides rule, the ≥2-dimension floor and the AST-purity test are stated inline and need no external precedent file. Highest-risk edit: B5's combination arithmetic — sound as specified.
- Section C (schema + migration): PASS — C0 lands the flag before Step D with exact precedents; C1 targets the right table and type; C2's re-derive-first rule is correct and necessary; C4's pinned-`DATABASE_URL` warning is the right guard against the repo's live PROD-`.env` hazard. Highest-risk edit: C4 — an unpinned alembic invocation reaches Supabase prod; the plan names this explicitly.
- Section D (persistence): CONCERN — the second-pass design is verified correct end to end (post-commit placement, symbol anchors exact, bulk load on a genuinely unique key, 3 reads + 1 bulk write, incremental branch excluded, watermark untouched). Residual: no exception containment (H-7). Highest-risk edit: the placement itself — it sits between the commit and `_resolve_companies`, so its failure mode is other people's work not running.
- Section E (surface): CONCERN — E1's placement is now locked, verified against source, and structurally un-truncatable; E1b's injection point and both precedent `data.update` blocks re-verified exact (`:693`, `:741-750`, `:761-772`, `:784`); the list-vs-detail split is correct and the do-not-move-it warning is load-bearing. Residuals: E1's "rendered ONLY when `icp_fit` is not `None`" is still not an iff — `build_conviction` returns `None` early when `not parts and score < HIGH_INTENT` (`conviction.py:73-74`), which a firmographics-only scored visitor can hit (H-6); and E3 never names its target file or carries any gate (H-9/H-10). Highest-risk edit: E1b's one-line injection — one line, but the whole feature's reachability.
- Section F (tests): CONCERN — F1/F2/F4/F5/F6 are well-shaped, F3's flag-toggle idiom is the correct repo pattern and now actually executable, and F7's `.sync_engine` plumbing is pinned correctly. Residuals: F6's tooltip half is unexecutable as scoped (H-9), and no F-item covers the sweep-resilience or web-render behaviors (H-7/H-10). Highest-risk edit: F5's seed — verified achievable this cycle, but a seed that silently loses one of the three parts makes AC-16 vacuously green again.

### Open gaps

- **H-6 (CONCERN, new) — E1's "rendered ONLY when `icp_fit` is not `None`" is still not an iff.** `build_conviction` returns `None` before any join when `not parts and score < HIGH_INTENT` (`conviction.py:73-74`, `HIGH_INTENT = 40` at `:22`). A visitor scored on firmographics + geography alone (no `job_title`/`company_name`, `total_sessions < 2`, no hot page, no depth, intent < 40) satisfies B5's ≥2-dimension floor yet gets no conviction line at all, so the ICP clause never renders for them. Narrow, not a defect in the fix — but E1 currently overstates. **Resolution:** add one sentence to E1 stating the early-return guard is deliberately UNCHANGED and the clause never resurrects a null conviction, and add one `test_conviction.py` case asserting exactly that.
- **H-7 (CONCERN, new) — the new second pass has no exception containment, and it runs upstream of `_resolve_companies`.** D1 places `_score_icp_fit_for_site` right after the `since is None` commit (`:529`), beside `revive_returning_unresolvable` (`:533`). On that same branch, `await _resolve_companies(db, site_id)` runs later at `:549`. Any raise inside the new pass (malformed `site_profile`, a scorer bug, a DB hiccup on the bulk UPDATE) propagates out of `aggregate_visitors_for_site`, is caught by the scheduler's blanket `except Exception` (`jobs/scheduler.py:502-504`) and the whole site is logged `aggregation_sweep_site_failed` and returned as `("skipped", 0)` — so a best-effort cosmetic score can suppress IP→company resolution for that site. The in-file precedent for the correct posture is `_advance_watermark`, which wraps its own body in try/except and logs `"Never fails the run."` (`:560-575`). **Resolution:** wrap the `_score_icp_fit_for_site` call in try/except + `logger.warning("icp_fit_pass_failed", ...)`, or place it after `_resolve_companies`; add one case forcing a raise and asserting the sweep still completes.
- **H-8 (CONCERN, new) — the umbrella's shared-file table is now stale.** C0 adds `apps/api/config.py` to this phase's Blast Radius. Phase 3 already claims the same file (`apps/api/config.py` — NEW `campaign_benchmark_enabled` flag, D9). The umbrella's `## Pre-PVL Conflict Resolution` lists only `api-types.ts` and states "**No other shared files identified**", which is no longer true. This is documentation drift, not a live conflict: the phases are strictly sequenced, both edits are additive declarations in different regions of a 1455-line file, and `extra: "ignore"` means neither can hard-fail startup. **Resolution:** add one row to the umbrella table — `apps/api/config.py` | Phase 2, Phase 3 | additive-only, no reassignment | each phase declares its own flag in its own region; whichever lands second re-reads the file rather than rebasing a stale copy.
- **H-9 (CONCERN, new) — AC-14's tooltip half has no executable gate, and F6 as scoped cannot provide one.** F6 lives in the Python unit suite and asserts "render the clause and tooltip"; the tooltip is TSX in `apps/web`, so the Python assertion can only ever cover the conviction clause. This matters more than a normal coverage gap because the tooltip is the one surface where LLM-derived `site_profile` text could reach a browser, which is exactly what D10 exists to prevent. It is cheaply fixable: `apps/web` already runs vitest (`npm test` → `vitest run`, `vitest.config.ts` present) with 10 existing `src/lib/*.test.ts` files, and the detail page already has a plain-string tooltip precedent (`candidateTooltip`, `page.tsx:480`, rendered via `title=` at `:594`). **Resolution:** scope F6 explicitly to the conviction clause, and add a small vitest leg — extract the band/tooltip string builder into `apps/web/src/lib/` and assert it emits only band vocabulary and never interpolates a `site_profile` field.
- **H-10 (CONCERN, new, minor) — E3 never names its target file, and the web display leg carries no gate at all.** "the visitor detail view" is the only pointer. Located this cycle: `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx`, which renders `{visitor.conviction}` at `:702-707` beside `<IntentRing score={visitor.intent_score} />` at `:697` — the natural home for the band chip. **Resolution:** name the file and the render site in E3, and either add the vitest leg from H-9 or record the web leg as an explicit named residual in the phase report.
- **H-5 (CONCERN, environmental, carried) — Redis IS listening on 6379 in this worktree, re-verified a fourth consecutive cycle** (`com.docke ... TCP *:6379 (LISTEN)`, alongside PG on `*:5433`). The Exit Gate's G-10 rule stands: record the 6379 state in the phase report BEFORE capturing the unit baseline, or stop the container first. A baseline captured without that record is not comparable.
- H-4 (informational, NOT a plan defect): the Phase 0 entry gate is still unmet, exactly as the plan's Entry Gate states — re-confirmed this cycle: `apps/api/services/site_analysis.py` and migration `c5e1a9b73d20_add_site_profile.py` untracked, `apps/api/models/site.py` modified-unstaged. Accepted as correct per the program's standing decision that Phase 2 is entry-gated on Phase 0.
- Umbrella Action-field check (informational): the umbrella's `## Pre-PVL Conflict Resolution` contains no unresolved `Action: update Phase [X] blast-radius claim` items — V1's Action-field completion check passes. H-8 is an ADD to that table, not an unexecuted Action.

### What this coverage does NOT prove

- `pytest tests/unit/test_icp_fit.py` proves the scorer is deterministic and mathematically well-formed. It does NOT prove the resulting number correlates with real ICP fit, that the keyword weights are calibrated against any real customer profile, or that the fuzzy match works on provider strings this repo has actually seen — no Hunter/Apollo/PDL `job_title` sample is cited anywhere in the plan.
- The D11 ISO-map geography unit cases prove the map behaves for the codes the test enumerates. They do NOT prove the map's coverage is adequate for this product's real traffic mix, and every code absent from the map silently degrades to `None` — which, combined with the ≥2-dimension floor, silently withholds a score rather than surfacing a gap.
- The AST purity test proves no forbidden module is imported. It does NOT prove the functions are side-effect-free in any deeper sense, nor that they avoid non-determinism from set/dict iteration order — B7 asserts stable ordering, but the AST test cannot see it.
- `pytest tests/unit/test_conviction.py` proves the clause appears and disappears with the `icp_fit` key in a dict the test constructs, and (given E1's locked placement) that existing output is byte-identical. It does NOT prove the clause renders for a visitor whose conviction is suppressed entirely by the early `not parts and score < HIGH_INTENT` guard — that is H-6.
- The grep gates (AC-2, AC-11) prove two named files contain no matching string. They do NOT prove that no OTHER file introduces a `site_profile_candidate` read or a JSONB content query, and they cannot catch an equivalent query written in raw `text()` SQL.
- `grep -n "icp_fit_enabled" apps/api/config.py` proves the field is declared. It does NOT prove the guard is placed correctly at the call site, nor that any test actually exercises the flag-ON branch — only the flag-ON persistence case does that.
- `test_icp_fit_persistence.py` proves the flag/NULL gating branches and that the full-recompute path writes a real `Visitor.icp_fit` while the incremental path does not. It does NOT prove the score is recomputed when enrichment arrives later (D7 staleness is untested by construction — the named residual in D3), does NOT prove the score's meaning, and does NOT prove the new pass survives its own exceptions (H-7).
- The AC-15 query-count assertion proves the query count is constant across two visitor counts. It does NOT prove the bulk UPDATE is efficient at production row counts, nor that the second pass fits inside the aggregation job's time budget on a large site.
- The `GET /visitors` 200 check proves the list endpoint did not regress on a happy path. It does NOT prove every list filter combination, nor the detail endpoint's full response shape.
- AC-16's detail-response gate, with the mandated ≥3-non-ICP-part seed, proves the clause survives `parts[:3]` truncation for the richest realistic case. It does NOT prove the score is meaningful for that visitor, and it does NOT prove anything about what the browser actually renders — the response body is where this gate stops.
- **Nothing in this contract proves the score is visible in the product UI.** E3's web display has no automated gate (H-9/H-10): no vitest leg, no Playwright leg. A user-visible regression in the detail page would pass every gate above. This is the single largest named residual in this contract.
- The AC-14 adversarial assertion proves one crafted injection string does not survive into the rendered CONVICTION CLAUSE. It does NOT cover the tooltip (H-9), does NOT prove the band vocabulary is exhaustive, and does NOT prevent a future copy change from re-opening the interpolation hole — only D10 does, and D10 is a convention, not a gate.
- The alembic up/down/up round-trip proves the revision is reversible on a local database. It does NOT prove it applies cleanly at production data volumes, and it says nothing about Supabase prod, which these gates deliberately never touch.
- The intent-score regression assertion proves values are equal across one recompute. It does NOT prove identity-resolution provider budget burn is unchanged in production.
- The Agent-Probe proves one reviewer's judgment of one rendered string. It does NOT generalize across sites, ICP shapes, or score bands.
- Every gate above is downstream of the Phase 0 entry gate. With `site_analysis_enabled` OFF and no committed `site_profile` writer, `Site.site_profile` is NULL in practice, so the flag-ON gates prove the write path against SEEDED data only — never against data the product itself produced.

Gate: CONDITIONAL
Accepted by: NOT ACCEPTED IN THIS SESSION — 0 FAILs, 6 CONCERNs (H-5 through H-10). The validate-agent may not self-accept its own verdict. Acceptance requires either (a) an orchestrator/user statement accepting H-6…H-10 as documented residuals, or (b) PVL supplement cycle 4 closing them. Mechanically, `results.tsv` records 3 completed fix cycles, so orchestration.md's condition (b) for routing CONDITIONAL → EXECUTE is satisfied — the choice is the orchestrator's, not this agent's.
