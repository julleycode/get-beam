---
name: plan:site-id-lifecycle
description: "COMPLEX plan — tombstone-based site_id reuse, wrong_site found-id surfacing, unknown-id ingest observability, delete-dialog pixel warning"
date: 01-08-26
feature: pixel
---

# PLAN — Site Identity Lifecycle (Delete/Re-Create Pixel Orphaning)

**Date**: 01-08-26
**Status**: ACTIVE — plan written, VALIDATE pending
**Complexity:** COMPLEX
**Feature:** pixel

**TL;DR** — Add a `site_tombstones` table written inside the existing hard-delete transaction; on
re-create for the same normalized URL by the same user, reuse the tombstoned `site_id` so the
already-installed pixel keeps working. Add a structured log + Redis counter on the ingest
unknown-site 403 branch (observability, wire contract unchanged). Surface the foreign site id the
pixel verifier already sees in the fetched HTML. Add a pixel-stops-working sentence to the delete
dialog. 27 checklist steps, 1 migration, 9 ACs mapped to gates.

Complexity: **COMPLEX** — multi-package (api + web + migration), live prod DDL on push, and a
security surface (unauthenticated ingest credential + cross-tenant id exposure).

---

## Overview

Root cause: `_generate_site_id()` issues a fresh random id on every `create_site`, with zero
relationship to a site previously deleted for the same domain. The installed tracker keeps sending
the old id, ingest 403s it, and the deployed tracker treats that 403 as terminal self-destruct —
silently, with no log line.

Chosen approach (locked in INNOVATE, not re-litigated here): **tombstone-table id reuse +
wrong_site found-id surfacing + unknown-id observability.**

## Goals

1. Delete → re-create for the same normalized URL by the same user resumes ingestion with **no
   snippet edit** (AC1).
2. Every unknown-`site_id` ingest rejection is logged and aggregatable (AC2, AC3).
3. `wrong_site` verify responses name the foreign id found in the fetched HTML (AC4), without
   creating any cross-tenant lookup capability (AC5).
4. Delete dialog warns that the live pixel stops working (AC6).
5. No weakening of id unguessability (AC7), no change to 404-on-foreign-id posture (AC8), no change
   to the unknown-site ingest wire contract old trackers depend on (AC9).

## Resolved Open Decisions

### D1 — AC3 aggregation surface: structlog event + Redis hourly-bucket counters + a service-level query helper. No new table, no new HTTP endpoint.

- **Why:** Redis is already in the stack and already backs the ingest rate limiters, so this adds
  zero infrastructure. A dedicated durable table would add a *second* migration to a plan that
  already ships prod DDL, for data that is operational telemetry, not business state.
- **Why no HTTP endpoint:** an unknown `site_id` belongs to **no tenant**. The existing
  `/sites/{site_id}/ingest-health` precedent is `verify_site_access`-scoped, so orphan counts
  structurally cannot live there without inventing a cross-tenant admin auth surface — out of
  proportion for this plan and a new security surface the SPEC does not ask for. AC3's stated proof
  is "a unit test on the aggregation surface," which a service-level helper satisfies exactly.
- **Shape:** keys `beam:orphan_ingest:{YYYYMMDDHH}` (global) and
  `beam:orphan_ingest:{YYYYMMDDHH}:{site_id}` (per-id), `INCR` + `EXPIRE` 7 days. Helper
  `orphan_ingest_summary(window_hours)` sums buckets and returns
  `{total, by_site_id, window_hours}`. Operator query recipe documented in the module docstring
  (`railway run -s retarget-agent ...` + the helper, or `redis-cli --scan`).
- **Fail-open:** any Redis error is swallowed and logged at debug. The counter must never be able to
  turn an ingest 403 into a 500.
- **Rejected:** durable counter table (second migration, growth, cron for pruning);
  structured-log-only (AC3 wants an aggregation surface with a test, not a grep recipe).

### D2 — Tombstone retention: keep rows indefinitely, but make **reuse eligibility** expire at 90 days, enforced at read time (no cron).

- **Why:** mirrors the existing `company_graph_staleness_days = 75` read-time-revalidation
  precedent in this repo — no background job to own, no deletion pass to get wrong. A years-old
  tombstone silently resurrecting an id would surprise the user (the pixel almost certainly is not
  still installed), so the reuse window is bounded; the row itself is cheap and worth keeping as an
  audit trail of what id a domain used to have.
- **Setting:** `site_id_reclaim_window_days: int = 90` in `apps/api/config.py`. Lookup filters
  `deleted_at >= now() - window`.
- **Rejected:** unbounded reuse (surprise resurrection); TTL delete job (a cron to own for a table
  measured in dozens of rows).

---

## Touchpoints

| File | Change |
|---|---|
| `apps/api/models/site_tombstone.py` | NEW — `SiteTombstone` model |
| `apps/api/models/__init__.py` (or wherever models are registered) | register new model so metadata/mapper sees it |
| `apps/api/migrations/versions/{rev}_add_site_tombstones.py` | NEW — additive table + indexes |
| `apps/api/routers/sites.py` | `create_site` reuse lookup + race retry; `delete_site` tombstone write; `verify_pixel_endpoint` passes through `found_site_id` |
| `apps/api/schemas/sites.py` | `PixelVerifyResponse` gains `found_site_id: str \| None = None` |
| `apps/api/services/pixel_verifier.py` | extract foreign id in the `wrong_site` branch; `VerifyResult` gains `found_site_id` |
| `apps/api/routers/events.py` | unknown-site 403 branch: structlog event + counter call (response bytes unchanged) |
| `apps/api/services/orphan_ingest_metrics.py` | NEW — `record_orphan_ingest()`, `orphan_ingest_summary()` |
| `apps/api/config.py` | `site_id_reclaim_window_days` |
| `apps/web/src/app/dashboard/page.tsx` | delete dialog copy (AC6) |
| `apps/web/src/lib/api.ts` | `verifyPixel` return type gains `found_site_id?: string \| null` |
| `apps/web/src/components/pixel-install-guide.tsx` | render the found-id hint when `status === "wrong_site"` |
| `tests/integration/test_events_ingest.py` | AC2 + AC9 |
| `tests/integration/test_site_delete.py` | AC1 delete→recreate; AC8 regression |
| `tests/unit/test_pixel_verifier.py` | AC4, AC5 |
| `tests/unit/test_orphan_ingest_metrics.py` | NEW — AC3 |
| `tests/unit/test_site_id_generation.py` | NEW — AC7 |
| `apps/web/e2e/dashboard.spec.ts` | AC6 (Hybrid) |

**Read-only for context (do not modify):** `apps/api/models/site.py`, `apps/api/routers/ingest_health.py`,
`apps/pixel/src/tracker.js`, `apps/api/dependencies.py`.

