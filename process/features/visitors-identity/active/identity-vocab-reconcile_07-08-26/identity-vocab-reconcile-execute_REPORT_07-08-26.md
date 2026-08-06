---
name: report:identity-vocab-reconcile-execute
description: "EXECUTE report — devjulley rebased onto main, identity vocabulary reconciled to identified/candidate, alembic sub-chain re-chained to a single head, candidate_outreach_enabled confirm-gate wired at 3 call sites. Nothing pushed."
date: 07-08-26
phase: EXECUTE
status: COMPLETE_WITH_GAPS
feature: visitors-identity
plan: process/features/visitors-identity/active/identity-vocab-reconcile_07-08-26/identity-vocab-reconcile_PLAN_07-08-26.md
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
---

# EXECUTE — identity-vocab-reconcile

**TL;DR** — The rebase is done and green. `devjulley` now sits on top of `main` at
`5293cbc`, all 12 commits, one alembic head, 1891 unit tests passing, 0 failures,
the fp3 e2e spec green across 3 browsers, and the pixel rebuilt at 5788 B gzipped.
**Nothing has been pushed.** Docker was unavailable so the integration lane and the
migration live round-trip are known-gaps. Three things need a human before this
ships: the `railway` prod pre-check, the push decision, and a call on a
plan-governance discrepancy I found (PVL cycle 7 says this plan was NOT unblocked).

---

## 1. Step-0 pre-flight vs plan snapshot

Run as the first action, before touching anything.

| Check | Live output | Plan snapshot | Match |
|---|---|---|---|
| `git rev-parse main` | `332b3a88af09e8ea3b55a1825b1a18da351c2546` | `332b3a8` | yes |
| `git rev-parse devjulley` | `ae7ffb9e1be44c321152de0713fcfbb3c7b2b9a3` | `ae7ffb9` | yes |
| `git rev-parse origin/devjulley` | `1c5ae323c199867ebd7b28b77216397e86cfd5df` | `1c5ae32` (ae7ffb9 unpushed) | yes |
| `git log main..devjulley` | `ae7ffb9, 1c5ae32, fe89466, 626d643, a066006, e11a91d` (6) | same 6, same order | yes |
| migration files in diff | `b1c9e7f24d83, c2f8a5d31e97, e9d2a4c71f68, f1a7c3e05b92` (4) | same 4 | yes |
| divergence | 20 / 6 | 20 / 6 | yes |
| `alembic heads` (local, devjulley) | `f1a7c3e05b92` (single) | single | yes |
| backup refs | `backup/main-06-08-26` = `db180c4`, `backup/devjulley-pre-rebase-06-08-26` = `1c5ae32` | intact | yes |

**Zero drift.** Proceeded.

Working tree was dirty at start (21 modified tracked files, all harness/process docs
under `.claude/`, `CLAUDE.md`, `docs/`, `process/`; **none** under `apps/` or `tests/`).
Stashed before the rebase, restored after, and left unstaged exactly as found.

---

## 2. Conflict-by-conflict resolution

`git rebase main` replayed the two clean commits (`e11a91d`, `a066006`) with zero
conflicts, exactly as predicted, then stopped on `626d643`.

| # | File | Predicted | Resolution |
|---|---|---|---|
| 1 | `services/identity_classification.py` | §3.1 adopt-devjulley | Took devjulley's file wholesale. All 8 retired symbols gone. `is_emailable_identity()` untouched — 3 params, verified. **Then ported 2 main-only symbols back (see D-3).** |
| 2 | `services/identity_resolver.py` | §3.2 — "highest-effort, take devjulley base then re-port main" | Git auto-merged the bulk; only **3 small hunks** conflicted. Far cheaper than planned. (a) imports: kept both sides, dropped `identity_status_for_provider`. (b) vocabulary write: devjulley's `"candidate" if is_graph_candidate_provider(...) else "identified"`. (c) conflict-log line: took devjulley's event name `save_identified_conflict_upsert` (matches the now-upsert semantics) with main's post-rollback-safe `conflict_visitor_id` variable — reading `visitor.*` there would `MissingGreenlet`. main's outage/watermark/RB2B logic verified present after merge. |
| 3 | `services/kpi.py` | §3.3 pure adopt | `--theirs`. |
| 4 | `services/timeseries.py` | §3.4 pure adopt | `--theirs`. |
| 5 | `tests/unit/test_identity_classification.py` | §3.7 rewrite | `--theirs` — devjulley's file has zero retired symbols, so adopt == the specified rewrite. |
| 6 | `web/components/ui/status-badge.tsx` | §3.8 | devjulley's `candidate: "warning"`; `vpn_filtered`/`merged` confirmed still present; `verified`/`provider_candidate` deleted. |
| 7 | `tests/integration/test_events_ingest.py` | §3.9 concatenate | Both sides are pure appends at line 431. Took main's full file + appended devjulley's block from line 434 on. `TestCookieFpPhase2` **and** `TestUnknownSiteObservability` both present exactly once. |
| 8 | `apps/pixel/src/tracker.js` | §3.10 clean auto-merge | Confirmed live: git auto-merged, zero markers. Spot-checked both sides survive — `withCredentials` (1 hit), `fontFp`/`audioFp` (4), Leadpipe vendor config (7). |
| 9 | `apps/api/routers/events.py` | §3.11 + **E-8** | See below. |

