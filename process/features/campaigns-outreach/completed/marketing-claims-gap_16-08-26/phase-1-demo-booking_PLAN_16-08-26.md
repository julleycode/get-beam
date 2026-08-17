---
name: plan:marketing-claims-gap-phase-1-demo-booking
description: "Marketing Claims Gap — Phase 1: demo booking link in drafts + demo-booked conversion attribution"
date: 16-08-26
metadata:
  node_type: memory
  type: plan
  feature: campaigns-outreach
  phase: phase-1
---

# Phase 1 — Demo Booking

**Program:** marketing-claims-gap
**Umbrella plan:** `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/marketing-claims-gap-umbrella_PLAN_16-08-26.md`
**Date**: 16-08-26
**Complexity**: SIMPLE (medium — one migration, one token, one preset endpoint)
**Status**: ⏳ PLANNED
**Report destination:** `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-1-demo-booking_REPORT_16-08-26.md`

---

## Overview

Beam's copy promises "book demos from your anonymous traffic." Today a site has no booking URL
anywhere in the data model, drafts have no way to render one, and if a human pastes a Calendly link
into a draft it is invisible to attribution — `link_decorator.py:88` decorates **same-host links
only**, so a third-party booking link never receives the `_bid`/`_tp` params that `CampaignClick`
needs.

The good news from research: the entire outcome stack already exists. `ConversionGoal` (with
`goal_type="url_match"` and a `pattern` column + `match_type` exact/prefix/contains), `CampaignClick`, `Conversion`,
`conversion_tracker.matches_goal` (pure) and `process_batch` (runs on pixel ingest), plus a goals
CRUD API and an HMAC webhook endpoint at `routers/outcomes.py:421`. "Demo booked" is therefore a
**ConversionGoal preset**, not new machinery.

**Naming correction (PVL F-1):** `url_match` is a *value* of the `goal_type` column
(`apps/api/models/outcome.py:49`, default `"url_match"`). The URL/path itself is stored in the
**`pattern`** column (`outcome.py:52`, `String(500)`, NOT NULL). Anywhere this plan previously used
`url_match` in a column sense, read **`pattern`**.

**Input shape correction (PVL F-2):** `matches_goal` compares the pattern against a **normalized
path** (`conversion_tracker.py:71-81`, `:281`, `:46-58`) — `/thanks`, never
`https://acme.com/thanks`. `validate_goal_pattern` (`apps/api/schemas/outcomes.py:24-26`) raises
`ValueError("exact/prefix patterns must start with '/'")` for any exact/prefix pattern not starting
with `/`. The preset therefore takes a **path**, and the UI must say so.

This phase does three small things and deliberately does not fix the third-party decoration hole.

Context: `process/context/all-context.md` (router), `process/context/tests/all-tests.md`,
`process/features/campaigns-outreach/_GUIDE.md`.

---

## Locked Decisions

| # | Decision | Alternative considered (rejected) |
|---|---|---|
| D1 | Store the booking link as `Site.booking_url`, nullable `String(500)`, additive migration. Prior art: `Site.leadpipe_pixel_id` (`site.py:111`). | Per-campaign booking URL — rejected: multiplies config surface for a value that is site-level in practice. |
| D2 | Expose it to drafts as a `{{booking_link}}` token resolved in `campaign_sender._personalize` (`:95`), with an instruction added to the planner prompt (`campaign_planner.py:76` area). **Correction (PVL F-4/gap-4): the dashboard draft view shows the RAW stored template — tokens are NOT rendered there.** The only surface where a human sees a *rendered* `{{booking_link}}` before approving is the `[TEST]` preview-send endpoint (`routers/campaigns.py:477` subject / `:482` body). All human-visible verification targets that endpoint. | Auto-appending a booking CTA to every email — rejected: mutates copy the human approved. |
| D3 | v1 attribution route = **customer sets their Calendly/Cal.com redirect to their own thank-you page**, then a "Demo booked" `ConversionGoal` with `goal_type="url_match"`, `match_type="prefix"`, and `pattern` = the thank-you **path** (e.g. `/thanks`). Uses the existing url_match goal type unchanged. | Provider webhook via the existing HMAC endpoint — deferred to v2, documented below. `js_event` goal type — scaffolded but less universal. |
| D4 | Offer a one-click "Demo booked" goal **preset**. **LOCKED (PVL C-5): the preset is UI-only pre-fill posting to the existing `POST /{site_id}/goals` (`outcomes.py:104-149`). No new endpoint.** That endpoint already enforces the per-site goal cap, the name-taken 409 pre-check, the `IntegrityError` 409 race, and shared `validate_goal_pattern`. Do NOT auto-create a goal on `booking_url` save. | (a) A new backend preset endpoint — rejected as YAGNI: duplicated surface, zero added behavior, and it would have to re-implement the caps/409s. (b) Auto-create — rejected: silently creating a conversion goal changes a site's reported metrics without consent. |
| D5 | Add an explicit test asserting a third-party host is NOT decorated, locking current behavior as **documented**. **Rationale correction (PVL C-7): same-host-only decoration is a PRIVACY GUARANTEE — the encrypted `_bid` token must never leak to a third-party domain.** It is not a link-parsing concern. | Decorating third-party links — rejected **permanently, not just for v1**: it would leak an encrypted-email token to Calendly/Cal.com. Valid v2 routes are the provider webhook and a redirect-through-Beam interstitial only. |

**Hard constraint restated:** nothing in this phase creates a path to
`campaign_sender.send_campaign_emails` that bypasses human approval. The token renders into a
DRAFT.

---

## Entry Gate

- **Phase 1 code work (Steps B, C, D, E, F) has no upstream dependency and may start immediately.**
- **Working-tree coupling on two Phase-1 files (PVL gap 5) — blocking precondition.**
  `apps/api/models/site.py` and `apps/api/routers/sites.py` are **both already dirty** with
  uncommitted concurrent site-analysis work. Measured 16-08-26 via
  `git diff --stat apps/api/models/site.py apps/api/routers/sites.py`:
  `site.py | 24 +++++-`, `sites.py | 197 ++++…`, **220 insertions / 1 deletion** (**drifting snapshot,
  16-08-26 — the concurrent session is still editing; an EXECUTE-time mismatch is EXPECTED, re-measure,
  not a blocker**). Steps A1, B1 and B2
  edit exactly those two files. **Before the first edit**, EXECUTE must re-run that `git diff --stat`
  and record its verbatim output in the phase report, so a later diff can separate Phase-1 changes
  from the pre-existing site-analysis changes.
  **Forbidden: `git stash`, `git checkout --`, `git restore`, `git revert`, `git rebase`, or any other
  command that discards or replays those uncommitted changes** — a concurrent session owns them
  (memory note `concurrent-session-rebase-eats-uncommitted-work`). Edit additively on top of the dirty
  tree; never "clean up first".
- **Step A (migration) IS gated (PVL F-4).** The live head is `d7e2b4c81f93`
  (`..._add_waitlist_application_fields.py`), which is **UNTRACKED**, and its parent
  `c5e1a9b73d20_add_site_profile.py` is **also untracked** — both belong to the working-tree
  site-analysis work. Step A therefore inherits the umbrella's **Phase 0 operator precondition**:
  the site-analysis migration tree must be committed (or explicitly frozen / re-chained) before the
  booking_url revision is written. Until then the migration chain couples Phase 1 to Phase 0, and the
  umbrella's "Phase 1 is fully independent" claim holds for code only, not for Step A.
- Local Postgres reachable on `:5433` before Hybrid gates: `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`.

---

## Blast Radius

Risk class: schema/migration (one additive nullable column) + public API contract (additive field).
No auth, no billing, no secrets, no send-path behavior change.

- `apps/api/models/site.py` — add `booking_url`
- `apps/api/migrations/versions/<new>_add_site_booking_url.py` — new revision
- `apps/api/schemas/sites.py` — additive optional `booking_url` on site in/out schemas
- `apps/api/routers/sites.py` — accept `booking_url` on site update
- `apps/api/services/campaign_sender.py` — `_personalize` gains `{{booking_link}}`; `select(...)` at `:248` gains `Site.booking_url`; `_compose_generic` (def `:160`, `_personalize` call `:172`) and `_compose_for_recipient` (`:175`) thread it through
- `apps/api/routers/campaigns.py` — **second live caller of `_personalize`** (imports at `:37`, calls at `:477` subject and `:482` body for the `[TEST]` preview send). Any signature change breaks or silently blanks this call site; both calls must be updated in the same edit.
- `apps/api/agents/campaign_planner.py` — prompt instruction for the token
- `apps/web/src/lib/api-types.ts` + site settings UI — booking URL field
- `tests/unit/test_campaign_sender_tokens.py` (new), `tests/unit/test_campaign_planner_prompt.py` (new — AC-4's home;
  PVL N-3: no `campaign_planner` test file exists anywhere, so `-k campaign_planner` collected ZERO tests),
  `tests/integration/test_booking_goal_preset.py` (new),
  `tests/unit/test_campaign_send_booking_link.py` (new — AC-2b end-to-end send gate; **UNIT, not
  integration — re-tiered per PVL gap 1 / M-1: the proven prior-art harness needs no Postgres/Redis**),
  `tests/unit/test_link_decoration.py` (EXISTING — EXTENDED, not created; PVL N-1)

Approx 10 files + 1 migration.

---

## Touchpoints

Same list as Blast Radius — explicitly including `apps/api/routers/campaigns.py` (the `[TEST]`
preview-send `_personalize` call sites at `:477`/`:482`). Read-only touchpoints (inspected, not modified):
`apps/api/services/link_decorator.py`, `apps/api/services/conversion_tracker.py`,
`apps/api/models/outcome.py`, and `apps/api/routers/outcomes.py` — **read-only (PVL N-4): confirm
`create_goal` (`:104-149`) accepts the preset body unchanged; add NO code there** (Locked Decision D4).

---

## Public Contracts

- `Site` API gains an optional `booking_url` field. Additive; no field removed or retyped.
- `{{booking_link}}` is a new personalization token. It **resolves in both compose branches**
  (`_compose_for_recipient` verified path AND `_compose_generic` non-verified path) and in the
  `[TEST]` preview-send path. Unknown/empty `booking_url` must **resolve** to an empty string —
  **never** the literal text `None`, and never merely be left for `_LEFTOVER_TOKEN` to strip inside an
  anchor (which would yield `href=""`). The token is documented as **bare-URL-only**: templates must
  not wrap it in `<a href="…">`.
- `booking_url` is owner-supplied text substituted by raw `str.replace` into outbound HTML. It is
  validated at the API boundary (http(s) scheme only, no `<>"'`, max 500 chars) — that validation is
  the security contract, since nothing downstream escapes it.
- `link_decorator.decorate_links` behavior is UNCHANGED (same-host only). The extended test documents,
  not alters, this contract.
- **Documented residual (PVL P10 — ORCHESTRATOR DECISION, LOCKED: ACCEPT, no code change).** A
  `booking_url` hosted on a **subdomain of the customer's own host** WILL receive the encrypted `_bid`
  param — proven behavior, not a gap (`tests/unit/test_link_decoration.py:30
  test_www_and_subdomain_match`). Accepted because the destination is same-tenant and owner-controlled:
  the token rides to a host the site owner already operates, so no third party gains it. Risk: low.
  Mitigation is advisory only — B1 helper text recommends a path-based or third-party booking URL for
  owners who object. No validator change, no decorator change.
