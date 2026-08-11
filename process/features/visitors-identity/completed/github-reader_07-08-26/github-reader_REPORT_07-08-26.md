---
phase: github-reader
date: 2026-08-07
status: COMPLETE
feature: visitors-identity
plan: process/features/visitors-identity/active/github-reader_07-08-26/github-reader_PLAN_07-08-26.md
---

# EXECUTE exit summary — GitHub public-profile reader

**TL;DR** — All 16 checklist items done, all 15 ACs green, zero deviations, zero migrations.
Unit lane: **1197 passed, 2 skipped, 0 failed**. Every hard guardrail (G1-G9) verified by a
test or grep gate, not by assertion.

## What Was Done

| # | Checklist item | Result |
|---|---|---|
| 1 | Config block (`enable_github_reader=False`, `github_osint_token=""`, `github_reader_max_repos=5`) | `apps/api/config.py:1043-1055`, in its own `## ─── ... ───` block right after `content_reader_max_items` |
| 2 | New service + docstring guarantees (flag/mock/cache/rate-limit/non-fatal + G1 out-of-scope + G6 note) | `apps/api/services/github_reader.py` (~430 lines) |
| 3 | Login parsing + GitHub-username regex | `parse_github_login()`, `_LOGIN_RE` |
| 4 | `_GITHUB_HOSTS = {"api.github.com"}` allowlist, checked pre-request | `_host_allowed()`, looped over all 3 built URLs before any call |
| 5 | Mock short-circuit before cache/rate-limit/network | `_mock_github()`, first branch after login parse |
| 6 | Redis 7d cache, positive + negative + miss marker | `_cache_get`/`_cache_set`, `_CACHE_MISS_MARKER` |
| 7 | Hourly rate limit, **fail-CLOSED** on Redis error | `_rate_ok()` returns `False` on any exception |
| 8 | 3 endpoint fetches using `github_osint_token` only | `/users/{login}`, `/users/{login}/repos?sort=pushed`, `/users/{login}/social_accounts` |
| 9 | Field-level `clean_text()` on every free-text field | `_shape_summary`/`_shape_repos`/`_shape_social_accounts` |
| 10 | Summary shaping (`dominant_languages` freq-ordered, `top_repos` capped) | `_shape_summary()` |
| 11 | Whole fetch wrapped, returns `{}` on any error | outer `try/except httpx.HTTPError` + `except Exception` |
| 12 | One gated enricher call site, read-modify-write merge | `Enricher._fetch_and_store_github` + call at `enrich_tier1` Step 4b |
| 13 | `tests/unit/test_github_reader.py` | 27 tests |
| 14 | AC10 call-site test | `TestEnricherGithubGate` (5 tests) in `tests/unit/test_content_enrich.py` |
| 15 | Static gates + full regression | see Test Gate Outcomes |
| 16 | G9 sibling-clobber documented (not fixed) | module docstring `github_reader.py:60-70` + `_fetch_and_store_github` docstring |

Plus the plan-required backlog note:
`process/features/visitors-identity/backlog/social-context-wholesale-overwrite-bug_NOTE_07-08-26.md`.

## What Was Skipped or Deferred

- **CONCERN-2 code fix** (`social_intelligence.py::store_social_context` wholesale overwrite) —
  explicitly out of scope per G9/Out of Scope. Documented + backlog note written.
- Integration/e2e lane — not required by the plan (no router/DB/UI surface).
- Live GitHub API smoke — not required (matches the `content_reader.py` precedent).

## Test Gate Outcomes

| Gate | Command / check | Result |
|---|---|---|
| AC1-AC9, AC13 + G6/G8 | `pytest tests/unit/test_github_reader.py -m unit -q` | **27 passed** |
| AC10 | `pytest tests/unit/test_content_enrich.py -m unit -q` | **19 passed** (5 new) |
| Full regression | `pytest tests/unit -m unit -q` | **1197 passed, 2 skipped, 0 failed** |
| AC11 | no new file under `apps/api/migrations/versions/` from this plan | PASS (4 untracked migrations there are pre-existing unrelated ws2/graph-erasure/job-change work) |
| AC12 / G1 | `grep -rn "events\|commits\|author.email" apps/api/services/github_reader.py` | no match (exit 1) — PASS |
| AC14 / G4 | `grep -c github_osint_token` = 3; `grep -c settings.github_token` = 0 | PASS |
| AC15 / G3 | `ENRICHMENT_FIELDS` grep = 1; `git diff -U0 enricher.py` hunks are only `@@ +315,4` and `@@ +839,56` | PASS — neither touches lines 101-106 or 430-433 |
| AC9 (Hybrid) | real `prompt_safety.wrap_untrusted` round-trip, fenced body has zero `<`/`>` | PASS |
| G9 | `grep store_social_context` → 1 hit in `github_reader.py`, 2 in `enricher.py` | PASS |

