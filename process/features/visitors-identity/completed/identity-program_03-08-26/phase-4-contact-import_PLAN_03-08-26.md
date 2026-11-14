---
name: plan:identity-program-phase-4-contact-import
description: "Identity honesty program — Phase 4: CSV contact import as phantom Visitor rows, 5,000/site cap, merge-on-click"
date: 03-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
  phase: phase-4
---

# Phase 4 — Contact Import (Named-Traffic Factory Foundation)

**Program:** identity-program
**Umbrella plan:** process/features/visitors-identity/active/identity-program_03-08-26/identity-program-umbrella_PLAN_03-08-26.md
**Phase status:** ⏳ PLANNED
**Report destination:** process/features/visitors-identity/active/identity-program_03-08-26/phase-4-contact-import_REPORT_03-08-26.md

---

## Purpose

Build the genuinely new CSV import surface (none exists today for CREATING an identity from a
contact who has never visited) so a customer can bring a list of contacts they already own into
Beam before those contacts ever visit the site. Each imported contact becomes a phantom `Visitor`
row (`visitor_id = "import:{contact_id}"`, new `is_imported_contact` flag column), mirroring the
`is_agent_derived` precedent so every existing join (segments, campaign_sender, dashboards,
aggregator) works unmodified. Hard cap: 5,000 contacts/site, rejected (not truncated) above the
limit. Specs the merge-on-click design: when a real visit later arrives for an email that matches
a phantom contact, unify onto the phantom's identity instead of creating a second contactable
record — **RESEARCH 04-08-26 confirmed this mechanism already exists in the codebase (see
`## Merge Mechanism Decision` below); Phase 4 does not write new merge code, it makes the phantom
row dedup-discoverable.**

**VALIDATE correction (03-08-26):** a *different*, narrower CSV upload feature already exists —
`apps/api/routers/known_contacts.py` (`KnownContact` model, hash-only, no email retained, no
`Visitor` row ever created) — used purely to flag an already-identified visitor as "Known"
(existing customer) for net-new filtering, surfaced today as "Import (known contacts)" on
`apps/web/src/app/dashboard/connectors/page.tsx`. This is NOT the same feature and does not need
to change, but the two "upload your contacts" surfaces WILL confuse customers if not clearly
distinguished. See Step E and Blast Radius below.

---

## Merge Mechanism Decision

**RESEARCH 04-08-26** traced the codebase and found the "how do we unify a phantom contact with
its later real visit" question is already answered by existing, already-exercised code — no new
merge function is required.

**Chosen: POINTER — `IdentifiedVisitor` email-dedup branch (`canonical_visitor_id`)**

`apps/api/services/identity_resolver.py:832-859`, inside `_save_identified`, already does exactly
this for every existing provider (**VALIDATE 04-08-26 read the live file and confirmed this excerpt
matches the code exactly, line numbers included**):

```python
if data.get("email"):
    existing_by_email = await self.db.execute(
        select(IdentifiedVisitor).where(
            IdentifiedVisitor.site_id == visitor.site_id,
            func.lower(IdentifiedVisitor.email) == data["email"],
            IdentifiedVisitor.visitor_id != visitor.visitor_id,
        )
    )
    canonical = existing_by_email.scalar_one_or_none()
    if canonical:
        visitor.identity_status = "merged"
        visitor.canonical_visitor_id = canonical.visitor_id
        ...
        return canonical
```

If a phantom contact's `IdentifiedVisitor` row already exists (by lowercase email), and a later
real visit reaches `_save_identified` with a matching email (via `_check_prior_signals` Check 1 /
captured `VisitorEmail`, or the tokenized-link click path), this branch fires automatically. The
click-derived `Visitor` row is marked `identity_status = "merged"` with
`canonical_visitor_id = <phantom's visitor_id>` — the phantom's original `"identified"` row stays
canonical. **VALIDATE 04-08-26 additionally confirmed `_save_identified`'s own email normalization
(`email = email.strip().lower()`, applied to the incoming `data["email"]` before this branch runs)
means the `func.lower(IdentifiedVisitor.email)` comparison matches regardless of how the phantom's
own stored email was cased — writing it pre-lowercased (Step B2) is good hygiene/consistency with
every other provider's convention, but is not itself what makes the match work.**

**Rejected: ROW REWRITE (re-key `events`/`visitor_emails`/`segment_members` onto the phantom's
`visitor_id`)**

No precedent exists anywhere in the codebase for rewriting child-table rows onto another
`visitor_id`. At least 4 tables carry UNIQUE constraints that make a literal rewrite
collision-prone in exactly the scenario this phase must handle (a phantom that already has rows in
`identified_visitors` / `visitor_emails` / `segment_members`): `uq_identified_site_visitor
(site_id, visitor_id)`, `segment_members` PK `(segment_id, visitor_id)`, `uq_visitor_email_site_vid_email
(site_id, visitor_id, email)`, `uq_enrichment_site_visitor (site_id, visitor_id)`. **VALIDATE
04-08-26 confirmed all 4 named constraints exist verbatim in the live models
(`apps/api/models/visitor.py`, `apps/api/models/visitor_email.py`, `apps/api/models/enrichment.py`).**
A rewrite targeting the phantom's existing `visitor_id` would collide with the phantom's own rows
at that id. This is precisely why `_save_identified`'s existing dedup branch chose pointer, not
row-rewrite, for every other provider — Phase 4 follows the same precedent rather than inventing a
new pattern.

**Cost tradeoff accepted (CORRECTED by VALIDATE 04-08-26 — see `## Known Gaps` below):** the
pointer approach means ~7 consumer surfaces (`routers/dashboard.py`, `services/kpi.py`,
`services/timeseries.py`, `services/visitor_aggregator.py`, `services/campaign_sender.py`,
`agents/segmenter.py`, `services/csv_exporter.py`) have **zero** existing awareness of
`canonical_visitor_id` / `identity_status == "merged"` (grep-confirmed 04-08-26 by RESEARCH,
re-confirmed independently by VALIDATE 04-08-26) and could double-count or double-send the
now-duplicate `Visitor` row unless explicitly excluded. **VALIDATE 04-08-26 found this is NOT
solved by Step D1, correcting the plan's original claim** — tracing the actual call sites showed
only 2 of these 7 files (`dashboard.py`, `visitor_aggregator.py`) are even among the 9 call sites of
`agent_visitor_filters.py`'s `human_only_visitor_filter()`, and that predicate does not itself
check `canonical_visitor_id`/`"merged"` — it only governs `is_agent_derived` and (after D1)
not-yet-visited-phantom exclusion, an orthogonal axis. This double-count/double-send risk is a
**pre-existing gap in `_save_identified`'s generic merge-dedup mechanism** (it already produces
`"merged"` rows for every provider today, independent of Phase 4) — Phase 4 does not create this
gap but materially increases how often it triggers (every phantom contact is a live merge
candidate). Fixing all 7 consumer surfaces is explicitly OUT of Phase 4's blast radius (the
umbrella states Phase 4 does not touch `campaign_sender.py`, and `kpi.py`/`timeseries.py`/
`segmenter.py`/`csv_exporter.py` are not in Phase 4's blast radius at all) — tracked as a
program-level backlog item, not silently absorbed:
`process/features/visitors-identity/backlog/merged-visitor-consumer-awareness_NOTE_04-08-26.md`.
`routers/visitors.py:185-206` already resolves `"merged"` display fields via `canonical_visitor_id`
(VALIDATE read the code and confirmed this precedent is real), so a working pattern exists for the
follow-up hardening pass.