- The send path (`send_campaign_emails`) is unchanged. Human approval gate unchanged.
- The "Demo booked" preset creates an ordinary `ConversionGoal` row — no new goal type.

---

## Implementation Checklist

### Step A — Schema

- [x] A1. Add `booking_url: Mapped[str | None] = mapped_column(String(500), nullable=True)` to `apps/api/models/site.py`, mirroring the `leadpipe_pixel_id` declaration style at `site.py:111`.
- [ ] A2. **BLOCKED (infra) — Docker daemon would not start this session; no PG on :5433.** Re-derive the live head FIRST: `DATABASE_URL=postgresql+asyncpg://<user>:<pw>@localhost:5433/<db> .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads`. Do NOT trust any head recorded in a plan or context file.
- [x] A2b. **Committed-parent check (PVL F-4) — blocking.** Run
  `git ls-files --error-unmatch apps/api/migrations/versions/<head-rev>*.py`. It must exit 0.
  As of 16-08-26 it does NOT: live head `d7e2b4c81f93` is untracked, and its parent
  `c5e1a9b73d20` is untracked too. **STOP rule:** if the live head is untracked, do not chain off it,
  and do not silently chain off an older tracked revision (that creates a second head). Report and
  escalate — the site-analysis tree must be committed or frozen first (see Entry Gate).
- [x] A3. Only after A2b exits 0: create `apps/api/migrations/versions/<rev>_add_site_booking_url.py` chaining `down_revision` off the head from A2. Upgrade adds the nullable column; downgrade drops it.
- [ ] A4. **BLOCKED (infra) — same.** Live round-trip with `DATABASE_URL` pinned to `localhost:5433`: `upgrade head`, then `downgrade -1`, then `upgrade head`. **Never** run a bare alembic command — repo `.env` points at Supabase PROD.

### Step B — API + schema surface