## Public Contracts

| Contract | Change | Compatibility |
|---|---|---|
| `POST /api/v1/events/ingest` unknown site_id | **NONE** — still 403, same `_rta_svid_*` delete-cookie attrs, same empty body | AC9 hard constraint. Old trackers are frozen; only logging/counters are added, strictly after the `Response` object is built and strictly before `return`. |
| `POST /api/v1/sites/{id}/verify-pixel` | **Additive** — `found_site_id: str \| None` added to `PixelVerifyResponse`; `null` for every status except `wrong_site` | Additive optional field; existing clients ignore it. |
| `POST /api/v1/sites/` | Behavior change: may return a `site_id` previously issued to a deleted site of the SAME user + SAME normalized url within 90 days. Response *shape* unchanged. | No shape change. Dedup / 409 / 402 branches all unchanged and still evaluated first. |
| `DELETE /api/v1/sites/{id}` | Still 204; still the same 17-table hard cascade; one extra INSERT inside the same transaction | Per SPEC out-of-scope: cascade mechanics untouched. |
| `sites.site_id` unique constraint | Unchanged | Reuse only happens after the old row is gone; the concurrent-recreate race is handled by retry, not by relaxing the constraint. |
| DB schema | Additive table `site_tombstones` only | No column added/dropped/altered on any existing table. |

## Blast Radius

- **Packages:** `apps/api` (7 files + 1 new model + 1 new service + 1 migration), `apps/web`
  (3 files), `tests` (6 files).