AC9 note: the initial draft asserted `wrapped.count(UNTRUSTED_OPEN) == 1`, which is wrong —
`UNTRUSTED_CLOSE`'s SECURITY NOTE legitimately quotes the tag. Corrected to assert exactly one
*closing* tag plus a bracket-free fenced payload region, which is the actual security property.

## Plan Deviations

**None.** Two mechanical adjustments, both inside blast radius and required by the plan's own gates:

1. `github_reader.py` docstring reworded from ``settings.github_token`` → "the separate
   repo-scoped `github_token` PAT". Reason: the AC14 gate is
   `grep -c "settings.github_token" == 0`, and the original prose wording tripped its own gate.
   Semantics unchanged.
2. Added `github_reader_max_repos: int = 5` (not named in the plan's config touchpoint, but the
   plan's checklist item 10 requires "top_repos capped" and `content_reader_max_items` is the
   mirrored precedent). Additive, default-safe.

Also: implemented the enricher call site as a **new sibling method**
(`_fetch_and_store_github`) rather than editing `_fetch_and_store_content` in place. The plan said
"near `enricher.py:774-821`" — this keeps the existing method and its 6 existing tests byte-identical,
which is the lower-blast-radius reading of the same instruction.

## Test Infra Gaps Found

- None new. `.venv/bin/pytest` shebang is still broken (used `.venv/bin/python3.11 -m pytest`
  throughout, per the known gotcha).
- The ORM-mapper gotcha did not apply — new tests use `SimpleNamespace`/`FakeClient`, never real
  `EnrichmentProfile`/`Visitor` instances.

## Closeout Packet

- **Selected plan**: `process/features/visitors-identity/active/github-reader_07-08-26/github-reader_PLAN_07-08-26.md`
- **Finished**: all 16 checklist items, all 15 ACs, all 9 guardrails, backlog note.
- **Verified**: everything in the Test Gate Outcomes table above (46 targeted + 1197 full-lane).
- **Still unverified**: `api.github.com`'s real response shape vs the mocked fixtures (residual
  gap, documented in the plan's "What this coverage does NOT prove"); the runtime Gemini
  prompt-assembly path that renders `social_context["github"]` (unchanged, out of Touchpoints).
- **Cleanup remaining**: EVL confirmation run by a spawned `vc-tester`, then UPDATE PROCESS
  (archive plan + context update). **Not committed** — the worktree carries unrelated
  uncommitted work and I touched nothing outside this plan.
- **Best next state**: EVL confirmation run.

## Forward Preview

### Test Infra Found
`fakeredis.aioredis.FakeRedis` + `monkeypatch` is the working no-container pattern for
Redis-backed services. Dependency-injecting `http_client=` (rather than monkeypatching
`httpx.AsyncClient` globally, as `test_content_reader.py` does) is a cleaner seam — reusable for
the next single-host reader.

### Blast Radius Changes
Unchanged from plan: 1 new service, 1 config block, 1 new enricher method + 1 call line, 1 new
test file, 1 extended test file. No schema, no dependency, no router, no runtime surface.

### Commands to Stay Green
```
.venv/bin/python3.11 -m pytest tests/unit/test_github_reader.py -m unit -q
.venv/bin/python3.11 -m pytest tests/unit/test_content_enrich.py -m unit -q
.venv/bin/python3.11 -m pytest tests/unit -m unit -q
grep -rn "events\|commits\|author.email" apps/api/services/github_reader.py   # must be empty
grep -c "settings.github_token" apps/api/services/github_reader.py            # must be 0
```

### Dependency Changes
None. `httpx`, `structlog`, `fakeredis` all pre-existing.

### Operator note before enabling
`enable_github_reader` stays `False`. Flipping it on is an explicit operator action; set
`github_osint_token` first (unauthenticated works but caps at 60 req/hr vs 5000).