- [x] B1. Add optional `booking_url` to the site update request schema and site response schema in `apps/api/schemas/sites.py`. Validation (PVL C-6 — this value is `str.replace`'d **unescaped** into outbound HTML email, so scheme-checking alone is insufficient):
  - reject any scheme other than `http` / `https` (blocks `javascript:`, `data:`) — must be an absolute URL;
  - reject the value if it contains any of `<`, `>`, `"`, `'` (HTML-injection surface in outbound mail);
  - **(PVL gap 6) also reject `)` and any whitespace character.** Rationale: the stored URL must survive
    link decoration intact, and `link_decorator._URL_RE` (`apps/api/services/link_decorator.py:79`,
    `r'https?://[^\s"\'<>)]+'`) **terminates** a URL at any of `\s " ' < > )`. A booking URL containing
    one of those characters would be silently truncated mid-URL by the decorator, producing a broken
    link in outbound mail. The validator's reject set must therefore MATCH the decorator's terminator
    set exactly: `< > " ' )` plus whitespace.
  - cap length at 500 chars to match the column width.
  Note: `SiteCreate.url` has no scheme validation to copy — this is a genuinely new validator. Add a unit case for a hostile value (e.g. `javascript:alert(1)` and `https://x.com/"><script>`) asserting rejection.
- [x] B2. Wire `booking_url` through the site update handler in `apps/api/routers/sites.py`, respecting the existing `Site.user_id == user.id` tenancy filter.
- [x] B3. Add `booking_url?: string` to the `Site` type in `apps/web/src/lib/api-types.ts` and a field in the site settings form, with helper text explaining the thank-you-page redirect requirement for attribution. **Add the
  subdomain note (PVL P10):** if the booking URL is on a subdomain of your own site, campaign links to it
  will carry Beam's encrypted click token; use a path on your own site or a third-party booking host if
  you prefer it not to.

### Step C — `{{booking_link}}` token

`_personalize` is a **pure** function taking `(text, full_name, company_name, sender_name)` — it has
no db/campaign/site access. Threading `booking_url` to it is the real work (PVL C-1). C1 is therefore
**eight explicit sub-steps (C1a–C1h)**, all in one edit.

**Append-only signature rule (PVL gap 4) — mandatory.** `booking_url` MUST be appended at the **END**
of every signature and at the **END** of the `select(...)` tuple. It must never be inserted in the
middle. Reasons, measured:
- `campaign_sender.py:253-258` consumes the `:248` select **positionally** — `site_row[0]`=`site.url`,
  `[1]`=`site.name`, `[2]`=`sender_name`, `[3]`=`owner_email`. Inserting a column mid-tuple silently
  rebinds `sender_name`/`owner_email` to the wrong values with no type error.
- `_compose_for_recipient` has **positional callers** that this phase does not otherwise touch:
  `apps/api/services/campaign_sender.py:377`, `tests/unit/test_contact_importer.py:124`,
  `tests/unit/test_outbound_identity_gate.py:101` and `:124`. A mid-signature insertion shifts every
  one of them.
- **(PVL gap 2 / M-2) Appending to the `:248` select changes the returned row's ARITY — append-last is
  safe for ORDER but is NOT free.** Exactly two tests in the repo hard-code the `site_row` **4-tuple**
  and will raise `IndexError: tuple index out of range` the moment `Site.booking_url` is appended
  (measured: `grep -rn "first.return_value = (" tests/` returns these two and nothing else):
  `tests/unit/test_gmail_sender_decoration_parity.py:84` and
  `tests/unit/test_agent_origin_exclusion.py:119` — the latter is described in
  `process/context/all-context.md` as *the program's highest-priority guardrail test*.
  **Required: extend BOTH fixture tuples to 5 elements in the same edit** (add a booking-URL element
  last). **FORBIDDEN: defensive length checks in production code** (e.g.
  `site_row[4] if len(site_row) > 4 else None`) — that would mask a genuinely mis-ordered select,
  which is the exact failure the append-only rule exists to prevent. A red on
  `test_agent_origin_exclusion.py` is EXPECTED from this edit and must be fixed at the fixture,
  never by weakening its assertion.

- [x] C1a. `apps/api/services/campaign_sender.py:248` — add `Site.booking_url` to
  `select(Site.url, Site.name, User.full_name, User.email)`. The value is not otherwise reachable
  inside `send_campaign_emails`.
- [x] C1b. `_personalize` (`:95`) — add a `booking_url` parameter and add the token to the replace chain.
  **(PVL N-5) Replace BOTH forms — `{{booking_link}}` AND `{booking_link}`** — mirroring every existing
  token (`:113-121` replaces both forms for `first_name`/`company_name`). `_LEFTOVER_TOKEN` (`:71`,
  `r"\{\{\s*[\w.]+\s*\}\}"`) strips only the DOUBLE-brace form, so a single-brace `{booking_link}` —
  exactly what an LLM planner emits when brace-escaping slips — would otherwise ship as literal text in
  an outbound email.
- [x] C1c. `_compose_generic` (def `:160`; its `_personalize` call `:172`) — accept and forward `booking_url`.
- [x] C1d. `_compose_for_recipient` (`:175`) — accept and forward `booking_url` on the verified path.
- [x] C1e. `apps/api/routers/campaigns.py` — update BOTH `[TEST]` preview call sites, `:477` (subject)
  and `:482` (body), fetching the site's `booking_url` for the preview. Verify with
  `grep -rn "_personalize" apps/api --include="*.py"` before and after the edit.
- [x] C1f. **(PVL C-2)** `booking_link` must render **identically in both compose branches**.
  `_compose_for_recipient` routes non-verified recipients to `_compose_generic`; if `booking_url` is
  not passed there too, the token is stripped by `_tidy`/`_LEFTOVER_TOKEN` for every
  candidate/anonymous recipient while verified ones get the link. `booking_url` is Beam-customer
  first-party data (like the sender signature the generic branch already fills), not a guess about the
  recipient. Add a unit case asserting the **generic branch** renders it.
- [x] C1g. **(PVL gap 1) `apps/api/services/campaign_sender.py:377`** — the `_compose_for_recipient`
  call inside `send_campaign_emails` is the **ONLY** path from the `:248` select to a real outbound
  email. Pass the `booking_url` read in C1a into that call (appended last, per the append-only rule).
  Without this edit every unit gate can be green while the shipped product never renders the token.
  **Gate mechanism (PVL gap 1 / M-1) — copy the proven in-repo harness, do not improvise:**
  `tests/unit/test_gmail_sender_decoration_parity.py:47-121` (`_run_send`) already drives the REAL
  `send_campaign_emails` end-to-end and captures the outbound body via
  `monkeypatch.setattr(campaign_sender, "EmailSender", MagicMock(return_value=sendgrid_instance))`
  with `captured["body"] = kwargs["body_html"]` (`:57-64`), also patching `send_via_gmail` (`:72`),
  `resolve_sender_for_site` (`:73-77`), `is_email_suppressed` (`:78`) and `check_and_reserve_email`
  (`:79`). It is `pytest.mark.unit` and requires **no Postgres and no Redis**. Do NOT rely on
  `MOCK_EXTERNAL_APIS=true`: `email_sender.py` has zero `MOCK` references and `EmailSender.send`
  (`:104-133`) POSTs to SendGrid unconditionally — a literal reading of the old wording captures
  nothing (the POST raises, is caught at `campaign_sender.py:461`, and `summary["sent"]` stays 0).
  Set `site_result.first.return_value` to the 5-tuple (booking URL last) and assert
  `summary["sent"] == 1` before asserting on the captured body.
- [x] C1h. **(PVL gap 1) `campaign_sender.py:196` and `:197`** — the two `_compose_generic(...)` calls
  inside `_compose_for_recipient` (non-verified branch). Forward `booking_url` into **both**; missing
  either one silently blanks the token for every candidate/anonymous recipient (this is the concrete
  mechanism behind C1f).
- [x] C2. Define the empty behavior explicitly: when `booking_url` is `None`/blank the token must be
  **resolved** to `""` inside `_personalize` — not merely left for `_LEFTOVER_TOKEN` to strip
  (PVL C-3). Unit cases required: (a) token mid-sentence — surrounding prose still reads correctly;
  (b) token as a bare URL; (c) token inside `<a href="{{booking_link}}">Book</a>` — stripping alone
  yields `href=""`, a broken anchor, so either handle the anchor form or document the token as
  bare-URL-only and assert that documented behavior; (d) **(PVL N-5) the single-brace `{booking_link}`
  form also resolves** (and, when unset, resolves to `""` rather than surviving as literal text —
  `_LEFTOVER_TOKEN` cannot strip it). Never `"None"`.
- [x] C2b. **(PVL gap 3 / M-3) Byte-for-byte round-trip of the RESOLVED value.** `_personalize` ends
  `return _tidy(out)` (`campaign_sender.py:120`), so `_tidy` runs **after** substitution and therefore
  post-processes the booking URL itself. `_LEFTOVER_HINT` (`campaign_sender.py:74`,
  `r"\[[a-z][^\]]*\]"`) DELETES any lowercase-led `[...]` span, and `_HOLLOW_PARENS` + whitespace /
  punctuation collapse also act on the substituted text. B1's reject set is coupled to `_URL_RE`'s
  terminator set (`< > " ' )` + whitespace) and deliberately does NOT cover `[` / `]`. Add one unit
  case asserting `_personalize` returns the booking URL **byte-for-byte unmodified** for a URL that
  contains `[`, `(`, and a trailing `.` — one generic assertion that catches any `_tidy` mangling
  class, rather than enumerating characters.
- [x] C3. In `apps/api/agents/campaign_planner.py` `CAMPAIGN_PLANNING_PROMPT`, document
  `{{booking_link}}` and instruct the model to use it ONLY when the site has a booking URL configured.
  **(PVL C-4) The prompt is a brace-escaped `.format()` template** — existing tokens appear as
  `{{{{first_name}}}}` (see the JSON example `"body"` line at `campaign_planner.py:76`) so `.format()`
  emits `{{first_name}}`. The new token MUST be written `{{{{booking_link}}}}`; writing it unescaped
  raises `KeyError`/`IndexError` at format time or emits a single-brace token. There is no "token
  table" at `:76` — it is one inline sentence inside the JSON output example; add the token there and
  to the `personalization_fields` example list.
- [x] C3b. **(PVL N-3)** Create `tests/unit/test_campaign_planner_prompt.py` — AC-4 has no existing home
  (`-k campaign_planner` collects ZERO tests; no planner test file exists under `tests/`). It must assert
  `CAMPAIGN_PLANNING_PROMPT.format(...)` succeeds AND that the output contains the literal
  `{{booking_link}}`. Declare `pytestmark = pytest.mark.unit` at the top (see F3).
  **(PVL gap 7) `CAMPAIGN_PLANNING_PROMPT.format()` requires exactly these 9 kwargs**
  (`campaign_planner.py:197-209`) — omitting any one raises `KeyError`, so the test must pass all 9:
  `segment_name`, `segment_description`, `visitor_count`, `characteristics_json`, `channels`,
  `messaging_angle`, `visitor_profiles_json`, `segment_id`, `connected_accounts_info`.
  Note `_GENERIC_COPY_NOTE` (`campaign_planner.py:123-131`) is a **separate** template appended at
  `:210` via `_generic_copy_note(...)`; it already carries its own `{{{{first_name}}}}` escaping and is
  **deliberately out of scope** for this phase — do not add the booking token to it and do not assert
  on it.
- [x] C4. Confirm `_compose_for_recipient` (`:175`) → `decorate_links` (`:419`) → unsubscribe footer (`_unsubscribe_footer(iv.email)` at `:431` — `:421` is the open-tracking pixel append; PVL N-6) ordering is unchanged and the token is resolved BEFORE decoration runs.

### Step D — "Demo booked" conversion goal preset

- [x] D1. **No new backend endpoint (Locked Decision D4 / PVL C-5).** The preset posts to the
  existing `POST /{site_id}/goals` (`apps/api/routers/outcomes.py:104-149`), which already handles
  the per-site goal cap, name-taken 409, `IntegrityError` 409 race, and `validate_goal_pattern`.
  Confirm by reading that handler that the following body is accepted unchanged, and add no
  `routers/outcomes.py` code:
  `{"name": "Demo booked", "goal_type": "url_match", "match_type": "prefix", "pattern": "/thanks"}`
  — note **`pattern`**, not `url_match` (PVL F-1: `url_match` is the `goal_type` value; the column is
  `pattern`, `models/outcome.py:52`), and note the value is a **path** starting with `/`
  (PVL F-2: `schemas/outcomes.py:24-26` rejects exact/prefix patterns that do not start with `/`, and
  `matches_goal` compares a normalized path, so a full `https://…` URL is both rejected at create time
  and unmatchable if it somehow persisted).
- [x] D2. Do NOT auto-create the goal when `booking_url` is saved (D4). Surface it as an explicit action in the UI.
- [x] D3. Add UI affordance: after a `booking_url` is saved, offer "Track demo bookings", which
  **pre-fills the existing goal form** with `match_type=prefix` and a placeholder **path** (`/thanks`),
  then posts to the existing goals endpoint. Helper text must state: *enter the path of your thank-you
  page (e.g. `/thanks`), not a full URL — it must start with `/`.*
- [x] D4. Document the v2 route in code comments and in the phase report: provider webhook → existing HMAC endpoint at `routers/outcomes.py:421` with its rotatable secret. Not implemented in v1.

### Step E — Attribution hole documentation

- [x] E1. **EXTEND the existing `tests/unit/test_link_decoration.py` — do NOT create a new file (PVL N-1).**
  Measured fact: that file already contains `test_third_party_link_not_decorated` (`:36`, using the exact
  `https://calendly.com/...` shape) with a non-vacuous same-host control (`assert len(_bids(out)) == 1`,
  which requires a real Fernet token), plus `test_www_and_subdomain_match` (`:30`) covering the
  customer-subdomain case. All 8 tests pass
  (`.venv/bin/python3.11 -m pytest tests/unit/test_link_decoration.py -q` → `8 passed`). Add ONE
  booking-URL-shaped case to that file: a `booking_url` on a third-party host stays undecorated while the
  same-host control IS decorated in the same call. A separate `test_link_decorator_third_party.py` would
  duplicate coverage that already exists — do not create it.
- [x] E2. **Extend** (do not add from scratch) the existing `decorate_links` docstring — it already
  states that only the customer's own host and subdomains are decorated because *"the encrypted `_bid`
  token is never leaked to third-party domains"*. Append only the **attribution consequence**: booking
  attribution therefore relies on the redirect-to-thank-you-page route (D3). Do NOT restate the
  rationale as a link-parsing concern (PVL C-7) — it is a privacy guarantee.
- [x] E3. Write a backlog note `process/features/campaigns-outreach/backlog/third-party-link-attribution_NOTE_16-08-26.md`.
  It must frame the limit as a **privacy guarantee**, and list exactly two candidate v2 routes:
  (a) provider webhook via the existing HMAC endpoint (`routers/outcomes.py:421`), and
  (b) redirect-through-Beam interstitial. **"Decorate third-party links" is explicitly NOT a candidate
  fix** — it would leak an encrypted-email token to Calendly/Cal.com.

### Step F — Regression safety

- [x] F1. **Caller-set invariant, not a "changed modules" grep (PVL C-8).** A "new modules must not
  reference `send_campaign_emails`" gate is self-tripping: this phase edits `campaign_sender.py`
  (which *defines* it) and `campaigns.py` (which imports and calls it). The gate is instead:
  `grep -rn "send_campaign_emails" apps/api --include="*.py"` must yield **exactly** the pre-existing
  set and nothing more —
  `apps/api/services/campaign_sender.py:201` (def) plus `apps/api/routers/campaigns.py:38` (import),
  `:559` (docstring), `:607`, `:658` (calls), `:862` (comment). Any additional line = FAIL.
- [x] F2. **Whole-phase regression uses the UNMARKED unit lane (PVL N-2):**
  `.venv/bin/python3.11 -m pytest tests/unit -q` and
  `.venv/bin/python3.11 -m pytest tests/ -m integration -q`. **Drifting snapshots (16-08-26) — an
  EXECUTE-time mismatch is EXPECTED, re-measure, not a blocker:** unmarked `tests/unit` collects
  **2804** tests (was 2802, and 2799 hours earlier — a concurrent session is still adding tests);
  `-m unit` collects **1842 (962 deselected)** because only
  **92 of 160** files carry a `unit` marker and `tests/conftest.py` does NOT auto-mark by path. The
  deselected set includes `tests/unit/test_link_decoration.py` (the only coverage of `decorate_links`,
  Step E's subject) and `tests/unit/test_personalize.py` (the only coverage of `_personalize`, whose
  signature Step C changes) — so the marker lane is structurally blind exactly where this phase is most
  exposed. Measure the baseline **in this session** before the first edit; every collection figure
  written in this plan is a drifting snapshot, never an assertion target. Integration requires **both** Postgres `:5433` and Redis `:6379` listening — a hard
  precondition, not conditional.
- [x] F3. **(PVL N-2) Every NEW test file created by this phase must declare
  `pytestmark = pytest.mark.unit`** (or `pytest.mark.integration`) at module top. This repo does not
  auto-mark by path; an unmarked file is fully deselected by `-m unit` and pytest exits **5**. Applies to
  `tests/unit/test_campaign_sender_tokens.py`, `tests/unit/test_campaign_planner_prompt.py`,
  `tests/integration/test_booking_goal_preset.py`, and
  `tests/unit/test_campaign_send_booking_link.py` (the latter is `unit`, per the M-1 re-tier).

---

## Acceptance Criteria

| # | Criterion |
|---|---|
| AC-1 | A site owner can save a `booking_url`; it persists and round-trips through the API. |
| AC-2a | **Compose surfaces (direct calls).** `{{booking_link}}` renders the site's booking URL when `_personalize`, `_compose_generic`, and `_compose_for_recipient` are called directly, and in the `[TEST]` preview-send path (`campaigns.py:477/:482`). The dashboard draft view is NOT a target — it shows the raw stored template. |
| AC-2b | **End-to-end delivery (PVL gap 3; mechanism corrected by M-1).** `send_campaign_emails` itself delivers the URL: the rendered outbound body captured from the real send path CONTAINS that booking URL. **`MOCK_EXTERNAL_APIS=true` does NOT apply here** — `apps/api/services/email_sender.py` has no mock branch and `EmailSender.send` POSTs unconditionally (measured: zero `MOCK` hits in that file). Capture instead via `monkeypatch.setattr(campaign_sender, "EmailSender", MagicMock(return_value=fake))`, reading `kwargs["body_html"]`. Non-vacuity guard: assert `summary["sent"] == 1` BEFORE asserting on the body. AC-2a can be fully green while the feature ships inert if the `:377` call site (C1g) was missed — AC-2b is the gate that catches it. |
| AC-3 | With `booking_url` unset, `{{booking_link}}` is resolved to empty — never the string `None`, and never left to be stripped inside an anchor (`href=""`). Covered mid-sentence, bare-URL, anchor, and single-brace `{booking_link}` forms. **Plus (M-3): when SET, the resolved URL emerges from `_personalize` byte-for-byte unmodified** — including a URL containing `[`, `(`, and a trailing `.` — because `_tidy` (`:120`) runs AFTER substitution and `_LEFTOVER_HINT` (`:74`) deletes lowercase-led `[...]` spans. |
| AC-4 | The planner prompt documents the token with correct `{{{{booking_link}}}}` escaping (`.format()` succeeds and emits `{{booking_link}}`) and only suggests it for sites that have a booking URL. Proven by the NEW `tests/unit/test_campaign_planner_prompt.py` (C3b) — not by a `-k campaign_planner` filter, which collects zero tests. |
| AC-5 | A "Demo booked" `ConversionGoal` created via the **existing** `POST /{site_id}/goals` with `goal_type="url_match"`, `match_type="prefix"`, `pattern="/thanks"` (a **path**) is matched by `conversion_tracker.matches_goal` for a landing path `/thanks/demo`; and a full `https://…` pattern is REJECTED by `validate_goal_pattern`. |
| AC-6 | No conversion goal is auto-created as a side effect of saving `booking_url`. |
| AC-7 | A third-party (non-same-host) link is provably NOT decorated, asserted in the EXISTING `tests/unit/test_link_decoration.py` (8/8 passing, non-vacuous same-host control) plus the booking-URL-shaped case E1 adds to that same file, and the limitation is documented in code and backlog. |
| AC-8 | The migration applies and reverses cleanly against local Postgres on `:5433`, **chained off a COMMITTED parent revision** (`git ls-files --error-unmatch` on the parent exits 0). |
| AC-9 | The `send_campaign_emails` caller set is unchanged — exactly `campaign_sender.py:201` + `campaigns.py:38,559,607,658,862`. |
| AC-10 | `booking_url` rejects non-`http(s)` schemes, any of `<>"'`, **`)` and whitespace** (matching `link_decorator._URL_RE`'s terminator set at `link_decorator.py:79`, so a stored URL can never be truncated mid-link by decoration), and values over 500 chars. |

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `.venv/bin/python3.11 -m pytest tests/unit/test_campaign_sender_tokens.py -q` exits 0 (file MUST carry `pytestmark = pytest.mark.unit`, F3) — must cover `_personalize`, `_compose_generic`, `_compose_for_recipient`, and the `campaigns.py` preview call; fixture site `booking_url` non-null | Fully-Automated | AC-2a, AC-3 |
| **(PVL gap 2; mechanism + tier corrected by M-1) NEW** `.venv/bin/python3.11 -m pytest tests/unit/test_campaign_send_booking_link.py -q` exits 0 — drives **`send_campaign_emails`** itself (not the compose helpers directly) for a campaign whose site has a non-null `booking_url`, and asserts the captured outbound body CONTAINS that exact booking URL. **Template: `tests/unit/test_gmail_sender_decoration_parity.py:47-121` (`_run_send`).** Capture mechanism: `monkeypatch.setattr(campaign_sender, "EmailSender", MagicMock(return_value=fake))`, assert on `kwargs["body_html"]`; also patch `send_via_gmail`, `resolve_sender_for_site`, `is_email_suppressed`, `check_and_reserve_email`. **`MOCK_EXTERNAL_APIS=true` is a NO-OP on this path** (`email_sender.py` has no mock branch) — do not use it as the mechanism. Non-vacuity guard: assert `summary["sent"] == 1` BEFORE asserting on the body, else a failed send yields an empty capture and a misleading red. This is the only gate that fails if C1g (the `:377` call site) is missed. File MUST declare `pytestmark = pytest.mark.unit` (F3). | Fully-Automated (re-tiered from Hybrid — the proven harness needs no Postgres/Redis) | AC-2b |
| `.venv/bin/python3.11 -m pytest tests/unit/test_campaign_planner_prompt.py -q` — assert `CAMPAIGN_PLANNING_PROMPT.format(...)` succeeds AND the output contains the literal `{{booking_link}}`. A `-k campaign_planner` filter collects ZERO tests (PVL N-3) — never use it | Fully-Automated | AC-4 |
| `.venv/bin/python3.11 -m pytest tests/unit/test_campaign_sender_tokens.py -q` (same marked file) — hostile values (`javascript:…`, `https://x.com/"><script>`, 501-char) rejected | Fully-Automated | AC-10 |
| `.venv/bin/python3.11 -m pytest tests/unit/test_link_decoration.py -q` exits 0 — EXISTING file (8/8 passing), EXTENDED by E1 with a booking-URL case; the same-host control assertion is already present and non-vacuous (an unset `settings.encryption_key` would make `decorate_links` a no-op) | Fully-Automated | AC-7 |
| `.venv/bin/python3.11 -m pytest tests/integration/test_booking_goal_preset.py -m integration -q` exits 0 — must PATCH a real non-null `booking_url` and re-GET it; assert a full-URL pattern is REJECTED | Hybrid — hard precondition: `lsof -nP -iTCP -sTCP:LISTEN \| grep -E '5433\|6379'` shows BOTH Postgres and Redis listeners | AC-1, AC-5, AC-6 |
| `git ls-files --error-unmatch apps/api/migrations/versions/<parent>*.py` exits 0, THEN `DATABASE_URL=<localhost:5433> .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head && ... downgrade -1 && ... upgrade head` | Hybrid — preconditions: committed parent revision; local PG up; `DATABASE_URL` pinned (bare alembic hits Supabase PROD) | AC-8 |
| `grep -rn "send_campaign_emails" apps/api --include="*.py"` yields exactly `campaign_sender.py:201` + `campaigns.py:38,559,607,658,862` and nothing more (caller-set invariant) | Fully-Automated | AC-9 |
| `.venv/bin/python3.11 -m pytest tests/unit -q` (UNMARKED lane — 2799 tests; the `-m unit` lane collects only 1837 and deselects `test_link_decoration.py` + `test_personalize.py`) and `.venv/bin/python3.11 -m pytest tests/ -m integration -q` — no new failures vs baseline measured this session | Fully-Automated | Whole-phase regression |
| Agent probe: trigger the `[TEST]` preview-send endpoint for a campaign whose site has `booking_url` set; confirm the delivered preview contains the resolved URL and campaign status is still `draft`. NOT the dashboard draft view — that renders the raw stored template | Agent-Probe | AC-2a, AC-9 (human-visible proof the approval gate is intact) |
| Real Calendly/Cal.com redirect actually lands on the customer's pixel'd thank-you page | Known-Gap (residual — backlog stub E3; gate stays CONDITIONAL) | AC-5 residual — needs-live-provider |

Failing stub (AC-2/AC-3, fully-automated):

```
test("{{booking_link}} renders site booking_url, and empty when unset", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: booking_link token resolution")
})
```

Failing stub (AC-7, fully-automated):

```
test("decorate_links leaves a third-party BOOKING host undecorated (extends existing file)", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: booking-URL third-party non-decoration")
})
```

Failing stub (AC-9, fully-automated):

```
test("no new module reaches send_campaign_emails", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: send-gate regression")
})
```

---

## Test Infra Improvement Notes

- **Measured (PVL N-1): `tests/unit/test_link_decoration.py` ALREADY covers same-host-only behavior —
  8 tests, all passing, including `test_third_party_link_not_decorated` (`:36`, Calendly-shaped, with a
  non-vacuous same-host control) and `test_www_and_subdomain_match` (`:30`). E1 EXTENDS that file; it does
  not create the first such test, and no `test_link_decorator_third_party.py` should exist.**
- **Marker split — drifting snapshot 16-08-26; EXECUTE-time mismatch is EXPECTED, re-measure, not a
  blocker (PVL N-2 / M-4):** `pytest tests/unit -q --collect-only` → **2804** (2802 and 2799 earlier
  the same day); `pytest tests/unit -m unit -q --collect-only` → **1842 collected, 962 deselected**.
  Only 92/160 files in
  `tests/unit` carry a `unit` marker; nothing auto-marks by path. Use the UNMARKED lane for whole-phase
  regression. A fully-deselected run exits 5 (loud), not 0 — so an unmarked new file fails visibly rather
  than passing vacuously.
- **No `campaign_planner` test file exists (PVL N-3):** `-k campaign_planner` collects zero tests both
  with and without the marker filter. AC-4 needs the new `tests/unit/test_campaign_planner_prompt.py`.
- Docker IS available at `/Applications/Docker.app/Contents/Resources/bin/docker` but is off `PATH`;
  detect via `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`. Do NOT mark Hybrid gates
  environment-blocked without running that check first.
- Use `.venv/bin/python3.11 -m pytest` — the `.venv/bin/pytest` shebang is broken in this repo.
- **(PVL gap 8) Alembic head-count tooling gotcha.** A naive on-disk scan of `down_revision` values in
  `apps/api/migrations/versions/` reports **5 heads** for this tree. That is a **parser artifact**, not a
  real branch: merge revisions declare `down_revision` as a **multi-line tuple**, which a line-oriented
  scanner fails to associate with its parents, so those parents look unreferenced. **`alembic heads` is
  the ONLY authoritative source** and reports a **single head, `d7e2b4c81f93`**. Never conclude "multiple
  heads / re-chain needed" from a grep or a hand-rolled script — always run
  `DATABASE_URL=<localhost:5433> .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` (A2).
- Lane rule for this phase: **per-file unit gates run bare** (`pytest tests/unit/<file>.py -q`, with the
  file marked per F3); the **whole-phase unit regression runs UNMARKED** (`pytest tests/unit -q`);
  integration keeps the marker lane (`pytest tests/ -m integration -q`). One canonical form per gate,
  identical in Verification Evidence and the validate-contract Test Gates table (PVL N-7).
- Integration needs **Redis `:6379` as well as Postgres `:5433`** — treat both as hard preconditions.
- **All numeric snapshots in this plan drift (M-4).** `git diff --stat` on the two shared files, the
  `update_site` line number, and both pytest collection counts are moving while a concurrent
  site-analysis session edits the tree. Every such figure is labelled a *drifting snapshot* —
  a mismatch at EXECUTE time is EXPECTED and must be re-measured in-session, never treated as an
  anomaly, a regression signal, or a blocker.
- **(PVL gap 1 / M-1) `EmailSender` has NO mock-mode branch.** `apps/api/services/email_sender.py`
  contains zero `MOCK` references; `EmailSender.send` (`:104-133`) POSTs to SendGrid unconditionally.
  This breaks the repo-wide "every external API works under `MOCK_EXTERNAL_APIS=true`" convention in
  `all-context.md`. Every send-path test must monkeypatch the class — prior art:
  `tests/unit/test_gmail_sender_decoration_parity.py:47-121`. Candidate cross-cutting fix (backlog):
  add a mock short-circuit to `EmailSender.send`.
- Vacuous-green hazards: (a) any `decorate_links` assertion is vacuously green when
  `settings.encryption_key` is unset (the function returns input unchanged) — the existing file already
  guards this with a same-host control; keep that guard in E1's added case; (b) an AC-1 assertion on a null
  `booking_url` proves nothing — PATCH a real value and re-GET it.
- Subdomain residual (PVL P10) is ACCEPTED as documented, not tested-away: `test_www_and_subdomain_match`
  already proves a customer-subdomain booking URL receives `_bid`. Same-tenant, owner-controlled
  destination; B1 helper text advises alternatives. No new gate.
- No gate covers the web/UI half (B3, D3): `apps/web` has no Clerk auth-harness for authenticated
  dashboard e2e in this repo. Recorded as a known-gap; those two items stay CONDITIONAL, not PASS.

---

## Exit Gate

```bash
lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'
# Expected: listeners on BOTH 5433 and 6379 (Redis is a hard integration precondition, not optional)

.venv/bin/python3.11 -m pytest tests/unit -q
# UNMARKED lane (drifting snapshot 16-08-26: 2804 tests). The -m unit lane collects only 1842
# and deselects test_link_decoration.py
# and test_personalize.py — the two files this phase most exposes.
# Expected: exit 0, no new failures vs this session's baseline

.venv/bin/python3.11 -m pytest tests/ -m integration -q
# Expected: exit 0, no new failures vs this session's baseline
# HARD precondition: BOTH :5433 and :6379 listening (the lsof check above must show both)

grep -rn "send_campaign_emails" apps/api --include="*.py"
# Expected exactly: campaign_sender.py:201; campaigns.py:38,559,607,658,862 — no additional line

DATABASE_URL=postgresql+asyncpg://USER:PW@localhost:5433/DB .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads
# Expected: single head, equal to the new booking_url revision

git ls-files --error-unmatch apps/api/migrations/versions/<parent-rev>*.py
# Expected: exit 0 (parent revision is COMMITTED). Non-zero => STOP, do not chain.

node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-1-demo-booking_PLAN_16-08-26.md
# Expected: failures: []
```

- All checklist items checked
- All AC-1, AC-2a, AC-2b, AC-3..AC-10 met (or explicitly recorded as known-gaps with rationale)
- Backlog note E3 written
- Phase report written to the report destination above
- Execution changes committed before Phase 2 starts

---

## Phase Completion Rules

- 🔨 CODE DONE — checklist complete, code compiles, unit tests green.
- 🧪 TESTING — Fully-Automated + Hybrid gates run; any failures triaged.
- ✅ VERIFIED — all gates green with their flag/precondition satisfied AND a validate-contract
  recorded AND the user has user-confirmed the rendered draft behaves as expected (AC-2a agent probe).
  A gate that passes only because a feature is inert does not count.
- 🚧 BLOCKED — see Blockers below.

Code-only completion is `CODE DONE`, never `VERIFIED`.

---

## Blockers That Would Justify BLOCKED Status

- Local Postgres on `:5433` genuinely unreachable after running the `lsof` detection (Hybrid gates
  cannot run; AC-8 unprovable).
- **`git ls-files --error-unmatch` on the live head revision file fails (head is UNTRACKED).** STOP.
  Do not chain the booking_url revision off an uncommitted parent, and do not chain off an older
  tracked revision instead (that creates a second head). Escalate: the site-analysis migration tree
  (`c5e1a9b73d20`, `d7e2b4c81f93`) must be committed or explicitly frozen/re-chained first. This is the
  live state as of 16-08-26 — expect to hit it.
- `alembic heads` returns more than one head — a concurrent program landed a migration; re-chain
  rather than force-merge, and stop if the correct parent is ambiguous.
- Adding the token would require restructuring `_compose_for_recipient` in a way that touches the
  approval gate — stop immediately; that is a hard safety constraint, not a design tradeoff.

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner
loop `R → I → P → PVL → E → EVL → UP` SKIPS SPEC.

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

1. Selected plan file path: `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-1-demo-booking_PLAN_16-08-26.md`
2. Last completed step: not started
3. Validate-contract status: pending
4. Supporting context files loaded: `process/context/all-context.md`,
   `process/context/tests/all-tests.md`, umbrella plan
5. Next step: spawn vc-research-agent for Phase 1 RESEARCH (Step 1). Do not `ENTER EXECUTE MODE`
   until PVL writes a full validate-contract.

---

## Next Step

Phase 1 plan complete. Run the inner loop starting at RESEARCH. `ENTER EXECUTE MODE` only after the
validate-contract below is written by vc-validate-agent.

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
supersedes: 2026-08-16 (outer-pvl) — PVL cycle 3 supplement applied; this cycle-4 re-validation has current evidence

Parallel strategy: sequential (single vc-execute-agent, model opus)
Rationale: signal score 5/7 (S1 multi-package, S2 schema+API surface, S4 phase program, S6 high-risk
class schema/migration + public API, S7 ~10 files). Score says HIGH, but Steps A→F share
`campaign_sender.py` / `campaigns.py` and are strictly order-dependent (schema → token threading →
goal preset), so a coordinating fan-out buys nothing and risks conflicting edits on one file. Fit
beats tier: sequential opus. Alternative if EXECUTE is later re-scoped: agent-team (TeamCreate +
TaskCreate + SendMessage) only if Step B3 (web) is split from Steps A/C/D (api) — never bare parallel
subagents, which cannot coordinate the shared `campaign_sender.py` edit.

**Validation method note (fan-out limitation):** this environment grants vc-validate-agent no Agent
tool, so the Layer 1 / Layer 2 fan-out ran as a single-pass sequential sweep by one agent rather than
as parallel dimension agents. Every finding below is backed by a command run in this session against
live source.

### Cycle 3 verification — the FAIL and all 5 CONCERNs CONFIRMED FIXED

| Prior gap | Claim | Live evidence this session | Verdict |
|---|---|---|---|
| N-8 (FAIL) | C1 omitted the only call sites reaching the real send path, and no gate covered `send_campaign_emails` | `grep -rn "_compose_for_recipient" apps/api tests` → def `campaign_sender.py:175`, production call **`:377`** (+ comment-only mentions in `agents/segmenter.py:122`, `agents/campaign_planner.py:139`); `grep -rn "_compose_generic" apps/api tests` → def `:160`, calls **`:196`/`:197`** only. Plan now carries C1g (`:377`, line 227) and C1h (`:196`/`:197`, line 231), re-words C1 to "eight explicit sub-steps (C1a–C1h)" (line 193), splits AC-2a/AC-2b (lines 341-342), adds `tests/integration/test_campaign_send_booking_link.py` to Blast Radius (line 113) and a dedicated Verification Evidence row (line 359) | FIXED — enumeration is now EXACT against live source and a send-path gate exists (mechanism needs correction — see M-1) |
| N-9 (CONCERN) | Append-only signature rule absent | Plan lines 196-205 mandate END placement in every signature and END of the `:248` select, with the measured rationale (`site_row[0..3]` consumed positionally at `:253/:256/:257/:258`) and the three positional caller files named | APPLIED (incomplete for the select half — see M-2) |
| N-10 (CONCERN) | Entry Gate understated the dirty-tree coupling | Entry Gate lines 74-85 now state both files are dirty, require a pre-edit `git diff --stat` recorded in the phase report, and forbid `git stash / checkout -- / restore / revert / rebase` by name | APPLIED (figures now stale — see M-4) |
| N-11 (CONCERN) | B1 validator narrower than `_URL_RE` | `link_decorator.py:79` is EXACTLY `_URL_RE = re.compile(r'https?://[^\s"\'<>)]+')`. B1 (lines 176-181) now rejects `)` and whitespace with the "must MATCH the decorator's terminator set" rationale; AC-10 (line 350) carries it | APPLIED — verified character-for-character |
| N-12 (CONCERN) | AC-4 gate did not state `.format()` requirements | `campaign_planner.py:197-209` requires exactly 9 kwargs: `segment_name`, `segment_description`, `visitor_count`, `characteristics_json`, `channels`, `messaging_angle`, `visitor_profiles_json`, `segment_id`, `connected_accounts_info`. C3b (lines 255-262) names all 9, in the same order. `_GENERIC_COPY_NOTE` confirmed at `:123-131` with its own `{{{{first_name}}}}` escaping, correctly declared out of scope | APPLIED |
| gap 8 | 5-heads parser artifact could re-raise as a false FAIL | Test Infra Notes lines 413-419 record it, name the multi-line-tuple cause, and make `alembic heads` the only authority | APPLIED |
| N-13 (contract-only) | `_personalize` caller list | Superseded; corrected in E3 below (live grep returns NINE lines, not seven) | CORRECTED |

Anchors re-verified EXACT against live source this session: `campaign_sender.py:71` (`_LEFTOVER_TOKEN`),
`:84-94` (`_tidy`), `:95` (`_personalize` def), `:113-118` (both-brace replaces), `:121` (`return _tidy(out)`),
`:160`/`:172` (`_compose_generic`), `:175`/`:377` (`_compose_for_recipient`), `:196`/`:197`, `:201`,
`:248` + positional consumption `:253/:256/:257/:258`, `:419` (`decorate_links`), `:431`
(`_unsubscribe_footer(iv.email)`); `campaigns.py:37,477,482` (`_personalize`), `:38,559,607,658,862`
(`send_campaign_emails`), `:469`/`:470` (preview `select(Site.name)` + `.scalar_one_or_none() or "Beam"`);
`campaign_planner.py:76` (`{{{{first_name}}}}` in the JSON `"body"` line), `:123-131`, `:197-209`;
`link_decorator.py:79`, `:88`, privacy docstring `:101-103`; `schemas/sites.py` (`SiteOut` explicit-field
list + `field_validator` idiom; `SiteUpdate` uniform optional block); `routers/sites.py` `update_site`
uniform `if body.X is not None` chain.

Infra re-confirmed live: `lsof -nP -iTCP -sTCP:LISTEN` shows BOTH `:5433` and `:6379` LISTENING.
`git ls-files --error-unmatch` still exits non-zero for BOTH `d7e2b4c81f93_add_waitlist_application_fields.py`
and `c5e1a9b73d20_add_site_profile.py` — the A2b STOP rule remains correctly armed and WILL fire.

### Net Gate Derivation

| Layer 1 dimensions | Status |
|---|---|
| Infra fit | PASS |
| Test coverage | CONCERN |
| Breaking changes | CONCERN |
| Security surface | PASS |

| Layer 2 sections | Status |
|---|---|
| Step A — Schema | PASS |
| Step B — API + schema surface | PASS |
| Step C — `{{booking_link}}` token | CONCERN |
| Step D — "Demo booked" goal preset | PASS |
| Step E — Attribution hole documentation | PASS |
| Step F — Regression safety | CONCERN |

**Totals: 0 FAILs / 4 CONCERNs / 6 PASSes**

**→ Net Gate: CONDITIONAL**

Terminal PASS is not available: the web/UI half (B3, D3) is proven by Known-Gap alone, which per the
vacuous-green ban cannot silently carry a behavior to PASS. It is named as a residual below.

### CONCERNs (new this cycle)

| # | Finding | Severity | Proposed fix |
|---|---|---|---|
| M-1 | **The AC-2b gate names a mock mechanism that does not exist, and misses in-repo prior art that already does exactly this.** `grep -n "mock_external_apis\|MOCK" apps/api/services/email_sender.py` → **zero hits**. `EmailSender.send` (`email_sender.py:104-133`) unconditionally POSTs to `SENDGRID_API_URL` via `httpx` — no mock branch, no missing-key guard. `MOCK_EXTERNAL_APIS=true` is therefore a **no-op on this exact path**, and the plan's "captures the rendered outbound body from the mocked sender" (line 359) has no referent. A test written literally captures nothing: the POST raises → caught at `campaign_sender.py:461` → `summary["failed"] += 1` → `summary["sent"] == 0`. Prior art exists and is exact: `tests/unit/test_gmail_sender_decoration_parity.py:47-121` (`_run_send`) drives the REAL `send_campaign_emails` end-to-end and captures the body via `monkeypatch.setattr(campaign_sender, "EmailSender", MagicMock(return_value=sendgrid_instance))` with `captured["body"] = kwargs["body_html"]`, also patching `send_via_gmail`, `resolve_sender_for_site`, `is_email_suppressed`, `check_and_reserve_email`. It is `pytest.mark.unit` and needs NO Postgres/Redis. | CONCERN | Apply to plan (Verification Evidence AC-2b row + C1g): name `tests/unit/test_gmail_sender_decoration_parity.py::_run_send` as the template; state the capture mechanism explicitly (`monkeypatch.setattr(campaign_sender, "EmailSender", ...)`, assert on `kwargs["body_html"]`); drop the `MOCK_EXTERNAL_APIS=true` clause or re-justify it. Optionally re-tier AC-2b from Hybrid to Fully-Automated unit — the prior art proves the infra preconditions are unnecessary. |
| M-2 | **The append-only rule protects positional CALL sites but not mocked RETURN-tuple arity; two existing tests hard-code the `site_row` 4-tuple and break at C1a.** `grep -rn "first.return_value = (" tests/` returns EXACTLY two files, both driving `send_campaign_emails`: `tests/unit/test_gmail_sender_decoration_parity.py:84` = `(_SITE_URL, "Site", "Owner", "owner@site.example")` and `tests/unit/test_agent_origin_exclusion.py:119` = `("https://site.example", "Site", "Owner", "o@e.com")`. Appending `Site.booking_url` LAST (correct, and what the plan mandates) makes `site_row[4]` → `IndexError: tuple index out of range` against both real 4-tuples. The plan's entire append-only rationale is "inserting mid-tuple silently rebinds" — appending IS safe there — so an execute-agent that internalized "append-last is safe" hits an unexplained red on `test_agent_origin_exclusion.py`, described in `process/context/all-context.md` as *"the program's highest-priority guardrail"*. Wrong-fix hazard: defensive indexing in production (`site_row[4] if len(site_row) > 4`) would mask a genuinely mis-ordered select. N-9's remedy named three files — all `_compose_for_recipient` callers; the **select half of the rule names zero files**. | CONCERN | Apply to plan (C1a + the append-only rule block, lines 196-205): add a second bullet — "appending a column changes the returned row's ARITY; two tests hard-code the 4-tuple: `tests/unit/test_gmail_sender_decoration_parity.py:84` and `tests/unit/test_agent_origin_exclusion.py:119`. Extend BOTH fixture tuples to 5 elements. Do NOT add defensive length checks in production code." |
| M-3 | **`_tidy` post-processes the SUBSTITUTED value, so the booking URL itself passes through `_LEFTOVER_HINT`.** `_personalize` ends `return _tidy(out)` (`campaign_sender.py:121`) — `_tidy` runs AFTER substitution, not before. `_tidy` (`:84-94`) applies `_LEFTOVER_HINT = re.compile(r"\[[a-z][^\]]*\]")`, which DELETES any lowercase-led `[...]` span, plus `_HOLLOW_PARENS` and whitespace/punctuation collapse. B1's reject set is deliberately coupled to `_URL_RE`'s terminator set (`< > " ' )` + whitespace) and therefore does NOT cover `[`/`]`. A booking URL containing `/[team]` would be silently mangled in outbound copy. The plan treats `_tidy`/`_LEFTOVER_TOKEN` purely as a stripper of UNRESOLVED tokens (C2, AC-3); nothing asserts the RESOLVED value survives intact. Low probability on real Calendly/Cal.com URLs; near-zero cost to close. | CONCERN | Apply to plan (C2 + AC-3): add one unit case asserting `_personalize` returns the booking URL **byte-for-byte** for a URL containing `[`, `(`, and a trailing `.` — a generic assertion that catches any `_tidy` mangling class, better than enumerating characters. Optionally extend B1 to reject `[`/`]`, noting the rationale is `_LEFTOVER_HINT`, distinct from the `_URL_RE` coupling. |
| M-4 | **Hard-coded measurement snapshots have already drifted within one session, yet the plan presents them as fixed facts in four places.** Measured live now vs plan text: `git diff --stat` → `sites.py \| 197` and **220 insertions / 1 deletion** (plan says `185` / `208 insertions`); `update_site` at **:388** in the worktree (plan/prior contract say `:383`; HEAD is `:330`). `pytest tests/unit -q --collect-only` → **2802** (plan says 2799); `-m unit` → **1840** collected / 962 deselected (plan says 1837 / 962). The concurrent site-analysis session is still actively editing. The plan already mandates in-session re-measurement (F2) — the risk is an execute-agent reading a mismatch as an anomaly or a regression signal rather than expected drift. | CONCERN | Apply to plan (Entry Gate, F2, Test Infra Notes, Exit Gate comment): label every such figure "snapshot 16-08-26, expected to drift — the in-session re-measurement is authoritative; a mismatch is EXPECTED, not a blocker." Refresh the four numbers to 197 / 220 / :388 / 2802 / 1840 or replace them with the label. |

### Dimension findings

- Infra fit: PASS — PG `:5433` and Redis `:6379` confirmed LISTENING this session; `.venv/bin/python3.11` resolves; the A2b untracked-parent STOP rule verified still-armed (both `d7e2b4c81f93` and `c5e1a9b73d20` exit non-zero under `git ls-files --error-unmatch`). Every Hybrid gate is RUNNABLE and must NOT be deferred as environment-blocked. M-1 additionally shows the AC-2b gate needs no infra at all.
- Test coverage: CONCERN — the cycle-3 send-path gate now EXISTS (closing prior FAIL N-8), but its stated mechanism does not (M-1: no mock branch in `EmailSender`), two existing fixtures break on the select arity change without being named (M-2), and no gate asserts the resolved URL survives `_tidy` (M-3). The UNMARKED-lane decision is re-validated and load-bearing: both M-2 files are `pytest.mark.unit` so both lanes catch them, while `test_personalize.py` carries no marker at all.
- Breaking changes: CONCERN — the `send_campaign_emails` caller-set invariant is EXACT against live grep (`campaign_sender.py:201` + `campaigns.py:38,559,607,658,862`). The `_compose_for_recipient` / `_compose_generic` / `_personalize` signature changes are now fully enumerated and the append-only rule is correct for CALL sites. New: the `:248` select arity change breaks two mocked RETURN tuples that no plan section names (M-2).
- Security surface: PASS — no auth/billing/secret surface touched; tenancy preserved (`verify_site_access` at `update_site`, `Site.user_id == user.id`); never-auto-send verified by live grep; B1's reject set now matches `link_decorator._URL_RE`'s terminator set character-for-character (`:79`, verified), closing prior N-11. Subdomain `_bid` residual remains ACCEPTED as documented (Public Contracts lines 144-150) and is NOT re-litigated. M-3 is a copy-integrity concern, not an injection surface — the HTML-injection reject set is unaffected.
- Step A — Schema: PASS — `booking_url` mirrors `leadpipe_pixel_id` (`site.py:111`); A2/A2b/A3/A4 sequence correct; single-head + parser-artifact note recorded; untracked-parent STOP rule verified live. Operator-gated on the site-analysis tree commit (locked/accepted, not re-litigated).
- Step B — API + schema surface: PASS — `SiteUpdate` uses the `field_validator` idiom so B1 fits the file; `SiteOut` is an explicit-field model so an additive `booking_url: str | None = None` is safe; `update_site` is a uniform `if body.X is not None` chain (re-verified in the DRIFTED worktree at `:388`), so B2 is mechanical.
- Step C — `{{booking_link}}` token: CONCERN (was FAIL) — C1a–C1h are now EXACT and complete against live source; `:377`, `:196`, `:197` all verified. Residual: M-1 (gate mechanism), M-2 (fixture arity), M-3 (`_tidy` post-processing). Still the highest-risk edit in the phase.
- Step D — "Demo booked" goal preset: PASS — unchanged from cycle 3; the preset body was executed against the real validator chain in a prior cycle and is VALID; `routers/outcomes.py` correctly read-only.
- Step E — Attribution hole documentation: PASS — unchanged; `test_link_decoration.py` 8/8 with a non-vacuous same-host control; `decorate_links` privacy docstring verified at `:101-103`.
- Step F — Regression safety: CONCERN — F1's caller-set invariant is EXACT; F3's `pytestmark` rule is correct and necessary; the UNMARKED-lane choice is re-validated (962 still deselected). Residual: M-4, the hard-coded 2799/1837/185/208/:383 snapshots have already drifted to 2802/1840/197/220/:388.

### Test Gates

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 | `booking_url` persists and round-trips through PATCH/GET `/sites/{site_id}` | Hybrid | `.venv/bin/python3.11 -m pytest tests/integration/test_booking_goal_preset.py -m integration -q` — precondition `lsof -nP -iTCP -sTCP:LISTEN \| grep -E '5433\|6379'` shows BOTH (confirmed present this session); must PATCH a real non-null value and re-GET it (a null-only assertion is vacuous) | B |
| AC-2a | `{{booking_link}}` resolves in `_personalize`, `_compose_generic`, `_compose_for_recipient`, and the `[TEST]` preview path | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_campaign_sender_tokens.py -q` — new file MUST carry `pytestmark = pytest.mark.unit` (F3); fixture `booking_url="https://cal.com/acme"` | B |
| AC-2b | `send_campaign_emails` itself delivers the booking URL into the outbound body HTML (catches a missed `:377`) | Hybrid (re-tier to Fully-Automated unit is RECOMMENDED — see M-1) | `.venv/bin/python3.11 -m pytest tests/integration/test_campaign_send_booking_link.py -m integration -q`. **Mechanism correction (M-1): `EmailSender` has NO mock branch — `MOCK_EXTERNAL_APIS=true` does nothing here.** Capture the body by `monkeypatch.setattr(campaign_sender, "EmailSender", MagicMock(return_value=fake))` and asserting on `kwargs["body_html"]`, patching `send_via_gmail`, `resolve_sender_for_site`, `is_email_suppressed`, `check_and_reserve_email` — template: `tests/unit/test_gmail_sender_decoration_parity.py:47-121`. Non-vacuous guard: assert `summary["sent"] == 1` BEFORE asserting on the body | B |
| AC-3 | With `booking_url` unset the token renders empty — never `"None"`, never `href=""` | Fully-Automated | Same suite; cases: mid-sentence, bare-URL, inside `<a href="…">`, single-brace `{booking_link}`. **Add (M-3): a byte-for-byte round-trip case** — a URL containing `[`, `(`, and a trailing `.` must emerge from `_personalize` unmodified (`_tidy` runs AFTER substitution at `:121`) | B |
| AC-4 | Planner prompt documents `{{booking_link}}` with correct `{{{{ }}}}` escaping | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_campaign_planner_prompt.py -q` (NEW file, marked `unit`) — assert `CAMPAIGN_PLANNING_PROMPT.format(**all 9 kwargs)` succeeds AND the output contains literal `{{booking_link}}`. The 9 kwargs re-verified at `campaign_planner.py:197-209`. Never `-k campaign_planner` (collects 0) | B |
| AC-5 | `ConversionGoal(goal_type="url_match", match_type="prefix", pattern="/thanks")` matches landing path `/thanks/demo` | Hybrid | `.venv/bin/python3.11 -m pytest tests/integration/test_booking_goal_preset.py -m integration -q` — proven provable in cycle 3 by direct execution of `validate_goal_pattern` + `matches_goal`; must also assert a full `https://…` pattern is REJECTED | B |
| AC-6 | Saving `booking_url` creates zero `ConversionGoal` rows | Hybrid | Same integration file — PATCH `booking_url`, assert `count(*)` on `conversion_goals` is unchanged | B |
| AC-7 | `decorate_links` leaves a third-party booking host undecorated while decorating a same-host control | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_link_decoration.py -q` — EXISTING file, 8/8 verified passing, non-vacuous control present; E1 adds ONE booking-URL-shaped case to that same file. Do NOT create a duplicate file | A (existing) + B (extension) |
| AC-8 | The migration applies and reverses against local PG, chained off a COMMITTED parent | Hybrid | `git ls-files --error-unmatch apps/api/migrations/versions/<parent>*.py` exits 0 — **still exits non-zero for both `d7e2b4c81f93` and `c5e1a9b73d20` as of this validation** — THEN `DATABASE_URL=postgresql+asyncpg://…@localhost:5433/… .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads`, `upgrade head` → `downgrade -1` → `upgrade head`. NEVER a bare alembic command — repo `.env` points at Supabase PROD | C (operator-gated on the site-analysis tree commit) |
| AC-9 | No new path reaches `send_campaign_emails` | Fully-Automated | `grep -rn "send_campaign_emails" apps/api --include="*.py"` yields exactly `campaign_sender.py:201` + `campaigns.py:38,559,607,658,862` — **re-verified EXACT against live source this session** | A (baseline verified) + B (re-run post-edit) |
| AC-10 | `booking_url` rejects non-`http(s)` schemes, `<>"'`, `)`, whitespace, and >500 chars | Fully-Automated | New cases in the marked token/schema unit file — `javascript:alert(1)`, `https://x.com/"><script>`, a value containing `)`, a value containing a space, 501-char string. Reject set re-verified to match `link_decorator._URL_RE` (`:79`) exactly | B |
| regression (signature) | The `_compose_for_recipient` signature change does not break its three existing positional callers | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -q` (UNMARKED) — `test_contact_importer.py:124`, `test_outbound_identity_gate.py:101,124`, `test_personalize.py` are ALL unmarked and would be deselected by `-m unit` | B |
| regression (select arity) | The `:248` select arity change does not break the two tests that mock `site_row` as a 4-tuple | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_gmail_sender_decoration_parity.py tests/unit/test_agent_origin_exclusion.py -q` — **NEW gate this cycle (M-2)**; both fixtures must be extended to 5-tuples, NOT worked around with defensive length checks in production code | B |
| whole-phase | No regression vs this session's measured baseline | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -q` (UNMARKED — **2802** collected as of 16-08-26; expect drift, re-measure in-session) AND `.venv/bin/python3.11 -m pytest tests/ -m integration -q` | B |
| AC-2a / AC-9 (human) | A human sees the rendered booking link and approval is still required before send | Agent-Probe | Trigger the `[TEST]` preview-send endpoint (`campaigns.py:477/482`) for a campaign whose site has `booking_url` set; confirm the preview contains the resolved URL and campaign status is unchanged (still `draft`). NOT the dashboard draft view — that renders the raw stored template | C |
| known-gap | Real Calendly/Cal.com redirect actually lands on the customer's pixel'd thank-you page | Known-Gap (residual) | — no automated coverage; depends on live third-party provider config | D |
| known-gap | Web/UI half (B3 site-settings field, D3 "Track demo bookings" affordance) | Known-Gap (residual) | — `apps/web` has no Clerk auth-harness for authenticated dashboard e2e in this repo | D |

gap-resolution legend: A — proven now; B — gate added by this plan's checklist; C — deferred to a
named later step / operator gate; D — backlog test-building stub (named residual).

C-4 reconciliation: the `strategy:` column carries ONLY Fully-Automated / Hybrid / Agent-Probe.
Known-Gap is a named residual row (gap-resolution D), never a strategy that proves a behavior.

Failing stub (AC-2b, the gate this cycle's supplement added):

```
test("send_campaign_emails delivers the site booking_url into the outbound body", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: send-path booking link delivery")
})
```

Failing stub (regression — select arity, M-2):

```
test("site_row 4-tuple fixtures survive the booking_url select append", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: site_row arity regression")
})
```

### Gap resolution options

| Gap | Resolution options |
|---|---|
| **G1 (M-1) — AC-2b's stated capture mechanism does not exist** | **A) Re-tier AC-2b to a Fully-Automated unit gate (recommended, ~30 min):** copy `tests/unit/test_gmail_sender_decoration_parity.py::_run_send` verbatim as the harness, set `site_result.first.return_value` to a 5-tuple with a `booking_url`, put `{{booking_link}}` in `_BODY_TPL`, assert the captured `body_html` contains the URL. Proven pattern, zero infra preconditions, still exercises the real `:377`. **B) Keep it as an integration test (~45 min):** same monkeypatch of `campaign_sender.EmailSender`, but against a real seeded DB + Redis; strictly more setup for the same proof. **C) Accept as known-gap — NOT acceptable:** this is the feature's primary path. **D) Backlog stub — NOT acceptable** for the same reason. |
| **G2 (M-2) — two fixtures hard-code the `site_row` 4-tuple** | **A) Extend both fixture tuples to 5 elements (recommended, ~5 min)** — `test_gmail_sender_decoration_parity.py:84` and `test_agent_origin_exclusion.py:119`. **B)** Name them in C1a so the execute-agent expects the red instead of debugging it. **C)** Accept — the unmarked lane fails loudly, but on the repo's highest-priority guardrail test, which invites the wrong fix. **D)** n/a. Do A **and** B. |
| **G3 (M-3) — `_tidy` runs after substitution** | **A) One byte-for-byte unit assertion (recommended, ~5 min).** **B)** Extend B1 to reject `[`/`]`, noting the rationale is `_LEFTOVER_HINT`, not `_URL_RE`. **C)** Accept as known-gap — defensible (real booking URLs rarely contain `[`), but the assertion is one line. **D)** n/a. |
| **G4 (M-4) — stale numeric snapshots** | **A)** n/a (not a test gap). **B)** Refresh the four figures and label them as drifting snapshots. **C) Accept** — F2 already mandates in-session re-measurement. **D)** n/a. Recommend B. |
| **G5 — live Calendly/Cal.com redirect chain** | **A)** Impossible without a live provider account. **B)** n/a. **C) Accept as known-gap** — recommended; `needs-live-provider`. **D)** Covered by backlog note `third-party-link-attribution_NOTE_16-08-26.md` (E3). |
| **G6 — web/UI half (B3, D3)** | **A)** Build a Clerk Playwright auth harness — out of this phase's scope. **B)** n/a. **C) Accept as known-gap** — recommended, consistent with every other plan in this repo. **D)** Existing backlog note `linkedin-onboarding-web-e2e-env-gap_NOTE_26-07-26.md` tracks the same missing harness; add a cross-reference. |