- **Risk classes present:** schema/data migration (live prod DDL on push);
  permission/trust-boundary (ingest's only write credential + cross-tenant id exposure); public API
  contract (additive).
- **Highest-risk surface:** `create_site`'s tombstone lookup. A missing `user_id` filter would let
  user B's re-create silently adopt user A's old id. Mitigation is structural: the filter is in the
  SQL `WHERE`, never a post-fetch Python check, and is regression-tested (AC5/AC8).
- **Second-highest:** the ingest hot path. Any exception from the counter must not surface — the
  call is wrapped and fail-open.

---

## Implementation Checklist

### Section A — Data layer (steps 1–5)

1. Create `apps/api/models/site_tombstone.py` defining `SiteTombstone` (`__tablename__ =
   "site_tombstones"`): `id: Mapped[uuid.UUID]` PK default `uuid.uuid4`; `site_id: Mapped[str]`
   `String(50)` not null; `normalized_url: Mapped[str]` `String(500)` not null; `user_id:
   Mapped[uuid.UUID]` `UUID(as_uuid=True)` not null; `deleted_at: Mapped[datetime]`
   `DateTime(timezone=True)` not null `server_default=func.now()`. Follow `apps/api/models/site.py`
   import/style exactly. Type hints 3.11-safe (`str | None`, no `Optional`).
   **No unique constraint on `site_id`** — a domain can be deleted/recreated repeatedly; the lookup
   orders by `deleted_at DESC` and takes the newest.
2. Add a composite index `ix_site_tombstones_user_url` on `(user_id, normalized_url, deleted_at)`
   (the exact lookup shape from step 8).
3. Register the model wherever the other models are imported for metadata (grep for
   `from apps.api.models.site import Site` in `apps/api/main.py` / `apps/api/models/__init__.py`
   and follow the existing registration pattern — the ORM mapper-registry gotcha means an
   unregistered model breaks unit tests that construct ORM objects).
4. Run `.venv/bin/python3.11 -c "import apps.api.main"` to confirm the mapper registry configures.
5. Add to `apps/api/config.py`, near the other lifecycle settings:
   `site_id_reclaim_window_days: int = 90` with an inline comment stating: reuse eligibility only,
   rows are never deleted, read-time enforced (mirrors `company_graph_staleness_days`).

### Section B — Migration (steps 6–7)

6. Re-confirm the live head FIRST: `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads`.
   Do **not** trust the head recorded in `process/context/all-context.md` (`e6b2d4a1c837`) — it is
   known to be behind (`f3c8b2e91d47` is on disk). Chain `down_revision` off the REAL single head
   returned by that command. If `heads` returns 2+ heads, STOP and report — do not force-merge.
   **VALIDATE-time re-confirmation (04-08-26): the real live head is neither of the above — see
   Validate Contract Dimension Findings §Migration Chain below. Do not reuse any head value
   recorded anywhere in this plan or in `all-context.md`; re-run the command fresh at EXECUTE
   time.**
7. Create `apps/api/migrations/versions/{rev}_add_site_tombstones.py` following the
   `f3c8b2e91d47_add_agent_fetch_link_marker.py` pattern (module docstring explaining what and why
   it is additive/reversible, then `revision`/`down_revision`/`branch_labels`/`depends_on`).
   `upgrade()` = `op.create_table("site_tombstones", ...)` + `op.create_index(...)`;
   `downgrade()` = drop index then drop table. Purely additive: no backfill, no constraint on an
   existing table, no data rewrite.
   **Do NOT call `sa.inspect(bind)`** — that is what makes `b7d3e9f1a4c2` offline-unsafe.
   Validate offline with an explicit range, never bare `head`:
   `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade {real_head}:head --sql`
   and the matching `downgrade head:{real_head} --sql`.
   Note for the operator: Railway auto-applies `alembic upgrade head` on boot, so merging to `main`
   IS the prod DDL apply.

### Section C — Delete writes the tombstone (steps 8–9)

8. In `delete_site` (`apps/api/routers/sites.py`), inside the existing `try:` block and **before**
   `await db.delete(site)`, `db.add(SiteTombstone(site_id=site.site_id, normalized_url=site.url,
   user_id=site.user_id))`. It rides the same single transaction — a cascade failure rolls the
   tombstone back too, so a tombstone can never exist for a site that still exists.
9. Extend the existing `logger.info("site_deleted", ...)` call with `tombstoned=True`. Log
   `site_id` and counts only — no PII (site_id is not PII; do not add url/email).

### Section D — Create reuses the tombstone (steps 10–13)

10. In `create_site`, **after** the existing dedup / 409 / same-user-return branches and **after**
    the per-plan site-limit check (so no branch ordering changes), add the tombstone lookup:
    ```
    SELECT ... FROM site_tombstones
    WHERE user_id = :current_user_id
      AND normalized_url = :normalized_url
      AND deleted_at >= now() - interval '{site_id_reclaim_window_days} days'
    ORDER BY deleted_at DESC LIMIT 1
    ```
    `user_id` MUST be a SQL `WHERE` predicate, not a post-fetch Python check. Use the same
    `variants` set the dedup block builds so www/trailing-slash normalization matches.
11. If a tombstone is found, build the `Site` with `site_id=tombstone.site_id` and `db.delete(tombstone)`
    (consume it) in the same transaction. If not found, `site_id=_generate_site_id()` exactly as today.
12. Wrap the insert+commit in a savepoint to survive the concurrent-recreate race: `async with
    db.begin_nested():` around `db.add(site)`; on `sqlalchemy.exc.IntegrityError` (unique violation
    on `sites.site_id`) log `site_id_reuse_collision` and retry ONCE with
    `site_id=_generate_site_id()` and no tombstone consumption. A second failure propagates as a
    500. Do not loop more than once.
13. Log `site_created` with `site_id`, `reused_tombstone: bool`. site_id only — no url, no email.

### Section E — Ingest observability (steps 14–17)

14. Create `apps/api/services/orphan_ingest_metrics.py` with a module docstring stating what it
    counts, the key shape, the 7-day TTL, the fail-open rule, and the operator query recipe.
15. `async def record_orphan_ingest(site_id: str) -> None` — `INCR` both
    `beam:orphan_ingest:{YYYYMMDDHH}` and `beam:orphan_ingest:{YYYYMMDDHH}:{site_id}`, `EXPIRE`
    each to 7 days. Reuse the existing Redis accessor (grep for `get_redis` / `settings.redis_url`
    and follow the existing async client pattern). Entire body inside `try/except Exception` →
    `logger.debug("orphan_ingest_counter_failed", ...)`. Never raises. `MOCK_EXTERNAL_APIS` needs no
    special branch (Redis is first-party infra, not an external API), but the helper must no-op
    cleanly when Redis is unreachable — which is what the fail-open wrapper gives.
16. `async def orphan_ingest_summary(window_hours: int = 24) -> dict` — sum the last `window_hours`
    hourly buckets, return `{"window_hours": n, "total": int, "by_site_id": {site_id: count}}`.
    Returns zeros (not an exception) when Redis is unavailable.
17. In `apps/api/routers/events.py`, in the `if tracking_enabled is None:` branch: after `gone` is
    fully constructed (including `delete_cookie`) and immediately before `return gone`, add
    `logger.warning("ingest_unknown_site", site_id=batch.site_id, rejected_as="unknown_site")` then
    `await record_orphan_ingest(batch.site_id)`. **Do not change the status code, the response body,
    or any cookie attribute** — AC9. Add a code comment saying so explicitly.

### Section F — Verifier surfaces the found id (steps 18–21)

18. In `pixel_verifier.py`, after `has_correct_site` is computed and only when
    `has_tracker and not has_correct_site`, run a **generic capture** regex parallel to the existing
    `has_correct_site` patterns — same `_win` window, same scoped `(?i:data-site)` key-only
    case-insensitivity, capture `(site_[0-9a-f]{6,32})` instead of the escaped known id; plus the
    query-param shape `(?:[?&]|&amp;|&#0*38;)site=(site_[0-9a-f]{6,32})`. Take the first match.
    Do NOT `html.unescape()` the document (same false-positive reasoning documented in the existing
    comment).
19. Add `found_site_id: str | None = None` to `VerifyResult`; populate it only on the `wrong_site`
    branch (`None` everywhere else, including `not_found`, `fetch_error`, `verified`).
    **Execute-agent note (found at VALIDATE):** `verify_pixel()` falls back to `_verify_via_events()`
    whenever the static check does not verify and a `db` session is passed (the live endpoint always
    passes one) — if the CURRENT site_id also has live event traffic within the last 7 days, that
    fallback overrides a `wrong_site` verdict with `verified`, discarding `found_site_id` entirely.
    This is pre-existing behavior, not a regression, and not a security issue — flagging only so
    step 19/20 tests account for it (call `verify_pixel(..., db=None)` or ensure no recent events
    exist for the test site_id in the `wrong_site` fixtures, exactly as the existing unit tests
    already do by omitting `db`).
20. Make the `wrong_site` message actionable when an id was found: e.g. `"This page currently has
    Beam site {found} installed, not this site. Update the snippet on your page to this site's ID,
    or re-create the site for this domain to reuse the installed ID."` Fall back to today's generic
    message when no id could be extracted. Extend the existing
    `logger.info("pixel_wrong_site", ...)` with `found_site_id=`.
21. **Security boundary (AC5) — do not implement any of these:** no DB lookup of the found id, no
    ownership resolution, no "this belongs to site X" enrichment, no reverse index. The found id is
    returned as a **bare string already present in that domain's public HTML**. Add an explicit
    code comment stating this. If a future reconnect affordance is added it must be gated on
    `tombstone.user_id == current_user.id`, which is out of scope here.

### Section G — API + UI wiring (steps 22–25)

22. `apps/api/schemas/sites.py`: add `found_site_id: str | None = None` to `PixelVerifyResponse`
    (optional with default → additive, existing clients unaffected).
23. `apps/api/routers/sites.py` `verify_pixel_endpoint`: pass
    `found_site_id=verify_result.get("found_site_id")` into the response. No new auth logic.
24. `apps/web/src/lib/api.ts` `verifyPixel`: add `found_site_id?: string | null` to the inline
    response type.
25. `apps/web/src/components/pixel-install-guide.tsx`: when `status === "wrong_site"` and
    `found_site_id` is present, render the found id in a copyable/monospace hint next to the
    existing message. Display only — no fetch, no lookup.

### Section H — Delete dialog warning (step 26)

26. `apps/web/src/app/dashboard/page.tsx` delete `DialogDescription`: append a second sentence,
    visually distinct (e.g. its own `<p className="text-sm text-destructive">` inside the
    description block) reading: **"Your installed pixel will also stop working — the tracking
    snippet on your website will start being rejected until you re-add this site or install a new
    snippet."** Must render before the user can press Delete (it is inside the same dialog, above
    `DialogFooter`).

### Section I — Verification (step 27)

27. Run the full gate set in `## Verification Evidence` order and record results.

---

## Explicitly NOT In Scope (restated from SPEC — do not drift)

- **No soft-delete / undo / historical-data restore.** The 17-table hard cascade, its ordering, and
  its single-transaction mechanics are untouched. Tombstones store id + url + user + timestamp
  ONLY — never event, visitor, or identity data.
- **No DNS-TXT or file-upload domain verification.** The existing fetch-our-page verification is the
  only ownership proof.
- **No billing/plan/quota changes.** The per-plan site-limit check keeps its current position and
  semantics.
- **No multi-site-per-domain feature.**
- **No remediation campaign** for trackers already self-destructed by a past occurrence.
- **No tracker.js changes.** `apps/pixel/src/tracker.js` is read-only for this plan; AC9 is
  satisfied by *not* changing the backend contract, not by shipping a new tracker.