**Practical consequence for Step C:** Phase 4's only NEW obligation is (1) ensure the phantom's
`IdentifiedVisitor.email` is written lowercase-normalized so `func.lower()` matches it (Step B2/B5
already write via the resolver-owned normalization convention — confirm at EXECUTE; VALIDATE notes
this is hygiene/consistency, not strictly required for the match to work, per the normalization
note above), and (2) extend `agent_visitor_filters.py`'s choke point (Step D1) to also exclude a
phantom's row from double-counting once it has been superseded by a `"merged"` pointer (in addition
to the not-yet-visited exclusion already specified) — **VALIDATE 04-08-26 found and corrected a
self-contradiction in the original predicate design here; see the Metric Exclusion bullet in Blast
Radius and Step D1 below for the corrected version.** No new lookup function, no new merge write
path.
**D6's test must assert `identity_status == "merged"` AND `canonical_visitor_id` resolving to the
phantom's `visitor_id` — NOT literal same-`visitor_id` equality on the click-derived row.**

**Note for Phase 5:** Phase 5's plan (`phase-5-promotion-sweep_PLAN_03-08-26.md:72-77`) named two
candidate outcomes for an imported-contact's later click — (a) `identity_status == "identified"`
directly, or (b) `identity_status == "merged"` + `canonical_visitor_id` → phantom's `"identified"`
row — and deferred to Phase 4's actual implementation. **Confirmed: outcome (b).** Phase 5's C1a
test (and any promotion-sweep logic reading `is_verified_identity()`, which only returns `True` for
the literal string `"identified"`) must assert against the `canonical_visitor_id` chain resolving
to the phantom, not the click-derived visitor's own `identity_status`.

---

## Entry Gate

- Program start — no phase dependency (parallel-safe with Phases 1, 2, 3).

---

## Blast Radius