Legacy line form (for existing validate-contract consumers):
- Token rendering (unit): `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_campaign_sender_tokens.py -q` (precondition: file marked `pytest.mark.unit`; fixture `booking_url` non-null)
- Token on the real send path: `Hybrid: .venv/bin/python3.11 -m pytest tests/integration/test_campaign_send_booking_link.py -m integration -q` (mechanism: monkeypatch `campaign_sender.EmailSender`; `MOCK_EXTERNAL_APIS` is a no-op here — M-1)
- Select-arity regression: `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_gmail_sender_decoration_parity.py tests/unit/test_agent_origin_exclusion.py -q`
- Third-party non-decoration: `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_link_decoration.py -q` (EXISTING file, 8/8 verified passing; extend, do not duplicate)
- Planner prompt escaping: `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_campaign_planner_prompt.py -q` (new file; pass all 9 `.format()` kwargs)
- Goal preset + site persistence: `Hybrid: .venv/bin/python3.11 -m pytest tests/integration/test_booking_goal_preset.py -m integration -q` + precondition `lsof` shows both `:5433` and `:6379`
- Migration round-trip: `Hybrid: DATABASE_URL=<localhost:5433> alembic upgrade head / downgrade -1 / upgrade head` + precondition COMMITTED parent revision (currently unmet — both parents untracked)
- Never-auto-send: `Fully-automated: grep -rn "send_campaign_emails" apps/api --include="*.py"` caller-set invariant (baseline verified exact)
- Whole-phase regression: `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit -q` (UNMARKED lane — 2802 as of 16-08-26, expect drift)
- Human-visible draft + approval gate: `Agent-probe: [TEST] preview send, campaign status unchanged`
- Live provider redirect: `known-gap: documented — needs-live-provider`
- Web/UI half: `known-gap: documented — no Clerk auth-harness`