- **No new admin/cross-tenant HTTP endpoint** (see D1).
- **No reverse lookup or reconnect button** built on the found site id (see step 21).

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `tests/integration/test_site_delete.py::test_delete_then_recreate_same_domain_reuses_site_id` (NEW) — create site, capture id, ingest OK, DELETE, re-POST same url, assert new site's `site_id == old id`, then POST /ingest with the ORIGINAL id → 204 | Hybrid — precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis` (see Validate Contract: this repo's integration lane requires a live Postgres+Redis; corrected from "Fully-Automated" in earlier drafts of this row — no CI-runnable-without-setup path exists for it) | AC1 |
| `tests/integration/test_site_delete.py::test_recreate_outside_reclaim_window_gets_fresh_id` (NEW) — backdate `deleted_at` beyond `site_id_reclaim_window_days`, assert a fresh id | Hybrid — same precondition as above | AC1 (window bound, D2) |
| `tests/integration/test_events_ingest.py::test_unknown_site_logs_structured_event` (NEW, alongside `:95-138`) — `structlog` capture asserts an `ingest_unknown_site` event with `site_id` on the 403 path | Hybrid — same precondition as above | AC2 |
| `tests/unit/test_orphan_ingest_metrics.py` (NEW) — fake/monkeypatched Redis: `record_orphan_ingest` increments the right hourly keys with TTL; `orphan_ingest_summary` sums a window and buckets `by_site_id`; a raising Redis returns zeros and never propagates | Fully-Automated | AC3 |
| `tests/unit/test_pixel_verifier.py::test_wrong_site_returns_found_id` (extends `:89`) — assert `res["found_site_id"] == "site_ffffffffffff"` for the existing wrong_site fixture, plus escaped/RSC/query-param shape variants | Fully-Automated | AC4 |
| `tests/unit/test_pixel_verifier.py::test_wrong_site_never_resolves_foreign_owner` (NEW) — verifier called with no DB session available for lookup; assert the result dict contains ONLY the bare id string and no owner/name/url of any other tenant's site; assert the module makes no `Site` query on this branch | Fully-Automated | AC5 |
| `tests/unit/test_site_id_generation.py` (NEW) — assert `_generate_site_id()` produces distinct ids across N calls for the same url input, i.e. no deterministic url→id function; assert a reused id still matches the original random `site_[0-9a-f]{12}` shape (reuse preserves randomness, does not create derivability) | Fully-Automated | AC7 |
| `tests/integration/test_site_delete.py` existing non-owner/unknown-site cases + NEW `test_foreign_tombstone_not_reused` — user B re-creates the same url after user A deleted it → user B gets a FRESH id and A's tombstone is untouched; foreign/unknown site ids still 404 | Hybrid — precondition: docker compose postgres+redis (corrected from "Fully-Automated" — see Validate Contract) | AC5, AC8 |
| `tests/integration/test_events_ingest.py::test_invalid_site_returns_403` + `::test_deleted_site_403_expires_svid_cookie` (existing, unmodified) still pass byte-identically | Hybrid — precondition: docker compose postgres+redis (corrected from "Fully-Automated" — see Validate Contract) | AC9 |
| `apps/web/e2e/dashboard.spec.ts` — delete-dialog copy assertion: dialog contains both "can't be undone" and text matching `/pixel will also stop working/i` before Delete is clickable | Hybrid — precondition: Next dev server + Clerk auth harness. **Known gap fallback:** if the Clerk auth-harness gap (documented for ads-audiences Phase 1/2 and cadence-bot-flag) blocks the authed run, downgrade to Agent-Probe (agent renders the dialog and reads the copy) and register a backlog stub. Do NOT mark AC6 PASS on Known-Gap alone — the gate stays CONDITIONAL. | AC6 |
| `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade {real_head}:head --sql` + matching `downgrade --sql` exit 0 | Fully-Automated | Migration safety (SPEC Constraints) |
| Live round-trip `upgrade head` → `downgrade -1` → `upgrade head` on a disposable Postgres container | Hybrid — precondition: Docker daemon up. **Confirmed at VALIDATE (04-08-26): no `docker`/`colima`/`podman` binary exists in the validating sandbox — this gate could not even be attempted here.** If Docker is still unavailable at EXECUTE time: register a backlog stub matching the existing `ingest-abuse-hardening-deferred-gates` / `cadence-bot-flag-deferred-gates` precedent; gate stays CONDITIONAL. | Migration safety |
| `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` (full unit lane, regression) | Fully-Automated | No-regression |
| `.venv/bin/python3.11 -m pytest tests/ -m integration -q` (full integration lane, regression) | Hybrid — precondition: docker compose postgres+redis (corrected — same as above) | No-regression |
| `cd apps/web && npm run lint` | Fully-Automated | No-regression (web) |

**Vacuous-green note:** no developed behavior in this plan terminates on Known-Gap. The two
environment-gated rows above (AC6 Playwright leg, migration live round-trip) each keep their gate
CONDITIONAL and require a backlog stub if they cannot run — they are never a PASS.

**Precondition for integration lane:** `docker compose -f infra/docker-compose.yml up -d postgres redis`.
Check `docker ps` for a stray Redis on 6379 before blaming unit-lane failures (known local gotcha).
Use `.venv/bin/python3.11 -m pytest` — the `.venv/bin/pytest` shebang is broken in this repo.

**VALIDATE tier correction (04-08-26):** every row above whose command is `tests/integration/*`
was corrected from `Fully-Automated` to `Hybrid` — `process/context/tests/all-tests.md`'s own
Test Tier Waterfall classifies anything needing `docker compose ... up -d postgres redis` as
Hybrid, not Fully-Automated, regardless of how deterministic the test is once the precondition is
met. This does not change what must be built; it changes which gates block EXECUTE-completion
autonomously vs. require the Docker precondition to be confirmed first. See Validate Contract
Dimension Findings below.

## Test Infra Improvement Notes

(none identified yet)

---

## Dependencies and Risks

| Risk | Mitigation |
|---|---|
| Tombstone lookup missing `user_id` → cross-tenant id adoption | `user_id` is a SQL WHERE predicate (step 10), regression-tested (AC5/AC8) |
| Concurrent recreate → unique violation on `sites.site_id` | savepoint + single retry with a fresh id (step 12) |
| Counter call raises inside the ingest hot path | fail-open `try/except` in the helper (step 15); call placed after the Response object is built |
| Alembic head drifts between PLAN and EXECUTE | step 6 mandates a live `alembic heads` re-check; hardcoded heads are forbidden |
| Offline `--sql` validation fails mid-chain | explicit `{real_head}:head` range required; new migration must not call `sa.inspect(bind)` (step 7) |
| Merging to `main` applies prod DDL | additive-only table; called out in step 7 for the operator |
| Verifier capture regex over-matches (false found-id) | reuse the existing `_win` window + trailing-boundary lookahead; no `html.unescape()`; shape-variant tests |