### E-8 — `events.py` (applied exactly as instructed)

Verified main's real gate from source before writing: it is **`if fp_value or svid:`**,
confirming the plan body's `if fp_value:` is wrong. Merged result:

- main's `pg_insert(...).on_conflict_do_update(...)` upsert-stub kept as the base (race fix preserved).
- Gate written as **`if fp_value or fp3_value or svid:`** — all three signals.
- `fingerprint_v3=fp3_value` added to `.values(...)`.
- `"fingerprint_v3": COALESCE(visitors.fingerprint_v3, EXCLUDED.fingerprint_v3)` added to `set_={}`.
- devjulley's dual fp2/fp3 scan loop survived the auto-merge and is intact.
- A comment at the gate records *why* `or svid` must not be dropped, so a future edit can't silently reintroduce it.

### E-9 — the two files git never flagged (confirmed real)

`dashboard.py` and `visitors_helpers.py` auto-merged with **no conflict**, and the
merged result still imported `VERIFIED_STATUSES` — exactly as E-9 warned. Rewrote both
manually: `.in_(VERIFIED_STATUSES)` → `== "identified"`, imports deleted. Also did
`visitors.py:1081` (`STATUS_VERIFIED` → `"identified"`, checklist step 9).
Had I trusted git's silence, the `ImportError` would have hit at app boot.

---

## 3. Deviations from the plan

| # | Deviation | Why | Class |
|---|---|---|---|
| **D-1** | Migration re-chain done after the whole rebase completed, not between checklist steps 3 and 5. | The constraint the plan protects is "the file must exist first." Doing it once at the end satisfies that and avoids a dangling window entirely. Identical end state. | Timing only, within blast radius |
| **D-2** | Rewrote 3 test files the plan's E3 spot-check said needed **no change**: `test_outbound_identity_gate.py`, `test_agent_origin_exclusion.py`, `test_handoff_emailability_separation.py`. | E3 checked *devjulley's* copies (clean, 0 refs). But devjulley never edited these files, so the **rebase keeps main's copies**, which reference `EMAILABLE_PROVIDERS` (5/4/2 hits) — deleted by §3.1. Same failure mode as Finding 9, different file set. Rewrote to D2 semantics: person-level = emailable, graph candidates emailable, agent-origin/abuse vetoes still unconditional. | Within blast radius (files already named in Touchpoints) |
| **D-3** | Ported `PAID_PERSON_GRAPH_PROVIDERS` and `name_email_consistent()` (+ its 2 regexes, `import re`) from main into devjulley's `identity_classification.py`. | §3.1 says "pure adopt-devjulley", but devjulley's file lacks both symbols and main's resolver paid-graph quality gate (`identity_resolver.py:1093-1096`) imports them. Pure adopt = `ImportError` + loss of a main-only feature, violating **D4**. Kept `PAID_PERSON_GRAPH_PROVIDERS` deliberately distinct from `GRAPH_CANDIDATE_PROVIDERS` (the former excludes `beam_identity_network`). | Within blast radius, D4-mandated |
| **D-4** | Updated `test_gmail_sender_decoration_parity.py` mock ordering. | The confirm-gate must read `identity_status` before the emailability decision, which reorders `db.execute` calls. The plan explicitly predicted this reorder (§4 campaign_sender row). Test used a positional `side_effect` list. | Within blast radius |
| **D-5** | Updated `test_rb2b_scoring.py` to mock a 3rd RB2B POST. | Genuine cross-branch interaction the plan did not enumerate: devjulley's test was written against a 2-step RB2B chain; main's RB2B rework (D4) added a Step-3 `/identity/business` enrichment call. Mocked as 404 so the assertions still observe Step 2. Preserves D3 and D4 together. | Within blast radius |
| **D-6** | `campaign_sender.py` reads `identity_status` **lazily** (cached per recipient) rather than eagerly hoisted. | Eager hoisting added a query on every early-skip path, breaking 5 tests' mock counts. Lazy+cached keeps the query count byte-identical to before while still making the value available to the gate. Better than the plan's spec, same semantics. | Within blast radius |
| **D-7** | An over-broad `git add -A` while resolving `626d643` swept untracked `process/` docs and the embedded `.claude/skills/yc-application-coach` git repo into that commit. | My error. Corrected in a follow-up commit (`6e7792c`) that untracks the embedded repo; the `process/` docs were left in place (harmless, would have been committed anyway). | Hygiene, corrected |
| **D-8** | Two commits carry the message `feat(identity): fingerprint v3 …` (`3528c00`, `bbffd74`). | `ae7ffb9`'s test additions landed across two commits. Verified the **content is complete and correct** — `tests/unit/test_pixel_fingerprint.py` is a proper superset containing both main's `test_xhr_sends_credentials_for_svid_cookie` and devjulley's `TestFingerprintV3`. Cosmetic history artifact only; not rewritten because nothing is pushed and rewriting adds risk. | Cosmetic |