### Plan updates required to reach PASS

| # | What changes | Where in plan | Why |
|---|---|---|---|
| R1 | AC-2b row: name `tests/unit/test_gmail_sender_decoration_parity.py:47-121` (`_run_send`) as the template; state the capture mechanism (`monkeypatch.setattr(campaign_sender, "EmailSender", ...)`, assert `kwargs["body_html"]`); drop or re-justify `MOCK_EXTERNAL_APIS=true` (no mock branch exists in `EmailSender`); add the `summary["sent"] == 1` non-vacuity guard. Consider re-tiering to a Fully-Automated unit gate. | Verification Evidence (line 359), AC-2b (line 342), C1g | M-1 |
| R2 | Add to the append-only rule block: appending a column changes the returned row's ARITY. Name `tests/unit/test_gmail_sender_decoration_parity.py:84` and `tests/unit/test_agent_origin_exclusion.py:119` (the only two `site_row` 4-tuple mocks in the repo); require extending BOTH to 5-tuples; forbid defensive length checks in production code. | Implementation Checklist — Step C (lines 196-205), C1a | M-2 |
| R3 | Add a byte-for-byte assertion to C2/AC-3: `_personalize` must return the booking URL unmodified for a URL containing `[`, `(`, and a trailing `.` — `_tidy` runs AFTER substitution (`campaign_sender.py:121`) and `_LEFTOVER_HINT` (`:76`) deletes lowercase-led `[...]` spans. | C2, AC-3 | M-3 |
| R4 | Label the drifting figures as snapshots and refresh them: `sites.py \| 197`, 220 insertions / 1 deletion, `update_site` at `:388` (HEAD `:330`); unit collection 2802, `-m unit` 1840 / 962 deselected. State that a mismatch at EXECUTE time is EXPECTED, not a blocker. | Entry Gate, F2, Test Infra Notes, Exit Gate comment | M-4 |