**Backwards compatibility:** the ingest unknown-site response is byte-identical; the verify response
gains one optional field; no existing column or constraint is altered. Old deployed trackers are
unaffected by every change in this plan.

**Rollback:** `alembic downgrade -1` drops `site_tombstones` (additive, no data dependency). Code
changes are a single revert; with the table gone, `create_site` falls back to the fresh-id path,
which is exactly today's behavior.

## Acceptance Criteria (measurable)

All 9 SPEC ACs, each with a named `proven by` gate and a `strategy` tag, are enumerated in
`## Verification Evidence` above — that table is the authoritative criterion↔gate mapping.

---

## Phase Completion Rules

This plan is a single-phase COMPLEX plan (Sections A–I), not a phase program. Section-level rules:

- A section is `CODE DONE` when every checklist step in it is implemented.
- A section is `✅ VERIFIED` only when its gates in `## Verification Evidence` are green with
  recorded evidence AND the user has explicitly confirmed the evidence. Code-only completion is
  never `VERIFIED`; no agent may self-promote a section to VERIFIED without that user confirmation.
- Run each section's gates before starting the next section — do not batch all tests to the end.
- Section B (migration) is a hard gate: no migration file may be authored before the live
  `alembic heads` re-check in step 6 returns a single head.
- The whole plan is complete only when all 9 SPEC ACs have a green or explicitly-CONDITIONAL
  (backlog-stubbed) gate. A CONDITIONAL gate blocks `✅ VERIFIED` for the plan but does not block
  EXECUTE closeout.

---

## Validate Contract

Status: CONDITIONAL
Date: 04-08-26
date: 2026-08-04
generated-by: outer-pvl

Parallel strategy: sequential
Rationale: Signal score 3/7 (S1 multi-package, S2 schema/API/auth surface, S6 high-risk class,
S7 5+ files — S6/S7 collapse into one dominant "high-risk single-plan COMPLEX change" signal).
Below the 4+ HIGH threshold; this is a single COMPLEX plan, not a phase program, and Layer
1+Layer 2 fan-out for this VALIDATE pass was run as parallel subagents-equivalent research in one
session (8 dimensions/sections investigated: 4 Layer 1 + 9 Layer 2 areas condensed to file-level
sections A–I). EXECUTE itself should run sequentially, section by section, per the plan's own
"run each section's gates before starting the next section" rule — sequential is the correct fit,
not a fan-out.

### I. Touchpoint Accuracy (spot-checked against live source, 04-08-26)

| Claim | File:location | Verdict |
|---|---|---|
| Models registered in `apps/api/main.py`, not `models/__init__.py` (which is empty) | `apps/api/main.py:15-44` | ✅ Confirmed — plan step 3 already hedges correctly ("or wherever models are registered") and instructs grepping `main.py` |
| `events.py` unknown-site 403 branch: `gone = Response(status_code=403)` → `delete_cookie(...)` → `return gone` | `apps/api/routers/events.py:171-191` | ✅ Confirmed exact insertion point for step 17 (after `delete_cookie`, before `return gone`) |
| `pixel_verifier.py` `wrong_site` branch has `_win`, `id_pat`, query-param regex ready to parallel for a capture group | `apps/api/services/pixel_verifier.py:164-187` | ✅ Confirmed — step 18's proposed capture regex is a mechanical parallel of the existing pattern |
| `PixelVerifyResponse` schema + `verify_pixel_endpoint` response-builder site | `apps/api/schemas/sites.py:87`, `apps/api/routers/sites.py:359-364` | ✅ Confirmed — step 22/23 additive field lands cleanly |
| `create_site` branch order: dedup/409 (L59-80) → site-limit (L82-117) → site build (L119-130) | `apps/api/routers/sites.py:52-130` | ✅ Confirmed — step 10's insertion point ("after site-limit check") is correct; `variants` set (L66) is always defined by the time that point is reached |
| `delete_site` existing `try:` block, tombstone write point before `db.delete(site)` | `apps/api/routers/sites.py:185-238` | ✅ Confirmed — step 8 insertion point correct, same transaction |
| `Site.site_id` `unique=True`, no `deleted_at` anywhere in the model | `apps/api/models/site.py:15` | ✅ Confirmed — matches SPEC Constraints |
| `get_redis()` accessor exists; `db.begin_nested()` savepoint pattern has no prior precedent in this repo but `get_db()` uses session autobegin (`async with async_session() as session: yield session`), so a nested SAVEPOINT is mechanically sound | `apps/api/services/redis_client.py:19`, `apps/api/models/database.py:91-93` | ✅ Confirmed feasible — net-new pattern for this codebase, no existing precedent to copy; flagged as an execute-agent note, not a blocker |
| `verify_site_access` already does the `user_id` SQL-WHERE-predicate ownership pattern step 10 needs to mirror | `apps/api/dependencies.py:29-43` | ✅ Confirmed — direct precedent exists for the exact mitigation the highest-risk surface requires |
| All 17 files in Touchpoints table exist on disk | (full list in `## Touchpoints`) | ✅ Confirmed — all 17 resolved via direct filesystem check |

### II. Migration Chain (live-verified 04-08-26)

```
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads
→ b1c9e7f24d83 (head)
```

**Critical finding — the plan's own recorded guesses are already stale, and the plan's step 6
defense is exactly what saves it:**