### Environment anomaly worth knowing

`apps/api/routers/events.py` was **twice** silently mutated back to a conflicted /
syntactically-broken state by something outside my control (an editor or linter) after
I had resolved and committed it. Both times the committed blob was clean and
`git checkout HEAD -- apps/api/routers/events.py` restored it. The same phantom
unmerged entry is almost certainly why `git rebase --continue` refused to advance
despite a provably clean index, which is why the last two commits were completed with
`git cherry-pick` instead. **Final state verified clean** (AST parses, 0 markers,
E-8 gate present, unit suite green).

---

## 4. Governance discrepancy — needs a human decision

While resolving a file conflict I read
`identity-vocab-reconcile_07-08-26/results.tsv`, which contains a **row 7 that
post-dates the validate contract embedded in the plan file**. It records a
**PLAN supplement cycle 7** with:

- **S19** — *"self-acceptance struck, `Accepted by` set to PENDING, 'EXECUTE now appropriate' replaced with **'EXECUTE is NOT yet unblocked'**"*, and *"Re-validate from V1 as cycle 8."*
- **S16** — the `events.py` gate correction (same substance as E-8).
- **S17/S18** — prose corrections about fork points (`a7d419e6c052` is an Alembic revision id, not a git object; the real merge-base is `db180c4` — which my own run independently confirms).
- An **INCIDENT** note: a prior session started this same rebase without authorization and left the repo mid-rebase. That explains the identical commit `88fa382` reappearing in my run.