### Execute-agent instructions (carry forward)

| # | Instruction | Trigger condition |
|---|---|---|
| E1 | Before creating the migration: run `alembic heads` with `DATABASE_URL` pinned to `localhost:5433`, then `git ls-files --error-unmatch` the parent revision file. Both `d7e2b4c81f93` and `c5e1a9b73d20` were UNTRACKED when this contract was written — expect a non-zero exit. If untracked, STOP and report; do not chain, and do not chain off an older tracked revision (that creates a second head). | Step A entry |
| E2 | Never run a bare alembic command anywhere in this phase. Repo `.env` `DATABASE_URL` points at Supabase PROD and `migrations/env.py` has no local-host guard. | Any alembic invocation |
| E3 | When changing `_personalize`'s signature, update BOTH `apps/api/routers/campaigns.py:477` and `:482` in the same edit. Verify with `grep -rn "_personalize" apps/api --include="*.py"`. The full expected output is **NINE** lines (the prior contract said seven — corrected): `campaigns.py:37,477,482` + `campaign_sender.py:95` (def), `:166` (docstring), `:172` (call), `:187` (docstring), `:193`, `:194`. Do not treat the two docstring lines as unexpected. | Step C entry |
| E4 | Add `Site.booking_url` **LAST** in the `select(Site.url, Site.name, User.full_name, User.email)` at `campaign_sender.py:248` — it becomes `site_row[4]`. `site_row[0..3]` are consumed positionally at `:253/:256/:257/:258`; inserting mid-list silently rebinds `site_name`, `sender_name`, and `owner_email`. | Step C entry |
| E5 | **The append changes the row's ARITY (M-2).** Two tests hard-code the 4-tuple and will raise `IndexError`: `tests/unit/test_gmail_sender_decoration_parity.py:84` and `tests/unit/test_agent_origin_exclusion.py:119`. Extend BOTH to 5-tuples in the same edit. Do NOT add a length check in production code — that would mask a mis-ordered select. `test_agent_origin_exclusion.py` is the repo's highest-priority guardrail test; a red there is expected from this edit and must be fixed at the fixture, never by weakening the assertion. | Step C entry |
| E6 | **Thread the value all the way to the send path.** After `:248`, pass `booking_url` at the `_compose_for_recipient` call at `campaign_sender.py:377`, and forward it into both `_compose_generic` calls at `:196`/`:197`. A green unit suite does NOT prove this — every AC-2a gate passes `booking_url` explicitly. | Step C entry |
| E7 | Append `booking_url` at the END of every changed signature with `= None`, or make it keyword-only. Three existing tests call `_compose_for_recipient` with 5–6 positional args: `tests/unit/test_contact_importer.py:124`, `tests/unit/test_outbound_identity_gate.py:101` and `:124`. `tests/unit/test_personalize.py` calls `_personalize` with ≤4 positional args (safe). Re-run all of them after the edit — they are UNMARKED, so only the unmarked lane covers them. | Step C entry |
| E8 | For the `[TEST]` preview (C1e), extend the EXISTING query at `campaigns.py:469` — `select(Site.name)` → `select(Site.name, Site.booking_url)` — and change `:470` from `.scalar_one_or_none() or "Beam"` to a `.first()` + explicit unpack. A two-column select left on `.scalar_one_or_none()` raises at runtime. Do not add a second query. | Step C entry |
| E9 | **For the AC-2b gate: `MOCK_EXTERNAL_APIS=true` does NOT mock the send (M-1).** `EmailSender.send` (`email_sender.py:104-133`) POSTs to SendGrid unconditionally. Capture the outbound body by `monkeypatch.setattr(campaign_sender, "EmailSender", MagicMock(return_value=fake))` and reading `kwargs["body_html"]`; also patch `send_via_gmail`, `resolve_sender_for_site`, `is_email_suppressed`, `check_and_reserve_email`. Copy `tests/unit/test_gmail_sender_decoration_parity.py:47-121`. Assert `summary["sent"] == 1` BEFORE asserting on the body — otherwise a failed send yields an empty capture and a misleading red. | AC-2b gate authoring |
| E10 | `_tidy` runs AFTER substitution (`campaign_sender.py:121`) — assert the resolved booking URL emerges byte-for-byte. `_LEFTOVER_HINT` (`:76`) deletes lowercase-led `[...]` spans from the SUBSTITUTED text (M-3). | Step C entry |
| E11 | Do not add any new call site of `send_campaign_emails`. The caller set must remain exactly `campaign_sender.py:201` + `campaigns.py:38,559,607,658,862`. If the token work appears to require touching `_compose_for_recipient`'s branch structure, STOP — that is the hard safety constraint, not a design tradeoff. | Throughout |
| E12 | Every Hybrid gate is RUNNABLE — PG `:5433` and Redis `:6379` were confirmed LISTENING during this validation. Do not mark any Hybrid gate environment-blocked without re-running the `lsof` check and reporting its actual output. | Any Hybrid gate |
| E13 | Declare `pytestmark = pytest.mark.unit` (or `integration`) at the top of EVERY new test file. This repo does not auto-mark by path; an unmarked file is fully deselected by `-m unit` and pytest exits 5. | Any new test file |
| E14 | Do NOT create `tests/unit/test_link_decorator_third_party.py`. The behavior is already locked by `tests/unit/test_link_decoration.py::TestDecorateLinks::test_third_party_link_not_decorated` (8/8 passing). Extend that file instead. | Step E entry |
| E15 | Measure the regression baseline with the UNMARKED lane (`pytest tests/unit -q`). It read **2802** on 16-08-26 (was 2799 hours earlier) — the number DRIFTS because a concurrent session is editing. Re-measure in-session; a mismatch against any figure written in this plan is EXPECTED, not a regression. The `-m unit` lane deselects 962 including every file that calls the functions this phase changes. | Step F entry |
| E16 | `models/site.py` and `routers/sites.py` carry uncommitted site-analysis changes (`+24` / `+197`, 220 insertions / 1 deletion, `update_site` at `:388` as of this validation — these figures drift). Record `git diff --stat` for both BEFORE the first edit and paste it into the phase report. Never stash, revert, or rebase to "clean" the tree — a prior session lost work that way. | Step A / Step B entry |