- `all-context.md` records head `e6b2d4a1c837` (known stale, per the plan's own step 6 note).
- The plan's step 6 guesses `f3c8b2e91d47` is "on disk" and more current — also now stale.
- The **actual live head** confirmed via `alembic heads` at VALIDATE time is **`b1c9e7f24d83`**
  (`add_identified_visitor_confirmed_at`) — 9 migrations ahead of the plan's own guess
  (`f3c8b2e91d47 → a7d419e6c052 → b1c9e7f24d83`, chain confirmed via `alembic history`).
- **`b1c9e7f24d83_add_identified_visitor_confirmed_at.py` is an UNCOMMITTED, UNTRACKED file**
  (`git status` shows `??`) belonging to a concurrent session
  (`process/features/visitors-identity/active/identity-program_03-08-26/`). Alembic reads the
  `versions/` directory on disk regardless of git tracking state, so it sees and resolves against
  this file today. If that concurrent session's file is committed unchanged before this plan's
  EXECUTE runs, chaining off `b1c9e7f24d83` is safe. If it is amended (different revision id) or
  removed before EXECUTE, the live head will be different again.
- Single head confirmed — no branching (`alembic heads` returned exactly one line).

**Execute-Agent Instruction (mandatory, ties to plan step 6):** the plan's own instruction to
"re-confirm the live head FIRST" and "do not trust the head recorded in `all-context.md`" is
correct and must be followed literally — EXECUTE must re-run `alembic -c apps/api/alembic.ini
heads` fresh at Section B execution time and MUST NOT reuse `b1c9e7f24d83` (this contract's
recorded value) or `f3c8b2e91d47` (the plan's original guess) without re-confirming. If `alembic
heads` returns 2+ heads at that time, STOP per the plan's own step 6 rule — do not force-merge.

### III. Test Coverage Plan (test-tier-corrected, all-tests.md Test Tier Waterfall applied)

**Context discovery confirmed:** `process/context/tests/all-tests.md` loaded; Test Tier Waterfall
followed. Existing blast-radius test files discovered and read (`tests/unit/test_pixel_verifier.py`,
`tests/integration/test_events_ingest.py`, `apps/api/models/site.py`, `apps/api/dependencies.py`).

**Docker/runtime availability confirmed at VALIDATE time (04-08-26):** `docker`, `colima`, and
`podman` binaries are ALL absent from this validating sandbox (`command not found` on all three).
Every `tests/integration/*` gate and the live migration round-trip gate are therefore **not
attemptable in this environment at all** — not merely "daemon down." This is a stronger statement
than the plan's own "if Docker is down at EXECUTE time" hedge; whether Docker exists at EXECUTE
time is unknown and must be re-checked there independently.

**Tier correction applied:** the plan's `## Verification Evidence` table originally tagged every
`tests/integration/*` row as `Fully-Automated`. Per `all-tests.md`'s own waterfall (Hybrid =
"requires a precondition... not always available in CI, but deterministic once set up" — exactly
what `docker compose -f infra/docker-compose.yml up -d postgres redis` is), these rows are
correctly `Hybrid`, not `Fully-Automated`. This has been corrected in the `## Verification
Evidence` table above (in-place, non-behavioral edit — no scenario or command changed, only the
tier label and a note). Unit-tier tests (`tests/unit/*`) remain genuinely `Fully-Automated` —
keyless, no DB, `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` collects/runs without any
external precondition.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC1 | delete→recreate same domain reuses site_id; ingest with the original id succeeds post-recreate | Hybrid | `tests/integration/test_site_delete.py::test_delete_then_recreate_same_domain_reuses_site_id` (NEW) — precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis` | A |
| AC1 (window bound, D2) | tombstone reuse eligibility expires at `site_id_reclaim_window_days` | Hybrid | `tests/integration/test_site_delete.py::test_recreate_outside_reclaim_window_gets_fresh_id` (NEW) — same precondition | A |
| AC2 | unknown-site 403 emits a structured `ingest_unknown_site` log event | Hybrid | `tests/integration/test_events_ingest.py::test_unknown_site_logs_structured_event` (NEW) — same precondition | A |
| AC3 | orphan-ingest volume aggregatable by operators | Fully-Automated | `tests/unit/test_orphan_ingest_metrics.py` (NEW) — monkeypatched Redis, no DB | A |
| AC4 | `wrong_site` response includes the foreign `found_site_id` | Fully-Automated | `tests/unit/test_pixel_verifier.py::test_wrong_site_returns_found_id` (extends `:89`) | A |
| AC5 | found id never resolves/exposes a foreign owner (no DB lookup on that branch) | Fully-Automated | `tests/unit/test_pixel_verifier.py::test_wrong_site_never_resolves_foreign_owner` (NEW) | A |
| AC5, AC8 | cross-tenant tombstone isolation; foreign/unknown ids stay 404 | Hybrid | `tests/integration/test_site_delete.py::test_foreign_tombstone_not_reused` (NEW) + existing non-owner/unknown-site cases — same precondition | A |
| AC6 | delete dialog states permanence + pixel-stops-working before confirm | Hybrid (Agent-Probe fallback) | `apps/web/e2e/dashboard.spec.ts` — precondition: Next dev server + Clerk auth harness (**known gap**: repo-wide Playwright auth-harness gap, see ads-audiences/cadence-bot-flag precedent). Fallback: agent renders the dialog and reads the copy | D — backlog stub required if the auth-harness gap still blocks at EXECUTE; gate stays CONDITIONAL, never PASS on the Agent-Probe fallback alone |
| AC7 | `_generate_site_id()` has no deterministic url→id function; reused id keeps the random shape | Fully-Automated | `tests/unit/test_site_id_generation.py` (NEW) | A |
| AC9 | unknown-site ingest response is byte-identical (status, cookie attrs, empty body) | Hybrid | `tests/integration/test_events_ingest.py::test_invalid_site_returns_403` + `::test_deleted_site_403_expires_svid_cookie` (existing, unmodified) — same precondition | A |
| Migration safety | offline chain validates both directions from the real head | Fully-Automated | `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade {real_head}:head --sql` + `downgrade head:{real_head} --sql`, where `{real_head}` = the value returned by a FRESH `alembic heads` run at EXECUTE time (never the value recorded in this contract) | A |
| Migration safety | live round-trip on a disposable Postgres | Hybrid | `upgrade head` → `downgrade -1` → `upgrade head` on a disposable container — precondition: Docker (**confirmed unavailable in this validating sandbox**; unknown at EXECUTE, re-check there) | D — backlog stub if still unavailable at EXECUTE, matching `ingest-abuse-hardening-deferred-gates` / `cadence-bot-flag-deferred-gates` precedent |
| No-regression | full unit lane stays green | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` | A |
| No-regression | full integration lane stays green | Hybrid | `.venv/bin/python3.11 -m pytest tests/ -m integration -q` — precondition: docker compose postgres+redis | A |
| No-regression (web) | lint stays green | Fully-Automated | `cd apps/web && npm run lint` (confirmed script exists: `apps/web/package.json` `"lint": "next lint"`) | A |

gap-resolution legend:
- A — proven now (gate passes in this cycle, once its precondition is met)
- B — fixed in this plan (gate added by this plan's checklist)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: `strategy:` carries only Fully-Automated / Hybrid / Agent-Probe. Known-Gap
never appears as a `strategy:` value in this table — AC6's Agent-Probe fallback and the migration
live-round-trip's D-resolution are named residuals, not proving strategies.

Legacy line form:
- data layer (Section A): Fully-automated: `.venv/bin/python3.11 -c "import apps.api.main"` (mapper registry smoke, step 4)
- migration (Section B): Hybrid: `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` + offline `--sql` both directions | Hybrid: live round-trip on disposable Postgres (precondition: Docker — unavailable here)
- delete/create lifecycle (Sections C/D, AC1/AC5/AC8): Hybrid: `tests/integration/test_site_delete.py` (precondition: docker compose postgres+redis)
- ingest observability (Section E, AC2/AC3/AC9): Fully-automated: `tests/unit/test_orphan_ingest_metrics.py` | Hybrid: `tests/integration/test_events_ingest.py` (precondition: docker compose postgres+redis)
- verifier found-id (Section F, AC4/AC5/AC7): Fully-automated: `tests/unit/test_pixel_verifier.py`, `tests/unit/test_site_id_generation.py`
- API+UI wiring (Section G): Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` (schema/type coverage) | Fully-automated: `cd apps/web && npm run lint`
- delete dialog (Section H, AC6): Hybrid: `apps/web/e2e/dashboard.spec.ts` (precondition: Next dev server + Clerk auth harness — known gap) | agent-probe: fallback dialog-copy read

### IV. Dimension findings

- Infra fit: PASS — no port/container/runtime conflicts; Redis and Postgres are already
  first-party infra; new service module follows existing async-client conventions
  (`redis_client.py`, `rate_limiter.py`).
- Test coverage: CONCERN — the plan's own Verification Evidence table mislabeled every
  `tests/integration/*` row as Fully-Automated; corrected to Hybrid in this contract (see §III).
  Additionally, Docker is confirmed absent from this validating sandbox, so 8 of 15 gates are
  untestable here and must run in an environment with Docker, or fall back to the plan's own
  documented backlog-stub path.
- Breaking changes: PASS — Public Contracts table is accurate; AC9 byte-identical-response claim
  mechanically verified against live source (insertion point is strictly after the `Response`
  object and its `delete_cookie` call, strictly before `return`); `PixelVerifyResponse` change is
  additive-optional.
- Security surface: CONCERN — design is sound (the highest-risk surface, the tombstone `user_id`
  SQL-WHERE predicate, mirrors the existing `verify_site_access` pattern exactly, and AC5/AC8 both
  have dedicated regression tests), but this plan touches TWO high-risk classes at once
  (schema/data migration + permission/trust-boundary logic per
  `process/development-protocols/orchestration.md` §High-Risk Execution Handoff). Recommend
  `vc-risk-evidence-pack` be produced before EXECUTE is marked closed — not a blocker to starting
  EXECUTE, but should exist before the plan is called `✅ VERIFIED`.
- Section A (data layer): PASS — model conventions, mapper-registration path, and config placement
  all mechanically confirmed against live source.
- Section B (migration): CONCERN — see §II. The plan's own defensive instruction (re-check
  `alembic heads` live, never trust a recorded value) is correct and sufficient PROVIDED it is
  followed literally at EXECUTE time; flagged as a mandatory Execute-Agent Instruction (E1 below)
  because the live head has now drifted twice since this plan was written (once before VALIDATE,
  documented in the plan; once again, discovered during VALIDATE) and the file it currently
  depends on is uncommitted.
- Section C (delete writes tombstone): PASS — transaction placement confirmed exact.
- Section D (create reuses tombstone): PASS — branch ordering, `variants` reuse, and the
  `db.begin_nested()` savepoint pattern all confirmed mechanically sound (no prior precedent for
  `begin_nested` in this repo, but `get_db()`'s session-autobegin behavior makes a nested SAVEPOINT
  straightforward).
- Section E (ingest observability): PASS — fail-open wrapper design is correct; note the hot path
  now `await`s a Redis round-trip before returning (previously synchronous-only) — acceptable given
  local Redis + fail-open, but worth watching if p99 ingest latency is monitored.
- Section F (verifier found id): PASS — regex design confirmed as a mechanical parallel of the
  existing pattern; security boundary (no DB lookup) confirmed structurally absent from the module.
  One execute-agent note added inline in the plan (step 19) re: `_verify_via_events` fallback
  interaction — not a defect, an implementation-order note for the new unit tests.
- Section G (API+UI wiring): PASS — additive schema field and response-builder site confirmed.
- Section H (delete dialog): PASS — `DialogDescription`/`DialogFooter` structure confirmed; new
  copy renders before `DialogFooter` as required.
- Section I (verification): PASS — matches the corrected Verification Evidence table.

### V. Execute-Agent Instructions

| # | Instruction | Trigger condition |
|---|---|---|
| E1 | Before authoring the migration file (step 7), run `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` fresh. Do NOT reuse `b1c9e7f24d83` (this contract's recorded value) or `f3c8b2e91d47` (the plan's original guess) without re-confirming — both may be stale by EXECUTE time. If 2+ heads are returned, STOP and report; do not force-merge. | Section B, step 6/7 |
| E2 | When writing the new unit tests for step 19/20 (`test_wrong_site_returns_found_id`, `test_wrong_site_never_resolves_foreign_owner`), call `pixel_verifier.verify_pixel(url, site_id)` WITHOUT a `db` argument (matching the existing test pattern at `tests/unit/test_pixel_verifier.py`) — passing `db` would route through `_verify_via_events` and could mask the static `wrong_site` result if the test fixture happens to also stub recent events. | Section F, steps 18-20 |
| E3 | Attempt the integration lane and the live migration round-trip gate with `docker compose -f infra/docker-compose.yml up -d postgres redis` / a disposable Postgres container FIRST. Only fall back to the plan's documented backlog-stub path (matching `ingest-abuse-hardening-deferred-gates` / `cadence-bot-flag-deferred-gates`) if Docker is confirmed unavailable in the EXECUTE environment too — do not assume unavailability from this validate-contract. | Section B step 7 (live round-trip), Section I step 27 (integration lane) |
| E4 | Before marking this plan `✅ VERIFIED` (not before EXECUTE, but before plan closeout), produce a `vc-risk-evidence-pack` (risk-gate.json / context-snippets.json / verification.json / review-decision.json / adversarial-validation.json) for the tombstone reuse lookup + migration, per `process/development-protocols/orchestration.md` §High-Risk Execution Handoff — two high-risk classes are touched (schema/migration + permission/trust-boundary). | Plan closeout / before `✅ VERIFIED` |

### VI. Backlog Artifacts (conditional — create only if the gate is not met at EXECUTE)

| Artifact | Location | What it tracks |
|---|---|---|
| `site-id-lifecycle-migration-live-roundtrip_NOTE_[date].md` (create only if Docker is still unavailable at EXECUTE) | `process/features/pixel/backlog/` | Live `upgrade head → downgrade -1 → upgrade head` round-trip on a disposable Postgres, matching the `ingest-abuse-hardening-deferred-gates` precedent |
| `site-id-lifecycle-ac6-playwright-auth-harness_NOTE_[date].md` (create only if the Clerk auth-harness gap still blocks AC6's e2e leg at EXECUTE) | `process/features/pixel/backlog/` | AC6 delete-dialog copy assertion via a real authed Playwright run, matching the ads-audiences/cadence-bot-flag precedent |

### VII. Open gaps

- Migration live round-trip (Docker-gated) — confirmed unavailable in this validating sandbox;
  status at EXECUTE unknown. See E3, backlog artifact in §VI if still unavailable.
- AC6 Playwright e2e leg (Clerk auth-harness gap, repo-wide known issue) — see backlog artifact in
  §VI if still blocked at EXECUTE.
- `vc-risk-evidence-pack` not yet produced (deferred to plan closeout per E4, not a pre-EXECUTE
  blocker).

### What this coverage does NOT prove

- The `tests/unit/*` Fully-Automated gates (AC3, AC4, AC5, AC7) prove unit-level logic correctness
  only — they do NOT prove the full request/response cycle through FastAPI, auth, or the DB, which
  is what the Hybrid `tests/integration/*` gates cover once Docker is available.
- The offline `alembic --sql` validation proves the DDL is syntactically valid and reversible; it
  does NOT prove the migration applies cleanly against a real Postgres with real data present —
  only the live round-trip gate proves that, and it is currently Docker-gated/unattempted.
- AC6's Agent-Probe fallback (if triggered) proves the dialog copy is present and renders in the
  DOM; it does NOT prove the full authed user journey (login → dashboard → delete flow) that the
  Playwright e2e leg would prove.
- No gate in this plan proves production behavior under Railway's actual deploy — `alembic upgrade
  head` auto-running on boot is a documented operational fact, not something any gate here
  exercises.
- The `_verify_via_events` fallback interaction noted in Section F (step 19) is not covered by any
  new test in this plan — it is pre-existing behavior and out of this plan's scope, but no gate
  proves `found_site_id` behavior when both a wrong_site HTML match AND recent live traffic for the
  current site_id are true simultaneously.

Gate: CONDITIONAL
Accepted by: session (single-pass autonomous VALIDATE, 04-08-26) — concerns C1-C4 accepted with
documented mitigations already designed into the plan (Hybrid/Agent-Probe/backlog-stub fallbacks
for every Docker-gated and auth-harness-gated row); none represent an unresolved design defect.
Specifically accepted:
- C1 (test tier mislabeling) — corrected in-place in this contract; no plan-text behavior changed.
- C2 (migration chain drift / untracked dependency) — plan's step 6 defense (live re-check) is
  correct; reinforced as mandatory Execute-Agent Instruction E1.
- C3 (Docker unavailable in this sandbox) — pre-anticipated by the plan's own backlog-stub
  fallback language; reinforced as E3, with concrete backlog artifact names in §VI.
- C4 (high-risk class evidence pack) — deferred to plan closeout, not a pre-EXECUTE blocker;
  reinforced as E4.

---

## Autonomous Goal Block

SESSION GOAL: Ship the Site Identity Lifecycle fix (site_id tombstone reuse on delete/re-create,
ingest orphan observability, wrong_site found-id surfacing, delete-dialog warning) per
`site-id-lifecycle_SPEC_01-08-26.md` and this plan's 27-step checklist.
Charter + umbrella plan: N/A — single COMPLEX plan, not a phase program.
Autonomy: standard RIPER-5 EXECUTE approval gate applies (no standing /goal was active for this
VALIDATE pass) — this block records the contract state for whoever runs EXECUTE next, autopilot or
interactive.
Hard stop conditions / safety constraints:
- Never weaken `site_id` unguessability (AC7) — no deterministic url→id function, ever.
- The tombstone lookup's `user_id` filter MUST be a SQL `WHERE` predicate, never a post-fetch
  Python check (highest-risk surface in this plan).
- The unknown-site ingest 403 response (status code, cookie attrs, empty body) MUST stay
  byte-identical (AC9) — old trackers depend on it and cannot be updated.
- No DB lookup, ownership resolution, or reverse index may be added to the `wrong_site`
  found-id path (AC5) — it is a bare string already public in that domain's HTML, nothing more.
- Section B (migration) may not be authored before a fresh, live `alembic heads` re-check returns
  a single head (see Execute-Agent Instruction E1) — 2+ heads is a hard stop, not a force-merge.
- Irreversible/outward-facing action without explicit contract instruction is a hard stop.
Next phase: EXECUTE — `process/features/pixel/active/site-id-lifecycle_01-08-26/site-id-lifecycle_PLAN_01-08-26.md`,
starting at Section A step 1, in order, running each section's gates before the next (per Phase
Completion Rules above).
Validate contract: inline in plan (`## Validate Contract` above).
Execute start: fully-auto commands: `.venv/bin/python3.11 -c "import apps.api.main"` (step 4) →
`.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` (step 6, E1) → per-section
implementation → `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` after each section |
Hybrid gates: `tests/integration/*` (precondition: `docker compose -f infra/docker-compose.yml up
-d postgres redis`) | e2e spec: `apps/web/e2e/dashboard.spec.ts` (AC6) | Agent-Probe fallback:
dialog-copy read if the auth-harness gap blocks the e2e leg | high-risk pack: yes — produce
`vc-risk-evidence-pack` before plan closeout (E4), not before EXECUTE start.

---

## Resume and Execution Handoff

1. **Selected plan file:** `process/features/pixel/active/site-id-lifecycle_01-08-26/site-id-lifecycle_PLAN_01-08-26.md`
2. **Last completed phase/step:** VALIDATE complete (04-08-26) — Gate: CONDITIONAL, accepted this
   session. No code written.
3. **Validate-contract status:** written — see `## Validate Contract` above.
4. **Supporting context loaded:** `site-id-lifecycle_SPEC_01-08-26.md` (same folder),
   `process/context/all-context.md`, `process/context/tests/all-tests.md`, and the blast-radius
   source files listed in `## Touchpoints` (all spot-checked live at VALIDATE).
5. **Next step for a fresh agent:** ENTER EXECUTE MODE on this plan. Start at Section A step 1 and
   work in order; Section B step 6 (`alembic heads` live, per Execute-Agent Instruction E1) is a
   hard gate before any migration file is authored — do not reuse any head value recorded in this
   plan or its Validate Contract. Run each section's gates before starting the next section rather
   than batching all tests to the end. Attempt the Docker-gated gates for real before falling back
   to a backlog stub (E3).

---

**Next:** review the Validate Contract above, then say **ENTER EXECUTE MODE**.