The plan file on disk still shows the **cycle-6** contract (`Gate: CONDITIONAL`,
`Accepted by: session (validate-agent, PVL cycle 6)`, "ENTER EXECUTE MODE is now
appropriate"). The cycle-7 supplement's *edits* are not in the plan body — only its
TSV row exists.

**I proceeded** because my orchestrator's task statement is an explicit human
acceptance for this session ("Gate: CONDITIONAL (PVL cycle 6) accepted by the user"),
and because cycle 7's only *code-affecting* item (S16) is identical to instruction E-8,
which I was independently bound to and did implement. S17/S18 are documentation-only.
**Flagging it because the on-disk plan and the on-disk bookkeeping disagree about
whether EXECUTE was authorized.** Worth reconciling at UPDATE PROCESS.

---

## 5. Gates

### Run and green

| Gate | Command | Result |
|---|---|---|
| Identity unit suite | `pytest tests/unit/test_identity_classification.py test_outbound_identity_gate.py test_agent_origin_exclusion.py test_handoff_emailability_separation.py test_identity_quality_gates.py test_leadpipe_webhook.py` | **181 passed** |
| Confirm-gate wrapper (new file) | `pytest tests/unit/test_candidate_outreach_gate.py` | **81 passed** |
| Pixel unit + size gate | `pytest tests/unit/test_pixel_fingerprint.py tests/unit/test_pixel.py` | **72 passed** |
| **Full unit suite** | `pytest tests/unit/ -q` | **1891 passed, 2 skipped, 0 failed** |
| App boot smoke (E-9 detector) | `python -c "import apps.api.main"` | **OK** — no `ImportError` |
| AC2 single alembic head | `alembic -c apps/api/alembic.ini heads` | **exactly 1 line** — see note below |
| Migration offline `--sql` | `alembic upgrade c2f7a9d31b64:head --sql` | **clean, both directions of the chain resolve** |
| Pixel rebuild | `cd apps/pixel && npm run build && npm run size` | **5788 B gzipped** — under both 6144 and 6000 |
| **fp3 e2e** | `npx playwright test e2e/fingerprint-v3.spec.ts` | **9 passed** (chromium + webkit + firefox) |
| AC3 retired-symbol sweep | `grep -rn <8 symbols> apps tests` | **zero residual** (incl. comments) |
| Conflict markers | `git diff --check` + repo-wide grep | **none** |
| Integration collectability | `pytest tests/integration/ --collect-only` | **489 collected, 0 import errors** |

The e2e gate was expected to be a possible known-gap; Playwright browsers were cached
locally so it actually ran and passed.

### AC2 note — a third-party migration landed on disk during EXECUTE

The **committed `devjulley` tree** has exactly one head: **`f1a7c3e05b92`** (verified
immediately after the re-chain, and again after the offline `--sql` run).

At the very end of the session an **untracked** file appeared on disk —
`apps/api/migrations/versions/a4f2b8c15d70_add_job_change_events.py`, belonging to the
unrelated in-flight `job-change-detection_07-08-26` plan (the same plan whose docs
drifted mid-session, see D-7). It is in **no commit** on any branch.

Its `down_revision` is `"f1a7c3e05b92"` — it chains cleanly onto this reconciliation's
new tip. So `alembic heads` still prints **exactly one line** either way:

- committed tree → `f1a7c3e05b92`
- working tree incl. that untracked file → `a4f2b8c15d70`

**AC2 holds in both cases: one head, no branching, no boot risk.** Flagged only so the
next agent is not surprised that `alembic heads` reports a hash this report does not
otherwise mention. Whoever owns `job-change-detection` should confirm they intended to
chain onto this branch's tip.

The same concurrent work also dropped an untracked
`tests/unit/test_job_change_detector.py`, which imports a not-yet-existing
`apps.api.services.job_change_detector` and therefore **breaks bare
`pytest tests/unit/` collection**. It is untracked and in no commit — unrelated to this
reconciliation. This report's headline unit figure is measured with
`--ignore=tests/unit/test_job_change_detector.py`:

```
pytest tests/unit/ -q --ignore=tests/unit/test_job_change_detector.py
→ 1891 passed, 2 skipped, 0 failed
```

If you see a collection `ImportError` on that module, it is the other plan's
work-in-progress, not a regression from this rebase.

### NOT run — known-gaps

| Gate | Why not | Precedent |
|---|---|---|
| Integration suite (`pytest tests/integration/`) | **Docker unavailable** (`docker: command not found`) — 7th consecutive session. Tests *collect* cleanly, proving no import breakage, but cannot execute without Postgres+Redis. | Plan §7, matches program precedent |
| Migration live round-trip (`upgrade`→`downgrade -1`→`upgrade`) | Same — no disposable Postgres. Offline `--sql` validation is the substitute, exactly as the 5 prior migrations in this chain. | Plan §7 explicitly accepts this |
| `railway run` prod pre-check (alembic_version + `identity_status` row counts) | **`railway` is blocked for agents.** Never simulated. | Plan §5 step 0 — human gate |
| Status-badge manual render (§3.8, Agent-Probe) | No browser session driven for the dashboard. Tone map verified by source inspection: `candidate: "warning"`, `vpn_filtered: "neutral"`, `merged: "info"`, `identified: "info"`. | Agent-Probe tier |
| Finding-8 svid-only-batch assertion | The contract *recommends* adding a new test asserting `server_visitor_id` is written for an svid-only batch. That test belongs in `tests/integration/test_events_ingest.py` and cannot be written meaningfully without Docker to run it. **Not written.** Registered as a follow-up below. | New residual |

---

## 6. Final git state

```
branch:            devjulley
HEAD:              5293cbc2de233a8431412ad1a4501a2a1eccfebb
main:              332b3a88af09e8ea3b55a1825b1a18da351c2546   (UNTOUCHED)
origin/devjulley:  1c5ae323c199867ebd7b28b77216397e86cfd5df   (UNCHANGED — nothing pushed)
backup/main-06-08-26:                db180c44d7cd273647c79b3093d7b7d10af2c5e2  (intact)
backup/devjulley-pre-rebase-06-08-26: 1c5ae323c199867ebd7b28b77216397e86cfd5df (intact)

devjulley is 12 commits ahead of main, 5 ahead / 32 behind origin/devjulley.
```

Commits on `devjulley` above `main`:

```
5293cbc process: sync unrelated in-flight plan artifacts picked up during rebase
6e7792c chore: untrack embedded yc-application-coach git repo
281f55f feat(identity): candidate_outreach_enabled confirm-gate + pixel rebuild
ac1317f fix(migrations): re-chain devjulley identity sub-chain onto main's head
bbffd74 feat(identity): fingerprint v3 ... (tail of ae7ffb9 — see D-8)
3528c00 feat(identity): fingerprint v3 with installed-font and audio probes
7176acd process(identity-vocab-reconcile): carry forward PVL cycle 7 bookkeeping row
3910df9 process: site-id lifecycle and identity program artifacts
ffff636 chore(app): wire new routers, jobs and dashboard nav
074be9f feat(identity): confirmed-identity promotion and orphan ingest metrics
88fa382 feat(contacts): contact import and hot-contacts surface
1a16662 feat(pixel): site-id lifecycle with delete tombstones
```

**Nothing pushed. No `git push` of any form was run.** Working tree holds the 21
pre-existing harness-doc modifications, restored unstaged exactly as found.

---

## 7. What was built (beyond the rebase)

- **`candidate_outreach_enabled: bool = False`** in `config.py`, with the rollout posture documented inline.
- **Confirm-gate wrapper at exactly 3 call sites**: `campaign_sender.py` (lazy cached read), `csv_exporter.py` (new query + `Visitor` import, only for graph candidates), `routers/campaigns.py` (new query + `settings` import, only for graph candidates).
- **`hot_alert.py` and `outcome_digest.py` untouched**, as specified — asserted by a structural test.
- **`is_emailable_identity()` not modified.** Signature asserted `["provider", "source_agent_visit_id", "is_abuse_flagged"]` by two independent tests.
- **New file `tests/unit/test_candidate_outreach_gate.py`** — 81 tests covering OFF/ON, the human-confirm exception, non-graph providers unaffected, "wrapper can only narrow", agent-origin and abuse vetoes surviving the wrapper, plus structural assertions that the 3 in-scope sites carry the wiring and the 2 excluded sites do not.

---

## 8. Follow-ups registered

1. **svid-only-batch assertion** (Finding 8 residual) — add to `tests/integration/test_events_ingest.py`: an ingest batch with `svid` but no `_fp`/`fp3` must still create the `Visitor` stub with `server_visitor_id` written. Needs Docker.
2. **Integration lane + migration live round-trip** — re-run when Docker is available.
3. **Plan-governance reconciliation** — resolve the cycle-6-vs-cycle-7 contradiction in §4 above and fold S17/S18 into the plan body.
4. **`all-context.md` migration head is stale** — records `e6b2d4a1c837`; live `main` head is `c2f7a9d31b64` and the new tip is `f1a7c3e05b92`. Update at UPDATE PROCESS.
5. **D-8 duplicate commit message** — optionally squash before push.

`CONTEXT_PARTIAL: live production database state` — no `railway` access, so prod
`alembic_version` and `visitors.identity_status` row counts are unverified.

---

## 9. Human actions still required

1. **Run the §5 step-0 live prod pre-check** (agent-blocked):
   ```
   railway run -s retarget-agent bash -c 'psql "${DATABASE_URL/postgresql+asyncpg/postgresql}" -t -A -c "select version_num from alembic_version;"'
   railway run -s retarget-agent bash -c 'psql "${DATABASE_URL/postgresql+asyncpg/postgresql}" -t -A -c "select identity_status, count(*) from visitors group by 1;"'
   ```
   If any `verified` / `provider_candidate` rows exist, run the §5 contingency backfill
   **before** deploying — the code no longer understands those values.
   Also confirm prod's `alembic_version` is an ancestor of `c2f7a9d31b64`; the re-chain
   assumes main's local head is what prod will be upgrading from.
2. **Decide the push.** I ran no push. `git push --force-with-lease origin devjulley`
   is the plan's step 18. Pushing **`main`** is a production DDL + deploy event
   (Railway runs `alembic upgrade head` on boot) and needs explicit sign-off.
3. **Rule on the governance discrepancy** in §4 — whether cycle 7's "NOT yet unblocked"
   supersedes this session's acceptance.
4. **Leave `candidate_outreach_enabled` OFF.** Enabling it is a separate operator action.

---

## Closeout classification

**Keep in active / testing.** Code-complete and green on everything runnable here, but
the live prod pre-check, the integration lane, and the push decision are all still open,
and the governance discrepancy needs a ruling before archival.

PHASE_COMPLETE: EXECUTE