### Backlog artifacts

| Artifact | Location | What it tracks |
|---|---|---|
| `third-party-link-attribution_NOTE_16-08-26.md` | `process/features/campaigns-outreach/backlog/` | The non-decoration limit, reframed as a privacy guarantee; candidate v2 routes = provider webhook (existing HMAC endpoint `outcomes.py:421`) and redirect-through-Beam interstitial. Explicitly NOT "decorate third-party links". |
| live-provider redirect gate (residual) | same backlog note | Real Calendly/Cal.com → customer thank-you page → pixel → conversion, end to end. `needs-live-provider`, no automated coverage. |
| unit-marker coverage gap (cross-cutting) | `process/features/campaigns-outreach/backlog/` or a general-plans note | 68 of 160 files in `tests/unit` carry no `unit` marker, so the `-m unit` lane is ~34% blind (962/2802 deselected). Affects every plan in this repo that adopts the marker lane as its regression gate. |
| `EmailSender` has no mock-mode branch (cross-cutting) | `process/features/campaigns-outreach/backlog/` | `apps/api/services/email_sender.py` POSTs to SendGrid unconditionally — `MOCK_EXTERNAL_APIS` is not honored on this path, breaking the repo-wide "every external API must work under MOCK_EXTERNAL_APIS=true" convention in `all-context.md`. Every send-path test must monkeypatch the class. Candidate fix: add a mock short-circuit to `EmailSender.send`. |