- `apps/api/models/visitor.py` — new column `is_imported_contact: Mapped[bool] = mapped_column(Boolean, default=False)`. **Requires an additive Alembic migration** — re-verify current head via `alembic -c apps/api/alembic.ini heads` (or `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` — plain `alembic` is not on PATH in this repo's shells) at EXECUTE time. **RESEARCH re-confirmed live 04-08-26: current single head is `b1c9e7f24d83`** (`add_identified_visitor_confirmed_at`, matching the untracked migration file already present in git status) — this supersedes VALIDATE's 03-08-26 reading of `a7d419e6c052`, which itself superseded the umbrella/`all-context.md`'s stale `e6b2d4a1c837`. **VALIDATE 04-08-26 independently re-ran `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` live and reconfirmed `b1c9e7f24d83 (head)` — single head, matches RESEARCH exactly, no further drift since 04-08-26 RESEARCH.** Head drift is real, ongoing, and confirmed across four separate checks now — do not hardcode any `down_revision` from this plan; re-run `alembic heads` live immediately before writing the migration file, every time.
- New: `apps/api/routers/contacts.py` (or `imports.py`) — CSV upload endpoint (`POST /{site_id}/contacts/import`), list/detail endpoints. **Naming:** do not name the router/module `known_contacts` or reuse its URL segment — `known_contacts.py` already owns `/api/v1/sites/{site_id}/known-contacts/*`. Pick a visibly distinct path segment (e.g. `/contacts/import`) and — more importantly — visibly distinct UI/product copy (see Step E). Product-facing name: **"imported contacts"**, never "known contacts" (that term is already owned by the pre-existing hash-only exclusion-list feature). **VALIDATE 04-08-26 confirmed neither `apps/api/routers/contacts.py` nor `apps/api/services/contact_importer.py` exist yet on disk — genuinely new files, no naming collision.**
- New: `apps/api/services/contact_importer.py` — CSV parsing, validation, phantom-Visitor creation, 5,000/site quota check (`COUNT(*) WHERE is_imported_contact AND site_id = :site_id`, checked in the same transaction as the bulk insert to minimize — not eliminate — a concurrent-upload TOCTOU race; acceptable for v1 single-operator-per-site usage, documented as a known limitation). Must also enforce defensive file-size/row caps BEFORE the business quota check, mirroring `known_contacts.py`'s existing `MAX_FILE_BYTES = 10 * 1024 * 1024` / `MAX_EMAILS = 50_000` pattern (this plan's caps can be tighter — the business cap is 5,000 rows — but must exist so a malformed/giant file can't exhaust memory before the row-count check even runs). **RESEARCH 04-08-26 confirmed `IngestBodySizeLimitMiddleware._GUARDED_PATHS` is an exact-string match on `/api/v1/events/ingest` only (`main.py:218`) — it will NOT intercept the new `/contacts/import` route regardless of naming, so the `known_contacts.py`-style application-level caps in `contact_importer.py` are the ONLY defense here; do not assume any middleware-level protection exists for this route. VALIDATE 04-08-26 independently re-read `main.py:218-220` and confirmed `_GUARDED_PATHS = {"/api/v1/events/ingest"}` verbatim.** **VALIDATE 04-08-26 additional finding:** `known_contacts.py` also validates each CSV cell against an email-shape regex (`_looks_like_email`) before persisting anything — Phase 4's plan text did not previously specify equivalent format validation for imported rows. Added as Step B1a below (execute-agent instruction E5): reject/skip rows whose email cell does not look like an email, using the same lightweight regex pattern (or `apps/api/services/email_validator.py` if a fuller check is preferred) — prevents garbage data from silently entering `IdentifiedVisitor.email` and poisoning the dedup match.
- `apps/api/services/identity_resolver.py` — **Phase 4's owned region only, and per the Merge Mechanism Decision above, NO NEW CODE is required here.** The existing email-dedup branch inside `_save_identified` (`identity_resolver.py:832-859`) already handles unification against a phantom contact's `IdentifiedVisitor` row, invoked via `apps/api/services/resolution_runner.py`'s trigger-agnostic `run_resolution_for_site` (APScheduler sweep + manual `/visitors/{site_id}/resolve` endpoint). Confirmed by VALIDATE 03-08-26 and re-confirmed by RESEARCH 04-08-26: this path already runs OUTSIDE the `/ingest` request — do NOT add anything inside `routers/events.py`'s ingest handler. **VALIDATE 04-08-26 independently grepped `apps/api/routers/events.py` for any resolver/resolution-runner import and confirmed zero hits — the ingest handler genuinely never calls into identity resolution.** Phase 4's only work in this file is verification (Step C1), not addition.
- `apps/api/services/identity_classification.py` — **new, additive touchpoint not in the original blast radius**: add a new provider constant (e.g. `"contact_import"`) to `PERSON_LEVEL_PROVIDERS`. Without this, `is_emailable_identity(provider="contact_import")` returns `False` for every single imported contact (the function returns `identity_level(provider) == "person"`, and an unrecognized provider string maps to `None`) — this would silently violate SPEC AC9/AC14 (imported contacts must be emailable) while looking like it works everywhere else. **This tier assignment is a direct, personalizable "identified" outcome — never a graph-candidate guess** (confirmed: `"contact_import"` is intentionally absent from `GRAPH_CANDIDATE_PROVIDERS`, matching the plan's explicit choice to write `identity_status = "identified"` directly at Step B2, because the customer supplied this contact themselves — it is verified by definition, not inferred). **VALIDATE 04-08-26 independently read the live `identity_classification.py` and confirmed `GRAPH_CANDIDATE_PROVIDERS`/`PERSON_LEVEL_PROVIDERS`/`is_verified_identity()` all already exist on disk (Phase 1's code is already landed, even though the umbrella's Program Status Table still shows Phase 1 as "⏳ PLANNED" — stale umbrella bookkeeping, not a Phase 4 blocker) — `"contact_import"` is confirmed absent from both frozensets today, so B2a's addition is a clean, additive, non-conflicting edit.** This file is ALSO touched by Phase 1 (adding `is_verified_identity()`) — the two edits are additive/non-overlapping (a new frozenset member vs. a new function) but both phases must confirm no literal merge conflict at EXECUTE time (lower residual risk than originally assessed, since Phase 1's edits already appear to be landed in the working tree per `git status`).
- `apps/api/services/link_decorator.py` — reuse existing `generate_bid()`/`decorate_links()` mechanism for each imported contact's tokenized link — no new token scheme.
- Metric exclusion — **corrected citation**: the actual `is_agent_derived` exclusion mechanism is `apps/api/services/agent_visitor_filters.py`'s `human_only_visitor_filter()` — a single choke-point predicate (`Visitor.is_agent_derived.is_(False)`) reused across 9 call sites (`visitors_helpers.py`, `visitors.py`, `dashboard.py`, `tasks/resolution_tasks.py`, `tasks/segmentation_tasks.py`, `models/visitor.py`, `services/visitor_aggregator.py`, `services/resolution_runner.py`, `services/daily_digest.py`) — NOT a per-query `FILTER (WHERE NOT is_agent_derived)` SQL aggregate clause (that shape belongs to the unrelated `is_abuse_flagged` exclusion). **VALIDATE 04-08-26 independently confirmed the exact 9 file list by grep.** Phase 4 must extend or parallel this SAME choke point (edit `agent_visitor_filters.py`, not all 9 call sites individually) rather than touching `visitor_aggregator.py` alone. **Critically, the exclusion condition is NOT permanent like `is_agent_derived`**: a phantom row must be excluded only while it has had no real visit yet; once merge-on-click attaches a real visit (per the Merge Mechanism Decision, this shows up as the CLICK-derived row being `"merged"` with a `canonical_visitor_id` pointing at the phantom — the phantom row itself is what should now count), the predicate must recognize that state and stop excluding. **VALIDATE 04-08-26 CORRECTION (was a self-contradiction in the plan text):** the previously-illustrated predicate `~(Visitor.is_imported_contact & (Visitor.total_pageviews == 0))` is **INSUFFICIENT and directly contradicts the very next sentence's own requirement** — the phantom's own `total_pageviews` column never changes after a merge (pageviews accrue on the separate click-derived `Visitor` row that points AT the phantom via `canonical_visitor_id`, never on the phantom itself), so this literal predicate would exclude every merged phantom PERMANENTLY — the exact opposite of the stated intent. The predicate must instead resolve via a correlated `EXISTS` subquery checking whether any OTHER `Visitor` row has `canonical_visitor_id == this.visitor_id AND identity_status == "merged"` — i.e. only exclude when `is_imported_contact AND total_pageviews == 0 AND NOT EXISTS(merged child)`. This is now a required execute-agent instruction (see validate-contract E5/E6) rather than an inline blanket boolean expression.
- PII handling — **corrected**: `IdentifiedVisitor.email` is stored as **plaintext** today (`String(320)`) for every existing provider (rb2b/leadpipe/capturify/form_capture/manual) — the `email_ciphertext` column on that model exists but per its own inline comment is "added nullable, not yet read/written" anywhere in the codebase. Phase 4 must follow the SAME plaintext-write pattern as every other provider — introducing a ciphertext-only write path for just this one phase would create an inconsistent, half-migrated column with no reader anywhere. The actual enforced guardrail to keep is: never log the raw email value (structlog events log domain/hash only, matching existing patterns) — not "encrypt at rest," which is a separate, not-yet-scoped program-wide migration.
- Frontend: new import UI (CSV upload form + import list/status view). **RESEARCH 04-08-26 confirmed no `apps/web/src/app/dashboard/contacts/` directory exists today** (VALIDATE 04-08-26 independently re-confirmed via `ls` — still absent) — recommend a new top-level `dashboard/contacts/` route (NOT nested under `connectors/`, which hosts the structurally different "Import (known contacts)" block) to keep the two upload surfaces visibly separate at the navigation level, not just in copy. **Must be visibly distinct in product copy from the existing "Import (known contacts)" block on `apps/web/src/app/dashboard/connectors/page.tsx`** (see Step E) — that block uploads a hash-only exclusion list and creates no visitors/links; this feature creates real, contactable leads with tokenized links. Use explicit UI labels such as "Imported Contacts" / "Import Contacts as Leads" (new) vs. the existing "Known Contacts" filter list, plus a one-line explainer on each so users don't upload the wrong list to the wrong place.
- New test files: `tests/integration/test_contact_import.py` (create → list → detail, boundary at 5,000/5,001), `tests/unit/test_contact_importer.py`, merge-on-click test (asserting the pointer outcome, not literal id-equality).

**Does NOT touch:** Phase 1's candidate-tier branch logic, Phase 2's personalization guard, Phase 3's compose-step decoration parity (only reuses `link_decorator.py`, doesn't modify `campaign_sender.py`), and does NOT touch `apps/api/routers/known_contacts.py` / `apps/api/models/known_contact.py` (separate, pre-existing feature, left as-is).

---

## Implementation Checklist

### Step A — Data model + migration

- [x] A1. Re-verify current alembic head: `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` (confirmed live 04-08-26 by RESEARCH and independently re-confirmed live 04-08-26 by VALIDATE: `b1c9e7f24d83`, single head — supersedes the 03-08-26 VALIDATE reading of `a7d419e6c052`; re-run again at actual EXECUTE time since drift is frequent and ongoing, confirmed across 4 separate checks so far). Add new migration `add_is_imported_contact` chaining off the confirmed current head.
- [x] A2. Add `Visitor.is_imported_contact: bool` column (default False), additive only.
- [x] A3. Offline `--sql` validate the migration in both directions using an EXPLICIT `<from-rev>:<to-rev>` range (the bare `upgrade head --sql` / `downgrade -1 --sql` shorthand fails mid-chain in this repo — see `process/context/tests/all-tests.md`); do NOT live-apply (matches program-wide convention — live apply is a separate explicit operator action, and per repo convention a `git push` to `main` auto-applies migrations via Railway boot, so do not push this migration to `main` until the operator explicitly approves a live apply).

### Step B — Import endpoint + service

- [x] B1. `POST /{site_id}/contacts/import` accepting a CSV (min columns: name, email). Enforce defensive caps FIRST (max file bytes / max distinct rows, mirroring `known_contacts.py`'s `MAX_FILE_BYTES`/`MAX_EMAILS` pattern — confirmed no middleware-level body-size guard applies to this route, see Blast Radius) to bound memory before any row-count logic runs. Validate row count BEFORE any writes: if current site count + new rows > 5,000, reject the entire upload with a clear error naming the limit (no partial import).
- [x] B1a. **(Added by VALIDATE 04-08-26)** Validate each row's email cell looks like an email before it is accepted (reuse a lightweight regex like `known_contacts.py`'s `_looks_like_email` pattern, or `apps/api/services/email_validator.py` for a fuller check) — skip/report malformed rows rather than silently writing garbage into `IdentifiedVisitor.email`, which would both poison the merge-dedup match (Step C) and count against the 5,000 quota for a row that can never be emailed.
- [x] B2. For each valid row: mint a fresh `uuid.uuid4()` as `contact_id` (do NOT derive it from the not-yet-created `Visitor.id` — the id must exist before the row is created since it's embedded in `visitor_id`). Create a `Visitor` row with `visitor_id = f"import:{contact_id}"`, `is_imported_contact = True`, and an `IdentifiedVisitor` row seeded with the contact's name/**lowercase-normalized email** marked `identity_status = "identified"` (deterministic — the customer supplied this contact themselves, so it's verified by definition, not a graph guess) and `resolution_provider = "contact_import"`. **Lowercase normalization is required hygiene, matching every other provider's convention — VALIDATE 04-08-26 notes the dedup match itself is robust to stored case either way, since `_save_identified` applies `func.lower()` on this column at query time (see Merge Mechanism Decision), but writing it normalized keeps the column consistent with the rest of the codebase.**
- [x] B2a. Add `"contact_import"` to `PERSON_LEVEL_PROVIDERS` in `apps/api/services/identity_classification.py` (additive frozenset entry) — required for `is_emailable_identity()` to return `True` for imported contacts; without this step every imported contact is silently unemailable. Confirmed this is a direct/personalizable tier assignment, not a graph-candidate guess (`"contact_import"` stays out of `GRAPH_CANDIDATE_PROVIDERS`).
- [x] B3. Generate a tokenized link per contact via existing `generate_bid(email)` / `decorate_links()` — no new mechanism.
- [x] B4. Scope all reads/writes via `Site.user_id == user.id` — reuse the existing `verify_site_access` dependency pattern already used by `known_contacts.py` and other site-scoped routers rather than reimplementing the check. Cross-tenant isolation test required (SPEC AC18).
- [x] B5. PII handling: write `IdentifiedVisitor.email` as plaintext, matching every other existing resolution provider's write pattern (rb2b/leadpipe/capturify/form_capture/manual) — do NOT introduce a one-off ciphertext write path for this phase (the `email_ciphertext` column exists but is unused everywhere else in the codebase; making imported contacts the sole exception is scope creep and creates a dead-end column pattern). Never log the raw email value (log domain/hash only).

### Step C — Merge-on-click: confirm existing dedup branch handles the phantom case

**Per the Merge Mechanism Decision above, this step is verification and one extension, not new
merge code.**

- [x] C1. Confirm `_save_identified`'s existing email-dedup branch (`identity_resolver.py:832-859`) fires correctly for a phantom contact: when a real visit's resolved email matches a phantom's lowercase-normalized `IdentifiedVisitor.email`, the click-derived `Visitor` row is set `identity_status = "merged"` with `canonical_visitor_id = <phantom's visitor_id>` — write a targeted test proving this against a seeded phantom row (do not assume it "just works" without proof; VALIDATE 04-08-26 confirmed the branch exists exactly as cited, but a targeted test is still required to prove it fires for THIS specific phantom-row shape). No code addition needed in `identity_resolver.py` itself unless this test reveals a gap.
- [x] C2. Extend `agent_visitor_filters.py`'s choke point (already being touched in Step D1) so a phantom whose `IdentifiedVisitor` counterpart has since been superseded via `"merged"`/`canonical_visitor_id` is recognized as "now-visited" and stops being excluded from rollups. **(VALIDATE 04-08-26 correction, matching the Blast Radius fix above):** the predicate must resolve the pointer via a correlated `EXISTS` subquery — `is_imported_contact AND total_pageviews == 0 AND NOT EXISTS(SELECT 1 FROM visitors v2 WHERE v2.canonical_visitor_id = visitors.visitor_id AND v2.identity_status = 'merged')` — not a check on the phantom's own `total_pageviews` alone (that column never changes on the phantom after a merge).
- [x] C3. Document explicitly in the phase report: what "match" means (lowercase email exact match is the ONLY key in v1; fingerprint-based matching is out of scope — no fingerprint-keyed dedup precedent exists anywhere in `_save_identified`, confirmed by RESEARCH 04-08-26).
- [ ] C4. ~~Investigate merge mechanism (rewrite vs. pointer)~~ — **RESOLVED by RESEARCH 04-08-26, see `## Merge Mechanism Decision`. Chosen: pointer via existing `canonical_visitor_id` dedup branch. No further investigation needed; proceed directly to C1/C2.**

### Step D — Metric exclusion + tests

- [x] D1. Exclude phantom (`is_imported_contact = True AND total_pageviews == 0 AND NOT EXISTS(merged child)`, i.e. not-yet-visited AND not-yet-merged-into — **VALIDATE 04-08-26 corrected predicate, see Blast Radius/C2**) rows from traffic/engagement rollups by extending the single choke-point predicate in `apps/api/services/agent_visitor_filters.py` (`human_only_visitor_filter()`, or a new sibling helper called at the same 9 sites) — NOT a per-query `FILTER` clause, and NOT a blanket/permanent exclusion (once merged via Step C, the phantom row must count normally).
- [x] D2. Integration test: import → list → detail (SPEC AC9).
- [x] D3. Boundary test: exactly 5,000 succeeds, 5,001 rejected with clear error (SPEC AC9).
- [x] D4. Unit test: link generation for imported contacts round-trips via `link_decorator.py`'s existing test pattern (SPEC AC10).
- [x] D5. Integration test: cross-tenant import isolation — an imported contact from site A is never visible/sendable from site B (SPEC AC18).
- [x] D6. Merge-on-click test: seed a phantom contact with a lowercase-normalized email; run a real resolution pass with a matching email; assert the click-derived `Visitor.identity_status == "merged"` AND `Visitor.canonical_visitor_id == <phantom's visitor_id>` — **NOT literal same-`visitor_id` equality** (per the Merge Mechanism Decision, the phantom keeps its own `visitor_id`; the click-derived row points at it).
- [x] D7. Unit test: `is_emailable_identity("contact_import")` returns `True` (regression-proves B2a was not skipped).
- [x] D8. **(Added by VALIDATE 04-08-26)** Unit test: `human_only_visitor_filter()`'s extended predicate correctly (a) excludes an unmerged phantom with `total_pageviews == 0`, and (b) INCLUDES a phantom once a merged child row exists, even though the phantom's own `total_pageviews` is still 0 — this is the regression test that proves the C2/D1 predicate fix actually works, not just the illustrative expression in the plan text.

### Step E — Frontend import UI

- [x] E1. CSV upload form at a new `apps/web/src/app/dashboard/contacts/` route (confirmed no such directory exists today; do not nest under `connectors/`) with clear error surfacing for the 5,000 cap and for the new defensive file/row caps (Step B1).
- [x] E2. Import list/status view showing imported contacts and their tokenized-link status.
- [x] E3. Use product copy that is visibly distinct from the existing "Import (known contacts)" block on `apps/web/src/app/dashboard/connectors/page.tsx` — labels: **"Imported Contacts"** / "Import Contacts as Leads" (new) vs. "Known Contacts" filter list (existing), each with a one-line explainer of what it does and does not do. The two features look similar (both are "upload a CSV of contacts") but do fundamentally different things (this feature creates contactable leads with tokenized links; the existing one is a hash-only exclusion filter that creates no visitors and stores no plaintext email).

---

## Exit Gate

```bash
.venv/bin/python3.11 -m pytest tests/integration/test_contact_import.py -q
# Expected: 0 failures, including 5000/5001 boundary

.venv/bin/python3.11 -m pytest tests/unit/test_contact_importer.py -q
# Expected: 0 failures

.venv/bin/python3.11 -m pytest tests/unit -k "link_decorator or is_emailable or human_only_visitor_filter" -q
# Expected: 0 failures (regression + new imported-contact coverage, including D7's
# is_emailable_identity("contact_import") assertion and D8's predicate regression test)

.venv/bin/python3.11 -m pytest tests/unit -q
# REQUIRED — full UNFILTERED unit lane, not -m unit and not -k. Added by VALIDATE 04-08-26 per
# the recorded Phase 1 EVL gate lesson ("phase gates must run the UNFILTERED unit lane, not
# -m unit, from Phase 4 on" — process/features/visitors-identity/active/identity-program_03-08-26/
# phase-1-candidate-tier-evl-iteration-001_REPORT_03-08-26.md). VALIDATE 04-08-26 ran this exact
# command as a pre-EXECUTE baseline: 1589 passed, 2 skipped, 0 failed (10.84s) — this is the
# regression floor EXECUTE must not break.
# Expected: 0 failures (baseline: 1589 passed, 2 skipped as of 04-08-26 pre-EXECUTE)

.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade <prior-head>:<this-migration> --sql
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini downgrade <this-migration>:<prior-head> --sql
# Expected: both directions validate offline without error (plain `alembic` binary
# is NOT on PATH in this repo's shell — must invoke via .venv/bin/python3.11 -m alembic)
```

- SPEC ACs 9, 10, 18 all have a passing proving test.
- Merge-on-click behavior explicitly specced and tested against the confirmed pointer mechanism (vc-predict mitigation item) — no open C4 decision remains.
- D1/C2's corrected EXISTS-subquery predicate has its own regression test (D8) proving both the exclude and re-include paths.
- Phase report written to report destination above.

---

## Blockers That Would Justify BLOCKED Status

- Alembic head has moved unexpectedly since research (known repo-wide risk, confirmed drift across four separate checks: 03-08-26 VALIDATE found `a7d419e6c052`, 04-08-26 RESEARCH found `b1c9e7f24d83`, 04-08-26 VALIDATE independently re-confirmed `b1c9e7f24d83` — the umbrella/`all-context.md`'s recorded `e6b2d4a1c837` was already stale before any of these). Re-verify before writing `down_revision`; if a conflicting migration landed concurrently, re-chain rather than force.
- Fingerprint-based merge matching (beyond exact email) is confirmed out of v1 scope (no precedent found in `_save_identified`) — not a blocker, documented as a backlog follow-up.
- ~~If Step C4's investigation finds row rewrite infeasible...~~ — **no longer a blocker; C4 is resolved (pointer mechanism confirmed via existing code, see Merge Mechanism Decision). If Step C1's proving test reveals the existing dedup branch does NOT fire as expected for a phantom row, treat that as a genuine implementation bug to fix within this phase's scope, not a design blocker requiring re-investigation.**

---

## Known Gaps (Resolved via Backlog)

- **Merged-visitor consumer awareness** (5 of 7 named consumer surfaces have zero
  `canonical_visitor_id`/`"merged"` awareness; pre-existing gap, elevated by import volume) —
  known-gap: documented as NEW PLAN REQUIRED — see
  `process/features/visitors-identity/backlog/merged-visitor-consumer-awareness_NOTE_04-08-26.md`.
  Out of Phase 4's blast radius; does not block this phase's EXECUTE.

---

## Phase Loop Progress

- [x] 1. RESEARCH — research-agent: prior phase reports read; confirmed no `dashboard/contacts/` directory exists (E1); confirmed fingerprint-matching out of scope (C3); re-verified alembic head (`b1c9e7f24d83`); **confirmed the Step C4 merge mechanism is the existing pointer/`canonical_visitor_id` dedup branch — no new merge code required**
- [x] 2. INNOVATE — innovate-agent: approach decided (largely pre-decided by program INNOVATE Fork 1; Merge Mechanism Decision above supersedes the deferred C4 question — VALIDATE 04-08-26 independently re-verified the decision against live source and found it sound, no further INNOVATE work needed)
- [x] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated with RESEARCH findings (this pass)
- [x] 4. PVL — vc-validate-agent: full V1-V7 re-run complete 04-08-26 (inner-pvl: phase-4). Gate: CONDITIONAL — 4 concerns found (missing unfiltered unit-lane gate, missing CSV email-format validation, D1/C2 predicate self-contradiction, mischaracterized "tracked there" consumer-awareness claim), all fixed directly in plan text (B1a, D8, corrected predicate, corrected Cost-tradeoff paragraph) except the pre-existing cross-cutting consumer-awareness gap, deferred to backlog (see Known Gaps above). No unresolved FAILs. Validate-contract rewritten below.
- [x] 5. EXECUTE — all checklist items done; per-section test gates run and green (or gaps documented)
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute — DONE (see below); this phase is now clear for EXECUTE.**

---

## Touchpoints

- `apps/api/models/visitor.py`
- `apps/api/migrations/versions/` (new migration, chains off `b1c9e7f24d83` as of 04-08-26 — re-verify at EXECUTE)
- `apps/api/routers/contacts.py` (new)
- `apps/api/services/contact_importer.py` (new)
- `apps/api/services/identity_resolver.py` (verification only — confirm existing dedup branch handles the phantom case, see Merge Mechanism Decision; no new function)
- `apps/api/services/identity_classification.py` (additive: new `PERSON_LEVEL_PROVIDERS` entry — shared file, Phase 1 also touches it for `is_verified_identity()`; non-overlapping edits; VALIDATE 04-08-26 confirmed Phase 1's edits already appear landed in the working tree)
- `apps/api/services/agent_visitor_filters.py` (metric exclusion choke point — corrected from `visitor_aggregator.py` alone; extended via a correlated EXISTS subquery to resolve the `canonical_visitor_id` pointer, see Step C2/D1 — corrected by VALIDATE 04-08-26)
- `apps/api/services/link_decorator.py` (reused, unmodified)
- Frontend: new `apps/web/src/app/dashboard/contacts/` route (confirmed empty today)

---

## Public Contracts

- No change to `is_emailable_identity()`'s signature (3 parameters, unchanged) — Phase 4 only adds a new value to the `PERSON_LEVEL_PROVIDERS` data constant it reads from, which is not a contract change.
- `_bid` token mechanism reused as-is, no new token scheme.
- No change to `identity_status` value set beyond what Phase 1 already introduced (`"merged"` already exists as a value produced by the existing dedup branch — Phase 4 causes it to be produced for a new class of row, it does not introduce a new value).
- No change to `_save_identified`'s merge-dedup logic — Phase 4 relies on it as-is (see Merge Mechanism Decision).
- `apps/api/routers/known_contacts.py` / `KnownContact` model are untouched — a separate, pre-existing feature.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Import creates phantom Visitor rows up to 5,000/site cap | Fully-Automated | AC9 |
| Upload exceeding 5,000 rejected with clear error, no partial import | Fully-Automated | AC9 |
| Each imported contact gets a unique working tokenized link | Fully-Automated | AC10 |
| Cross-tenant import isolation | Fully-Automated | AC18 |
| Merge-on-click: existing dedup branch fires for a phantom, produces `"merged"` + `canonical_visitor_id` pointer | Fully-Automated | (design surface, vc-predict mitigation) |
| `is_emailable_identity("contact_import")` returns True | Fully-Automated | AC9/AC14 (added by VALIDATE — closes the PERSON_LEVEL_PROVIDERS gap) |
| D1/C2 EXISTS-subquery predicate excludes unmerged phantom, includes merged phantom | Fully-Automated | (design surface — closes the VALIDATE 04-08-26-found predicate contradiction) |
| Full unfiltered unit lane, no regressions | Fully-Automated | Program-wide gate lesson (Phase 1 EVL) |

Failing stub (example):
```
test("should reject an import upload exceeding the 5000-contact site cap", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: import quota boundary")
})
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/visitors-identity/active/identity-program_03-08-26/phase-4-contact-import_PLAN_03-08-26.md`
- Last completed step: PVL (inner-pvl: phase-4, 04-08-26) — Gate: CONDITIONAL, all fixable concerns applied directly to plan text, one pre-existing cross-cutting gap deferred to backlog (does not block this phase)
- Validate-contract status: written, CONDITIONAL — see `## Validate Contract` below
- Supporting context files loaded: umbrella plan, SPEC, INNOVATE Decision Summary (Fork 1), RESEARCH findings (04-08-26), this VALIDATE pass (04-08-26)
- Next step: Spawn vc-execute-agent for Step 5 (EXECUTE) — plan and validate-contract are both current as of 04-08-26; no further PVL cycle required unless EXECUTE surfaces new gaps.

---

## Validate Contract

Status: CONDITIONAL
Date: 04-08-26
date: 2026-08-04
generated-by: inner-pvl: phase-4
supersedes: 2026-08-03 (outer-pvl) — inner PVL has current evidence (plan text materially changed by 04-08-26 RESEARCH + PLAN-SUPPLEMENT; full V1-V7 re-run performed against the updated plan)

Parallel strategy: sequential (single-plan inner-PVL; deep-mode manual investigation reading all cited source files directly, no parallel subagent fan-out required for a one-plan re-validate pass)
Rationale: Score 5/7 (schema/migration surface present, 5+ blast-radius files, high-risk class present, phase-program phase, new-surface design) would normally recommend parallel subagents, but this invocation is scoped to exactly one phase plan already supplemented with fresh RESEARCH findings — a single deep-mode pass reading `identity_resolver.py`, `identity_classification.py`, `agent_visitor_filters.py`, `known_contacts.py`, `main.py`, `visitor.py`, `visitor_email.py`, `enrichment.py`, and running the live alembic-heads check + full unfiltered unit lane, gave higher-confidence, cheaper verification than a multi-agent fan-out for this single-plan scope.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC9 | CSV import creates phantom Visitor rows up to 5,000/site cap | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_contact_import.py -q` | B (fixed in this plan's checklist D2/D3) |
| AC9 | Upload exceeding 5,000 rejected, no partial import | Fully-Automated | same file, boundary case at 5001 | B |
| AC10 | Each imported contact gets a unique working tokenized link | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_contact_importer.py -q` + `link_decorator` regression | B |
| AC18 | Cross-tenant import isolation | Fully-Automated | `tests/integration/test_contact_import.py` (D5 case) | B |
| AC9/AC14 | `is_emailable_identity("contact_import")` is True | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -k "is_emailable" -q` | B (added by 03-08-26 VALIDATE — D7/B2a) |
| (design surface) | Merge-on-click unifies phantom + real visit onto one visitor_id via pointer | Fully-Automated | `tests/unit`/`tests/integration` merge-on-click test (D6) | A (RESOLVED by 04-08-26 RESEARCH + independently re-verified against live source by 04-08-26 VALIDATE — see Merge Mechanism Decision) |
| (design surface) | D1/C2 EXISTS-subquery predicate excludes unmerged phantom, includes merged phantom | Fully-Automated | new D8 unit test (added by 04-08-26 VALIDATE) | B (fixed in this plan — corrects a genuine predicate self-contradiction found this pass) |
| (data quality) | CSV rows with malformed email are rejected/skipped, not silently persisted | Fully-Automated | new B1a-derived unit test in `test_contact_importer.py` | B (added by 04-08-26 VALIDATE) |
| (program-wide regression) | Full unfiltered unit lane has no regressions | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -q` | A (proven now — VALIDATE 04-08-26 ran this exact command as pre-EXECUTE baseline: 1589 passed, 2 skipped, 0 failed) |
| — | Migration offline round-trip | Hybrid | `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade <from>:<to> --sql` (both directions) | A (precondition: current head re-confirmed live twice now — `b1c9e7f24d83`, stable since 04-08-26 RESEARCH) |
| — | Live migration apply / production DDL | Known-Gap | — | D (explicit operator action per umbrella hard-stop; never part of this phase's automated gates; docker unavailable in this environment — confirmed via `which docker` returning not-found) |
| — | Integration lane (test_contact_import.py, boundary/cross-tenant) | Known-Gap | `.venv/bin/python3.11 -m pytest tests/integration/test_contact_import.py -q` | D (env-blocked — no Docker/Postgres/Redis in this sandbox, confirmed; matches Phase 1/2's identical known-gap precedent. Fully-Automated once Docker is available — not a design gap.) |

gap-resolution legend: A = proven now, B = fixed in this plan (checklist item added/corrected), C = deferred to a named later step, D = backlog/operator/environment residual.

Legacy line form:
- CSV import + quota + cross-tenant: Fully-automated: `.venv/bin/python3.11 -m pytest tests/integration/test_contact_import.py tests/unit/test_contact_importer.py -q`
- is_emailable_identity provider gap: Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit -k "is_emailable" -q`
- Merge-on-click: Fully-automated (mechanism resolved 04-08-26 — pointer/canonical_visitor_id, independently re-verified against live source) — `tests/unit`/`tests/integration` merge-on-click test named in D6
- D1/C2 predicate: Fully-automated (corrected 04-08-26 — EXISTS-subquery, not total_pageviews-only) — new D8 test
- Full unfiltered unit lane: Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit -q` — baseline 1589 passed / 2 skipped, 04-08-26
- Migration round-trip: hybrid: `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade <from>:<to> --sql` + downgrade, precondition: re-verified current head twice
- Production DDL apply: known-gap: documented — explicit separate operator action, program-wide hard stop
- Integration lane: known-gap: documented — no Docker in this sandbox, confirmed live this pass

Failing stub (Fully-Automated rows):
```
test("should reject an import upload exceeding the 5000-contact site cap", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: import quota boundary")
})
test("should mark an imported contact identity as emailable via is_emailable_identity", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: contact_import added to PERSON_LEVEL_PROVIDERS")
})
test("should merge a phantom contact and its later real visit via canonical_visitor_id pointer", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: merge-on-click unification (pointer mechanism)")
})
test("should stop excluding a phantom from rollups once a merged child row exists, even though its own total_pageviews stays 0", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: D1/C2 EXISTS-subquery predicate (D8)")
})
test("should skip a CSV row whose email cell does not look like an email", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: B1a email-format validation")
})
```

Dimension findings:
- Infra fit: PASS — plain `alembic` binary is not on PATH in this repo's shell (must invoke via `.venv/bin/python3.11 -m alembic`, correct throughout the plan); true current alembic head independently re-verified live by VALIDATE 04-08-26 (`.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` → `b1c9e7f24d83 (head)`, single head) and confirmed to match the plan's stated head exactly — no drift found this pass, though the historical drift pattern (4 checks, 3 different values) means EXECUTE must still re-verify live.
- Test coverage: CONCERN → FIXED — the plan's original Exit Gate did not include the full unfiltered unit lane, violating the program's own recorded gate lesson from Phase 1 EVL ("phase gates must run the UNFILTERED unit lane, not `-m unit`, from Phase 4 on"). Fixed: added as a required gate in Exit Gate + validate-contract Test Gates table; VALIDATE ran it as a pre-EXECUTE baseline (1589 passed, 2 skipped, 0 failed).
- Breaking changes: PASS — no public-contract changes (`is_emailable_identity` signature untouched and independently re-confirmed at 3 params in the live source; `_bid` mechanism reused as-is; `_save_identified`'s merge logic reused unmodified and independently re-verified against live source).
- Security surface: CONCERN → FIXED — CSV upload endpoint had no explicit email-format validation instruction (garbage-data risk poisoning the dedup match and consuming quota for unemailable rows); fixed via new Step B1a + D-series test. Site-scoping (`verify_site_access`) correctly reused from `known_contacts.py`'s existing pattern — independently confirmed present in the live file. Phantom-lookup at merge-on-click remains site-scoped (`_save_identified`'s existing dedup branch filters on `IdentifiedVisitor.site_id == visitor.site_id`, independently re-confirmed) — no cross-tenant identity-hijack path via email collision across sites.
- Section A (Data model + migration) feasibility: PASS — mechanically feasible (additive boolean column, no FK changes); alembic head independently re-verified live and stable at `b1c9e7f24d83` since 04-08-26 RESEARCH, no further drift found this pass.
- Section B (Import endpoint + service) feasibility: CONCERN → FIXED — missing email-format validation (B1a added); everything else previously found by the 03-08-26 VALIDATE pass (PERSON_LEVEL_PROVIDERS gap, PII storage citation, CSV defensive caps, contact_id minting order) remains correctly fixed in plan text and was independently spot-checked this pass (e.g. `known_contacts.py`'s `MAX_FILE_BYTES`/`MAX_EMAILS`/`_looks_like_email` pattern confirmed to exist exactly as cited).
- Section C (Merge-on-click) feasibility: PASS — RESEARCH 04-08-26's trace of `identity_resolver.py:832-859` was independently re-read by VALIDATE 04-08-26 and confirmed to match the plan's cited excerpt verbatim, including line numbers. `is_graph_candidate_provider("contact_import")` correctly evaluates `False` (not in `GRAPH_CANDIDATE_PROVIDERS`, independently confirmed), so the direct `identity_status = "identified"` write at B2 does not conflict with Phase 1's candidate-tier guard.
- Section D (Metric exclusion + tests) feasibility: FAIL → FIXED — VALIDATE 04-08-26 found a genuine self-contradiction: the plan's own illustrative predicate (`~(is_imported_contact & total_pageviews==0)`) is exactly the thing the plan's own C2 text says is insufficient (the phantom's `total_pageviews` never changes post-merge). This would have shipped a phantom-exclusion bug where merged phantoms are excluded from rollups FOREVER, contradicting the stated design intent. Fixed: corrected to a correlated EXISTS-subquery predicate in Blast Radius, C2, and D1, with a new regression test (D8) proving both directions.
- Section E (Frontend import UI) feasibility: PASS — route location independently re-confirmed empty (`ls apps/web/src/app/dashboard/contacts/` → not found); naming disambiguation (E1/E3) already well-specified from the 03-08-26 VALIDATE pass.

Plan updates applied (this inner-PVL pass, in-plan text edits — not deferred):
- Added Step B1a (CSV email-format validation) and Step D8 (D1/C2 predicate regression test) to the Implementation Checklist.
- Corrected the D1/C2 metric-exclusion predicate from a self-contradictory `total_pageviews==0`-only check to a correlated EXISTS-subquery that correctly resolves the merged-child pointer, in Blast Radius, C2, and D1.
- Corrected the "Cost tradeoff accepted" paragraph's claim that Step D1 solves the 7-consumer `canonical_visitor_id` awareness gap — traced the actual call sites and found only 2 of 7 files overlap with D1's choke point at all, and even those don't check `canonical_visitor_id`. Added a `## Known Gaps (Resolved via Backlog)` section and wrote a new backlog NOTE (`merged-visitor-consumer-awareness_NOTE_04-08-26.md`) rather than silently absorbing or hand-waving the gap.
- Added the full unfiltered unit lane (`pytest tests/unit -q`) to the Exit Gate and Verification Evidence, per the program's recorded Phase 1 EVL gate lesson — the plan had not yet incorporated this lesson.
- Added inline "VALIDATE 04-08-26 independently confirmed/re-verified" annotations throughout Blast Radius and Merge Mechanism Decision, documenting exactly which claims were re-checked against live source this pass (vs. carried over from 03-08-26 VALIDATE / 04-08-26 RESEARCH without independent re-verification).
- Updated Phase Loop Progress: ticked INNOVATE (2) and PVL (4); updated Resume and Execution Handoff to point at EXECUTE as the next step.

Execute-agent instructions (cannot be resolved by plan text alone — must be confirmed at EXECUTE time):
- E1: Before writing the migration file, re-run `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` live and use whatever head is actually current — do not trust this contract's `b1c9e7f24d83` value beyond "confirmed as of 04-08-26." Confirmed drift pattern across 4 checks: re-verify every single time, no exceptions.
- E2 (SUPERSEDED — see Merge Mechanism Decision, resolved 04-08-26): the original instruction to "determine and document the Step C4 merge-mechanism decision during RESEARCH" is complete. No further investigation needed at EXECUTE time; implement Steps C1/C2 as written.
- E3: Confirm `contact_id` (fresh `uuid.uuid4()`) is minted before Visitor-row creation and used consistently for `visitor_id` construction and any per-row audit/list keying — do not derive it from the not-yet-existing `Visitor.id`.
- E4: When touching `identity_classification.py`, coordinate with Phase 1's edits to the same file — VALIDATE 04-08-26 found Phase 1's `is_verified_identity()`/`GRAPH_CANDIDATE_PROVIDERS` already appear landed in the working tree (lower residual risk than previously assessed), but still confirm no literal merge conflict at commit time.
- E5: Implement Step B1a's email-format validation using a lightweight regex (mirror `known_contacts.py`'s `_looks_like_email`) or `apps/api/services/email_validator.py`; reject/skip malformed rows with a clear per-row error rather than a silent write.
- E6: Implement the D1/C2 predicate as a correlated EXISTS subquery against the `Visitor` table (self-referential on `canonical_visitor_id`), not a boolean expression over the phantom's own columns alone. Write D8's regression test FIRST (red), confirm it fails against the naive `total_pageviews==0`-only predicate, then implement the EXISTS-subquery version and confirm it goes green — this is exactly the class of bug a red-first test catches that manual review can miss.

Open gaps:
- ~~Step C4 merge-mechanism decision~~ — RESOLVED 04-08-26 (see Merge Mechanism Decision above), independently re-verified against live source by this VALIDATE pass.
- Fingerprint-based merge matching scope (beyond exact email) — RESOLVED as out-of-scope for v1 (no precedent found anywhere in `_save_identified`); documented as a backlog follow-up, not ambiguous anymore.
- Live migration apply — known-gap: documented as an explicit separate operator action after PVL/EVL close, matching program-wide convention (never part of this phase's automated gates).
- Integration lane (test_contact_import.py) — known-gap: documented as environment-blocked (no Docker in this sandbox, confirmed via `which docker` this pass); Fully-Automated once Docker is available, not a design gap.
- Merged-visitor consumer awareness (5 of 7 consumer files) — known-gap: documented as NEW PLAN REQUIRED — see `process/features/visitors-identity/backlog/merged-visitor-consumer-awareness_NOTE_04-08-26.md`. Pre-existing gap, out of Phase 4's blast radius, does not block this phase.

What this coverage does NOT prove:
- The Fully-Automated import/quota/link/cross-tenant tests prove the code paths behave correctly in the test DB; they do NOT prove production-scale CSV files (near 5,000 rows) parse within acceptable request latency — no load/perf test is in scope for this phase.
- The `is_emailable_identity("contact_import")` unit test proves the classification function's return value; it does NOT prove the full send pipeline (`campaign_sender.py`) actually delivers a real email to an imported contact — that is exercised by the AC14 guardrail test named in the umbrella/Phase 2 scope, not duplicated here. It also does NOT prove `campaign_sender.py` (or `kpi.py`/`timeseries.py`/`segmenter.py`/`csv_exporter.py`) correctly avoids double-counting or double-sending a merged-duplicate row — see the Known Gaps / backlog note above; this is explicitly out of scope for Phase 4.
- The merge-on-click test (D6), asserting the pointer outcome, proves that specific scenario — it does NOT prove every possible timing race (e.g. two phantom candidates matching ambiguously, or a merge attempt arriving mid-aggregation-batch) unless those cases are explicitly added; this remains a known residual, not blocking.
- The D8 predicate regression test proves the corrected EXISTS-subquery logic for a single phantom/single merged-child scenario; it does NOT prove behavior when a phantom somehow accumulates more than one merged child (should not happen given the email-uniqueness-per-site dedup key, but not explicitly tested).
- The offline `--sql` migration validation proves the DDL is syntactically valid in both directions; it does NOT prove a live-apply against a populated production table is safe at scale — that step is explicitly deferred (known-gap, operator action).
- The full unfiltered unit lane proves no regression against the 1589-test baseline captured 04-08-26 pre-EXECUTE; it does NOT prove anything about integration-lane or e2e-lane behavior, both of which remain environment-blocked known-gaps in this sandbox.

Gate: CONDITIONAL (0 FAILs remaining; 1 FAIL found and fixed in-plan during this pass — the D1/C2 predicate self-contradiction — plus 3 additional CONCERNs found and fixed in-plan (missing unfiltered unit-lane gate, missing CSV email-format validation, mischaracterized consumer-awareness claim); 1 known-gap deferred to backlog (merged-visitor consumer awareness, pre-existing, out of blast radius); 2 known-gaps deferred to environment/operator action (integration lane — no Docker; live migration apply — explicit operator action). No unresolved FAILs. Plan and validate-contract are both current as of 04-08-26; this phase is clear to proceed to EXECUTE.)
Accepted by: session (autonomous inner-PVL pass, 04-08-26) — accepted concerns/gaps: alembic head drift (mitigated via live re-verification instruction, re-confirmed stable this pass), CSV email-format validation gap (fixed via B1a), D1/C2 predicate self-contradiction (fixed via corrected EXISTS-subquery design + D8 test), missing unfiltered unit-lane gate (fixed — added to Exit Gate, baseline captured), mischaracterized consumer-awareness claim (corrected in-plan + backlog note written), integration-lane environment block (known-gap, matches Phase 1/2 precedent), live migration apply (known-gap, explicit operator action per umbrella hard-stop).

---

## Inner Loop Refresh Note

**Date: 2026-08-04** — Inner-loop RESEARCH has run and its findings are baked into this plan
(Merge Mechanism Decision section added; Step C rewritten to verification-only; D6 test assertion
corrected to pointer semantics; alembic head updated to `b1c9e7f24d83`; CSV body-size middleware
gap confirmed; UI route location confirmed empty; Phase 5 cross-phase note resolved). **PVL
re-run is required** — the existing 03-08-26 validate-contract above is STALE and must not be
treated as current; do not proceed to EXECUTE against it.

**RESOLVED 2026-08-04 by inner-PVL (see `## Validate Contract` above):** the PVL re-run required by
this note is now complete. Gate: CONDITIONAL, 0 unresolved FAILs, all fixable concerns applied
directly to plan text, one pre-existing cross-cutting gap deferred to backlog. This phase is clear
to proceed to EXECUTE.