Open gaps:
- AC-2b gate mechanism (M-1): the gate EXISTS but its stated mock mechanism does not; must be corrected in the plan before EXECUTE or the execute-agent will improvise it.
- `site_row` arity regression (M-2): two existing fixtures break at C1a and no plan section names them.
- `_tidy` post-processing of the resolved URL (M-3): unasserted.
- Drifting numeric snapshots (M-4): four figures already stale within one session.
- Live Calendly/Cal.com redirect chain end-to-end: known-gap — needs-live-provider, no automated coverage possible in this phase.
- Web/UI half (B3, D3): known-gap — `apps/web` has no Clerk auth-harness for authenticated dashboard e2e.
- Migration Step A: operator-gated — accepted; both parent revisions still untracked as of this validation.
- Subdomain `_bid` residual: ACCEPTED as documented (prior-cycle orchestrator decision, not re-litigated).

What this coverage does NOT prove:
- The AC-2a unit gates prove `_personalize`/compose-branch substitution ONLY when `booking_url` is passed explicitly. They do NOT prove `send_campaign_emails` passes it — that is AC-2b's job, and AC-2b's stated capture mechanism does not currently exist (M-1), so until R1 is applied nothing proves the primary path.
- No gate proves the resolved booking URL survives `_tidy` byte-for-byte (M-3) — `_LEFTOVER_HINT` can delete a `[lowercase…]` span from the substituted value.
- The third-party non-decoration gate proves regex/host behavior for one Calendly-shaped URL. It does NOT prove behavior for URL shorteners or redirect chains. It DOES prove the subdomain case — a booking URL on a subdomain of the customer's own host WILL be decorated with `_bid`. Proven, accepted, documented.
- The B1 validator gate proves rejection of `<>"'`, `)`, whitespace, non-http(s) schemes, and >500 chars — a set now verified to match `link_decorator._URL_RE`'s terminator set exactly. It does NOT cover `[`/`]`, which `_tidy` (not the decorator) can act on.
- The integration goal-preset gate proves row creation and `matches_goal` against a synthetic path. It does NOT prove the pixel fires on the customer's thank-you page, nor that `attribute_visitor` links the conversion back to the campaign — with third-party links undecorated there is no `_tp`, so campaign attribution falls back entirely to the `same_visitor` branch (`conversion_tracker.py:148-169`), which requires a prior clicked touchpoint for that visitor. Untested, and materially weaker than the plan implies.
- The migration gate proves apply/reverse against LOCAL Postgres `:5433` only. It proves nothing about production, and nothing about ordering against the concurrent uncommitted site-analysis / waitlist revisions.
- The never-auto-send grep proves the static caller set. It does NOT prove the approval gate at runtime; only the Agent-Probe touches that.
- The whole-phase unmarked lane proves no regression across the tests collected AT MEASUREMENT TIME (2802 on 16-08-26, drifting). It does not prove anything about the 220 uncommitted lines of concurrent site-analysis work sharing two of this phase's edit targets — an EVL failure may not be attributable to this phase.
- No gate proves the web/UI half (B3, D3).

Gate: CONDITIONAL (0 FAILs; 4 CONCERNs — M-1 AC-2b gate mechanism does not exist, M-2 two `site_row` 4-tuple fixtures break unnamed, M-3 `_tidy` post-processes the resolved URL, M-4 four numeric snapshots already stale. The prior cycle's FAIL (N-8) and all 5 CONCERNs are CONFIRMED FIXED against live source.)
Accepted by: not accepted — vc-validate-agent may not self-accept its own verdict. No user acceptance recorded this session. All four CONCERNs are cheap plan-text edits (R1–R4, est. ~15 min total); recommended route is one more vc-plan-agent PVL-supplement cycle, then re-run PVL from V1. Alternatively the orchestrator/user may explicitly accept M-1..M-4 as documented gaps, in which case EXECUTE may proceed with E9/E5/E10/E15 carrying the corrections.

### Contract Errata (post-EVL)

Recorded 17-08-26 during the EVL fix cycle. The Validate Contract body above is left
UNCHANGED — these are corrections to it, not rewrites.

| # | Contract says | Reality on disk | Correction |
|---|---|---|---|
| E-1 | The AC-2b Hybrid gate runs `tests/integration/test_campaign_send_booking_link.py` (Test Gates table, and repeated in the closing gate list) | That file does not exist. The gate file that exists and passes is `tests/unit/test_campaign_send_booking_link.py` | Read every `tests/integration/test_campaign_send_booking_link.py` occurrence in the contract as `tests/unit/test_campaign_send_booking_link.py`, run WITHOUT `-m integration`. This matches M-1's own re-tier note ("re-tier to Fully-Automated unit is RECOMMENDED") and the Verification Evidence row at line 398, which already names the unit path — the Test Gates table and the closing list simply never absorbed the re-tier. |

No other contract rows are affected. AC-2b's substance (drive `send_campaign_emails`,
assert the booking URL lands in `body_html`, non-vacuity guard on `summary["sent"] == 1`)
is unchanged — only the file path and the tier marker were stale.
