---
name: plan:owned-data-layer
description: "Owned identity data layer — durable company graph (cross-tenant reuse) + SendGrid open/click corroborating signals"
date: 23-07-26
feature: visitors-identity
---

# Owned Identity Data Layer — Plan

**Date**: 23-07-26
**Status**: VERIFIED (24-07-26) — Docker/integration gates closed, archived to `completed/`
**Complexity**: COMPLEX (schema + 2 staged internal phases, single plan artifact — not a phase program)

## Overview

Beam already pays for identity/company lookups once and throws most of the value away (Redis-only
30d cache, no durable rDNS/company store, no use of SendGrid engagement data as a corroborating
signal). This plan makes every dollar/lookup spent a **permanent, cross-tenant asset** instead of a
transient cache hit, and adds a strictly corroborating (never identity-creating) signal source from
existing outbound email engagement. No new consent surface, no new outbound provider spend.

Two staged internal phases in ONE plan (not a phase program — single feature-scoped effort):

- **Phase 1 — Durable company graph + cross-tenant full-profile email reuse**
- **Phase 2 — SendGrid open/click → `identity_signals` corroborating table**

## Acceptance Criteria

1. `company_graph` table exists, is populated write-through on every successful free rDNS
   resolution, and is read before a new rDNS lookup when a fresh (non-stale) row exists for the IP.
2. `company_graph_enabled=False` (default) is byte-identical in behavior to current
   `resolve_company_cached` — proven by regression tests.
3. `_graph_node_by_email` returns full profile fields (not just name) when a cross-tenant email
   match exists, verified by a new unit test.
4. `identity_signals` table exists, receives SendGrid open/click events (ip + useragent) only when
   `identity_signals_enabled=True` and all 4 write gates (datacenter-IP, proxy/VPN, suppression,
   `do_not_resolve`) pass.
5. `corroborate_identity()` is proven (by test) to never independently create or upgrade an
   `IdentifiedVisitor` — corroboration only bumps confidence on an already-matched identity.
6. Existing SendGrid bounce/dropped/spamreport suppression behavior is unchanged (regression test).
7. Existing `test_agent_origin_exclusion.py` stays green unmodified (regression proof the new signal
   path never crosses the agent-exclusion boundary).
8. Both new migrations apply cleanly in the integration test DB, chained after the 3 already-pending
   migrations, with no destructive schema change.

---

## Phase Completion Rules

- A phase is **CODE DONE** when its Implementation Checklist items are implemented and its own unit
  tests pass locally — this is NOT "VERIFIED."
- A phase is **VERIFIED** only after: (a) its Verification Evidence gates all pass (unit +
  integration lanes green), (b) the regression gates for the other phase and pre-existing identity/
  SendGrid tests are confirmed green, and (c) the validate-contract for that phase's EXECUTE pass is
  recorded PASS or explicitly accepted CONDITIONAL.
- Phase 2 may start implementation independently of Phase 1 (no hard code dependency — separate
  table, separate service) but should not be marked VERIFIED before Phase 1 if both are executed in
  the same session, so the combined migration chain is validated together.
- Config flags (`company_graph_enabled`, `identity_signals_enabled`) stay `False` through EXECUTE and
  EVL — flipping either to `True` in any real environment is explicitly OUT OF SCOPE for this plan
  (that is a manual, post-migration-live-apply operator action, matching the `agent_detection_enabled`
  precedent).

---

## Plan Discovery (done before writing this plan)

`find process/features/visitors-identity -type f` returned only the 4 `_GUIDE.md` stub files
(`_GUIDE.md`, `active/_GUIDE.md`, `backlog/_GUIDE.md`, `completed/_GUIDE.md`) — **no existing plan
overlaps this work.** This is a fresh task folder, not a resume.

Related durable context confirmed in code (see `## Grounded Facts` below) — these facts are load-
bearing for the checklist and are cited by exact file:line so EXECUTE does not need to re-derive them.

---

## Grounded Facts (verified in code, 23-07-26)

| Fact | Evidence |
|---|---|
| Raw events purge at 90d; graph tables are durable and untouched by retention | `apps/api/services/retention.py` (raw events only) |
| Free rDNS company resolver + Redis-only 30d cache exists today | `apps/api/services/company_resolver.py` (`resolve_company_cached`, `CACHE_TTL = 30 * 24 * 3600`, `CACHE_PREFIX = "company_ip:"`) |
| Datacenter/proxy classifiers already exist — reuse, don't rebuild | `apps/api/services/company_resolver.py:229 is_proxy_or_vpn(privacy)`, `apps/api/services/company_resolver.py:336 async def is_datacenter_ip(ip)` |
| `beam_identity_graph` unique constraint + PII pattern to copy | `apps/api/models/beam_identity.py` — `BeamIdentityNode`, `uq_beam_identity_fp_email` unique(fingerprint,email), `email_ciphertext`/`email_bidx` (blind index via `pii_crypto.email_hash`/`encrypt_pii`), `full_name_ciphertext` |
| Cross-tenant email backfill point (name-only today) | `apps/api/services/identity_resolver.py:885-913 _graph_node_by_email(email)` — currently selects only `email`, `full_name`, `confidence_score`; needs extension to full profile fields present on `BeamIdentityNode`/new `CompanyGraphNode` |
| Free-first waterfall entry point | `apps/api/services/identity_resolver.py:219-376` (`_check_prior_signals`, svid/email/fingerprint/graph checks) |
| Paid waterfall entry point | `apps/api/services/identity_resolver.py:386-539` — confirmed at VALIDATE: `_resolve_ip_company_parallel` (~line 625) runs PDL + IPinfo concurrently; the resolved `company_domain` is set on `visitor.company_domain` around lines 508-523 — this is the exact hook point for the paid-path `_write_through_company_graph` call |
| Owned-write pattern to copy (upsert with PII dual-write) | `apps/api/services/identity_resolver.py:838-883 _upsert_beam_identity` — `pg_insert(...).on_conflict_do_update(...)`, `encrypt_pii`, `email_hash` |
| Owned-resolution cost ledger + provider classification | `apps/api/services/identity_resolver.py:958- _log_owned_resolution`; `apps/api/services/identity_classification.py` — `OWNED_FREE_PROVIDERS`, `is_owned_resolution`, `identity_level` |
| SendGrid webhook today only handles bounce/dropped/spamreport | `apps/api/routers/webhooks.py` — `_SUPPRESS_EVENTS = {"bounce", "dropped", "spamreport"}`, `_HARD_BOUNCE_TYPES = {"bounce", "blocked"}`, `POST /webhooks/sendgrid`. Confirmed at VALIDATE: handler loops over `events`, filters by `event_type in _SUPPRESS_EVENTS` — a new `elif event_type in {"open","click"}` branch is a clean additive insertion with zero risk of touching the suppress branch. |
| Dedicated rollup-table pattern to copy (site/vendor/token uniqueness, indexes) | `apps/api/models/agent_visit.py` — `AgentVisit`, `__tablename__ = "agent_visits"`, `uq_agent_visits_site_vendor_token`, `idx_agent_visits_site_last_seen` |
| 3 migrations already pending live-apply, in order | `d11b39a6c843` (agent_visits) → `a1c7e4f92b83` (Phase 5 visitor.is_agent_derived / source_agent_visit_id) → `b3f9a1d2c7e5` (ai_referral). Confirmed at VALIDATE by reading each file's `revision`/`down_revision` header: this chain is linear and `b3f9a1d2c7e5` is the current alembic head (nothing else declares it as a `down_revision`) — new migrations in this plan should set `down_revision = "b3f9a1d2c7e5"`, but EXECUTE must re-confirm via `alembic heads` since other work may land first. |
| Migrations dir + naming convention | `apps/api/migrations/versions/*.py`, 12-hex-char revision ids, `env.py` + `alembic.ini` at `apps/api/` |
| Test lanes | `process/context/tests/all-tests.md` — unit: `.venv/bin/python -m pytest tests/unit -m unit -q` (no deps); integration: `.venv/bin/python -m pytest tests/ -m integration -q` (needs `docker compose -f infra/docker-compose.yml up -d postgres redis`) |
| DB conventions | snake_case plural tables, UUID `id`, `created_at`/`updated_at`, FK `{singular}_id` — confirmed across `beam_identity.py` and `agent_visit.py` |
| `BeamIdentityNode` current columns confirmed at VALIDATE | `apps/api/models/beam_identity.py` — no `city`/`region`/`country` columns exist today; the plan's claim these must be added as new nullable columns is correct, not redundant. |
| Suppression list check has a ready-made function | `apps/api/services/suppression.py:29 async def is_email_suppressed(db, email, scope) -> bool` — directly reusable for the Phase 2 write gate, confirmed at VALIDATE. |
| `do_not_resolve` sticky check has **no** standalone reusable helper | `apps/api/services/suppression.py:57-71 _cascade_suppress` contains the ONLY existing email→visitor join (`select(IdentifiedVisitor.site_id, IdentifiedVisitor.visitor_id).where(func.lower(IdentifiedVisitor.email) == norm)`), but it is inlined for a different purpose (mass-update on opt-out), not exposed as a callable read-check. EXECUTE must write this join inline in `identity_signals.py` — see VALIDATE-added checklist item 14. |
| SendGrid sends carry no `custom_args` today | `apps/api/services/email_sender.py` `send()` payload has no `custom_args`/`unique_args`/`tracking_settings` keys at all — confirmed at VALIDATE. This means the webhook cannot currently know which `site_id`/`visitor_id` an open/click event belongs to. See VALIDATE-added checklist items 11-13 and the expanded Known Gap section. |

---

## Out of Scope (explicit)

- `_tp` touchpoint wiring — backlog (`process/features/visitors-identity/backlog/`)
- Retail HEM (Hashed Email Match) data purchase — backlog; re-trigger condition = 90-day production
  plateau in owned-resolution coverage metric after this plan ships
- Auto-send anything — never in scope per brand guardrail
- EU/GDPR expansion — out of scope for this plan
- A cron/background re-validation worker for stale `company_graph` rows (Phase 1 uses lazy
  read-time re-validation only)
- Any change to SendGrid suppression/bounce behavior (Phase 2 only ADDS open/click handling)

---

## Touchpoints

**Phase 1:**
- NEW `apps/api/models/company_graph.py` — `CompanyGraphNode` model
- NEW `apps/api/migrations/versions/{rev}_add_company_graph.py`
- `apps/api/services/company_resolver.py` — write-through: every `resolve_company_cached` L1 miss
  that resolves (free rDNS OR future paid IP→company hit) persists to `company_graph`; add
  read-time staleness re-validation when `last_verified > company_graph_staleness_days`
- `apps/api/services/identity_resolver.py:885-913` (`_graph_node_by_email`) — extend the SELECT +
  return payload from name-only to full profile fields available on the graph node (email,
  full_name, city, region, country, confidence_score — mirroring `_check_beam_identity_network`'s
  richer dict shape at lines 945-953)
- `apps/api/services/identity_classification.py` — read (do not modify unless a new provider label
  is needed for graph-sourced hits; if so, extend `OWNED_FREE_PROVIDERS` set)
- `apps/api/config.py` — add `company_graph_enabled: bool = False`, `company_graph_staleness_days: int = 75`
- NEW `tests/unit/test_company_graph.py`
- NEW `tests/integration/test_company_graph_persistence.py`

**Phase 2:**
- NEW `apps/api/models/identity_signal.py` — `IdentitySignal` model
- NEW `apps/api/migrations/versions/{rev}_add_identity_signals.py` (chains after Phase 1's migration)
- `apps/api/routers/webhooks.py` — extend SendGrid handler: add `open`/`click` event types to a new
  handling branch (separate from `_SUPPRESS_EVENTS`); capture `ip` + `useragent` per event; write
  gates before persisting (see Write Gates below)
- `apps/api/services/identity_signals.py` (NEW service) — `record_signal()`, `decay_confidence()`
  (computed at read time, not stored), `corroborate_identity()` (join-only helper — never creates
  an `IdentifiedVisitor`)
- `apps/api/services/pii_crypto.py` — read only (reuse `encrypt_pii`/`email_hash` for the signal's
  email column, same pattern as `beam_identity_graph`)
- `apps/api/config.py` — add `identity_signals_enabled: bool = False`
- **[VALIDATE-added]** `apps/api/services/email_sender.py` — extend `send()` to accept an optional
  `custom_args: dict[str, str] | None` param and forward it, plus always set explicit
  `tracking_settings` (click/open enable), in the SendGrid payload. Required so the webhook can
  attribute an event to a `site_id`/`visitor_id` — see Known Gap.
- **[VALIDATE-added]** `apps/api/services/campaign_sender.py` — pass
  `custom_args={"site_id": ..., "visitor_id": ...}` at the existing identified-visitor send call site.
- NEW `tests/unit/test_identity_signals.py`
- NEW `tests/unit/test_sendgrid_open_click_webhook.py`
- NEW `tests/integration/test_identity_signals_persistence.py`
- **[VALIDATE-added]** extend existing `tests/unit/test_email_sender_branding.py` with a
  `custom_args`/`tracking_settings` forwarding test (no new file needed).
- Existing `tests/unit/test_agent_origin_exclusion.py` — regression-only, no edits expected (confirms
  the `identity_signals` write path never touches `source_agent_visit_id` / `is_emailable_identity`)

---

## Public Contracts

- `company_graph` table: new durable read surface; internal-only (no new public API endpoint in
  this plan). Consumed by `company_resolver.py` and `identity_resolver.py` only.
- `identity_signals` table: new durable read surface; internal-only. Consumed only by a new
  `corroborate_identity()` helper called from the existing confidence-scoring step in
  `identity_resolver.py`'s waterfall — **never** called as an independent identification path.
- `POST /webhooks/sendgrid`: existing public webhook contract EXTENDED (new event types accepted),
  never narrowed. Existing bounce/dropped/spamreport behavior is unchanged byte-for-byte — this is
  additive only, confirmed by a regression test on the existing suppress path.
- No changes to any dashboard-facing API response shape in this plan (both new tables are backend
  internal state — no UI touchpoint identified; if a future phase wants to surface `company_graph`
  confidence or signal count on the identity card, that is out of scope here).

---

## Blast Radius

- **Risk class:** none of auth/billing/schema-destructive/public-API-breaking/secrets — this is
  additive schema (2 new tables) + 1 additive webhook branch. Migration risk is non-destructive
  (new tables only, no column drops/renames).
- **Files:** 2 new models, 2 new migrations, 1 extended service (`company_resolver.py`), 1 extended
  service (`identity_resolver.py`, ~1 method), 1 new service (`identity_signals.py`), 1 extended
  router (`webhooks.py`), 1 config file (2 new flags), 2 VALIDATE-added extended files
  (`email_sender.py`, `campaign_sender.py`), 6 new test files + 1 VALIDATE-added extended test file.
  ~16 touched/created files total — MEDIUM blast radius (5+ files, no high-risk class present as
  defined in the 7-signal scoring: S1 no, S2 no [no auth/billing/destructive-migration], S6 no, S7
  yes → score ≈ 1-2/7). Schema/data migration is a High-Risk Class per orchestration.md even though
  additive; both new-table migrations get a Hybrid gate (see Verification Evidence) rather than a
  known-gap, satisfying the minimum-tier rule.
- **Cross-tenant surface:** `company_graph` is intentionally a GLOBAL (cross-tenant) read table, same
  posture as `beam_identity_graph` today — no new consent surface since this data was already being
  resolved and spent on per-tenant; this plan only makes the resolution durable and shared, matching
  existing `beam_identity_graph` precedent exactly.

---

## Config Flags (new)

| Flag | Default | Purpose |
|---|---|---|
| `company_graph_enabled` | `False` | Master switch for Phase 1 write-through + read-time reuse. Safe rollout: OFF until migration is live-applied and verified. |
| `company_graph_staleness_days` | `75` | Configurable window (60-90d requested) before a `company_graph` row triggers lazy re-validation at read time. |
| `identity_signals_enabled` | `False` | Master switch for Phase 2 SendGrid open/click capture + corroboration lookup. Safe rollout: OFF until migration is live-applied and verified. |

Both new flags default OFF, matching the existing `agent_detection_enabled` precedent
(`process/context/all-context.md` AI-Agent-Traffic Layer section) — this program does not enable
anything in production by shipping code; a human flips the flag after migrations are live-applied.

---

## Phase 1 — Durable Company Graph + Cross-Tenant Full-Profile Reuse

### Implementation Checklist

1. Add `company_graph_enabled: bool = False` and `company_graph_staleness_days: int = 75` to
   `apps/api/config.py` `Settings` class.
2. Create `apps/api/models/company_graph.py` — `CompanyGraphNode(Base)`:
   - `__tablename__ = "company_graph"`
   - `id: UUID` (primary key, default `uuid.uuid4`)
   - `ip: str | None` (String, indexed) — the resolved IP (nullable if resolved by domain only)
   - `domain: str | None` (String, indexed) — company root domain
   - `company_name: str | None`
   - `source: str` (String — one of `"rdns"`, `"pdl"`, `"ipinfo"`, or future provider names;
     mirrors `source_provider` naming on `BeamIdentityNode`)
   - `confidence: float` (Float, default 0.0)
   - `first_seen: DateTime(timezone=True)` (server_default `func.now()`)
   - `last_verified: DateTime(timezone=True)` (server_default `func.now()`, onupdate `func.now()`)
   - `created_at` / `updated_at` (standard convention, `server_default=func.now()`, onupdate on updated_at)
   - Unique index: `uq_company_graph_ip_source` on `(ip, source)` when `ip` is present — mirrors the
     `uq_beam_identity_fp_email` upsert-key pattern so write-through can use
     `pg_insert(...).on_conflict_do_update(...)` exactly like `_upsert_beam_identity`
   - Secondary index on `domain` for future domain-keyed lookups
3. Create migration `apps/api/migrations/versions/{new_rev}_add_company_graph.py`. Set `down_revision`
   to whichever of the 3 pending migrations (`d11b39a6c843` / `a1c7e4f92b83` / `b3f9a1d2c7e5`) is
   currently the alembic head — confirm via `alembic heads` at EXECUTE time (heads may have advanced
   since this plan was written; do not hardcode without checking). Migration creates the table +
   both indexes only — no data backfill in this migration.
4. Extend `apps/api/services/company_resolver.py`:
   - Add `_write_through_company_graph(db: AsyncSession, ip: str, domain: str, company_name: str | None, source: str, confidence: float) -> None` —
     upsert via `pg_insert(CompanyGraphNode).on_conflict_do_update(...)` on `(ip, source)`, updating
     `company_name`, `confidence`, `last_verified`, `updated_at`. Best-effort: wrap in try/except +
     rollback on failure, log `structlog` keys-only (no PII values — IP is not PII-sensitive per
     existing `agent_visits` precedent logging `ip` directly, but do not log `domain`/`company_name`
     values if a future PII policy tightens this — for now mirror existing IP-logging precedent in
     `geoip.py`/`agent_classifier.py`).
   - Call the write-through function from every successful resolution path inside
     `resolve_company_cached` (both the free rDNS path AND, when `company_graph_enabled=True`, any
     paid PDL/IPinfo IP→company hit surfaced by `identity_resolver.py`'s paid waterfall — the hook
     point is confirmed at VALIDATE: `_resolve_ip_company_parallel` around identity_resolver.py:625,
     with `company_domain` assigned around lines 508-523; add the equivalent write-through call there,
     gated by the same flag).
   - Add `_read_company_graph(db, ip) -> CompanyGraphNode | None`: query by `ip`, order by
     `confidence DESC`, `limit(1)`. If found and `last_verified` is within
     `company_graph_staleness_days`, return immediately (no external call). If stale
     (`last_verified` older than the window), return the stale row anyway BUT set a
     `needs_revalidation: bool` flag on the returned tuple/dataclass so callers can trigger a fresh
     resolve — read-time lazy re-validation, no cron.
   - Gate all new behavior behind `settings.company_graph_enabled` — when `False`, behavior is
     byte-identical to today (Redis-only path unchanged).
5. Extend `apps/api/services/identity_resolver.py:885-913 _graph_node_by_email`:
   - Broaden the SELECT to include all profile columns present on the underlying node (email,
     full_name, city, region, country if those columns exist on `BeamIdentityNode` — confirmed at
     VALIDATE that `city`/`region`/`country` do NOT currently exist on `BeamIdentityNode` and must be
     added as new nullable columns in this same migration for the full-profile-reuse goal).
   - Return the full profile dict (mirroring `_check_beam_identity_network`'s dict shape at lines
     945-953) instead of just `email`/`full_name`/`confidence_score`.
   - Update the caller at line 312 (`node = await self._graph_node_by_email(captured_email)`) to pass
     through the additional fields into `_save_identified`.
6. Add `city`, `region`, `country` nullable columns to `BeamIdentityNode` in the SAME migration as
   step 3 (or a second additive migration chained immediately after, if isolating schema changes per
   table is preferred — EXECUTE decides based on migration hygiene, but both must land before step 5
   is functional).
7. Write `tests/unit/test_company_graph.py` — pure logic: upsert-on-conflict behavior (mocked DB),
   staleness-window calculation, flag-gating (feature OFF → no-op).
8. Write `tests/integration/test_company_graph_persistence.py` — real Postgres: insert, conflict
   update, staleness read-time check, verify existing identity waterfall tests still pass with flag
   OFF (default).

### Phase 1 Exit Criteria

- Migration applies cleanly in integration test DB (not live-applied to any real environment —
  Docker-gated per existing program constraint).
- `company_graph_enabled=False` (default): zero behavior change vs current `resolve_company_cached`.
- `company_graph_enabled=True` (test-only): every successful free rDNS resolution persists a
  `company_graph` row; a second resolve for the same IP within the staleness window reads from
  `company_graph` without a new rDNS lookup.
- `_graph_node_by_email` returns full profile fields when available, still returns `None` gracefully
  when no match (unchanged failure behavior).

---

## Phase 2 — SendGrid Open/Click → `identity_signals`

### Implementation Checklist

1. Add `identity_signals_enabled: bool = False` to `apps/api/config.py`.
2. Create `apps/api/models/identity_signal.py` — `IdentitySignal(Base)`:
   - `__tablename__ = "identity_signals"` (separate table from `beam_identity_graph` — different
     cardinality/lifecycle per approved decision: one row per corroborating event, not per identity)
   - `id: UUID` (primary key)
   - `site_id: str` (FK-shaped, String — matches existing `site_id` typing seen on `BeamIdentityNode`)
   - `ip: str` — the engagement event's IP
   - `email_ciphertext: str | None` (Text) + `email_bidx: str | None` (String, indexed) — same
     PII pattern as `beam_identity_graph` (`pii_crypto.encrypt_pii` / `email_hash`); NEVER store
     plaintext email
   - `signal_type: str` (String — `"sendgrid_open"` | `"sendgrid_click"`)
   - `base_confidence: float` (Float — 0.4-0.5 for open, 0.6 for click per approved decision; set at
     write time, NOT decayed at write time)
   - `created_at: DateTime(timezone=True)` (server_default `func.now()`) — decay is computed at READ
     time from `created_at`, never stored as a mutated column
   - `updated_at: DateTime(timezone=True)` (standard convention, even though signals are
     append-only/immutable post-write — keep for consistency with repo-wide table convention)
   - Index: `idx_identity_signals_ip` on `ip`; index on `email_bidx`
3. Create migration `apps/api/migrations/versions/{new_rev}_add_identity_signals.py`, chained after
   Phase 1's migration (confirm actual head via `alembic heads` at EXECUTE time).
4. Create `apps/api/services/identity_signals.py`:
   - `async def record_signal(db, site_id, ip, email, signal_type) -> None` — write gates FIRST (see
     Write Gates below), then insert. Best-effort try/except + rollback + `structlog` keys-only log
     (never log the email value — log `email_domain` only, matching existing
     `beam_identity_upserted` logging precedent).
   - `def decay_confidence(base_confidence: float, created_at: datetime, now: datetime | None = None) -> float` —
     pure function, computed at read time. Simple linear or exponential decay (EXECUTE picks one
     documented formula, e.g. halve confidence every 30 days) — must be pure/deterministic and unit-
     testable without DB.
   - `async def corroborate_identity(db, ip, email) -> float | None` — join-only helper: looks up
     matching `identity_signals` rows by `ip` AND/OR `email_bidx`, returns a decayed confidence bump
     (or `None` if no signal). **Hard invariant: this function NEVER creates or upgrades an
     `IdentifiedVisitor` on its own — it is called only from inside the existing waterfall's
     confidence-scoring step, after a fingerprint/cookie match has already produced a candidate
     identity.** Enforce this by NOT importing `_save_identified` or any `IdentifiedVisitor` write
     path into `identity_signals.py` at all — the module should have zero write access to
     `IdentifiedVisitor`.
5. Extend `apps/api/routers/webhooks.py` SendGrid handler:
   - Add a new branch (separate from `_SUPPRESS_EVENTS` handling) for `event_type in
     {"open", "click"}` when `settings.identity_signals_enabled` is `True`.
   - Extract `ip` and `useragent` from the event payload (exact field names to be confirmed against
     live SendGrid payload shape — flagged as a known-gap below; write test fixtures with the
     documented SendGrid Event Webhook schema field names `ip` and `useragent`).
   - Call write gates (step 6) before calling `record_signal`.
   - Existing `_SUPPRESS_EVENTS` branch is UNTOUCHED — add the new branch as a separate `if`/`elif`,
     never inside the suppress branch.
6. **Write gates (mandatory on this new write path from day 1):**
   - `is_datacenter_ip(ip)` (from `company_resolver.py:336`) — reject datacenter/CDN IPs (SendGrid's
     own infra, image-proxy opens, etc. — critical because Apple MPP proxy-opens and SendGrid's link
     click-tracking redirect both originate from provider infrastructure, not the recipient)
   - `is_proxy_or_vpn(privacy)` (from `company_resolver.py:229`) — reject when geoip privacy flags
     indicate proxy/VPN
   - Suppression list check — do not record a signal for an email already on `do_not_email`.
     Confirmed at VALIDATE: use `apps/api/services/suppression.py:29 is_email_suppressed(db, email, "do_not_email")` directly.
   - `do_not_resolve` sticky check — if the visitor this email maps to has `do_not_resolve=True`,
     skip recording entirely. **No reusable helper exists for this (confirmed at VALIDATE) — see
     checklist item 14 below for the exact pattern to write inline.**
   - Any gate failure = silent skip (log + no insert), never raise — webhook must always 200 back to
     SendGrid per existing handler convention.
7. Write `tests/unit/test_identity_signals.py` — pure logic: `decay_confidence` formula correctness
   at 0/30/60/90 day marks, `record_signal` write-gate rejection paths (datacenter IP / proxy /
   suppressed / do_not_resolve — all mocked, no DB).
8. Write `tests/unit/test_sendgrid_open_click_webhook.py` — extend existing SendGrid webhook test
   file's fixture patterns: open/click event payloads accepted, existing bounce/dropped/spamreport
   behavior UNCHANGED (explicit regression assertion), flag OFF → open/click events are no-ops.
9. Write `tests/integration/test_identity_signals_persistence.py` — real Postgres: insert with PII
   ciphertext/bidx pattern verified (no plaintext email column), corroboration join lookup by ip and
   by email_bidx, decay applied correctly at read time.
10. Confirm `tests/unit/test_agent_origin_exclusion.py` still passes unmodified — this is the
    program's existing regression guard proving `identity_signals` cannot leak into the agent-
    exclusion boundary (it shouldn't touch that boundary at all, but the test must stay green as
    proof).

### Phase 2 Additional Checklist Items (added at VALIDATE — 23-07-26)

These items resolve a mechanical feasibility gap found during VALIDATE: the plan's original
checklist assumed `site_id`/`visitor_id` would be available on the webhook event payload, but
`apps/api/services/email_sender.py` currently sends no `custom_args` at all (confirmed by reading
the file) — without them, step 5's `IdentitySignal.site_id` (a NOT NULL column) has no reliable
source. These items are REQUIRED for Phase 2 to be functionally complete, not optional polish.

11. Extend `apps/api/services/email_sender.py`'s `send()` signature with
    `custom_args: dict[str, str] | None = None`. When present, add `"custom_args": custom_args` to
    the outbound SendGrid payload dict. ALWAYS set
    `"tracking_settings": {"click_tracking": {"enable": True}, "open_tracking": {"enable": True}}`
    explicitly in the payload — do not rely on SendGrid account/dashboard-level defaults, which
    cannot be verified from this environment (cost-class: needs-live-provider; whether an account-
    level override suppresses tracking regardless of the API payload is accepted as a known-gap —
    see the expanded Known Gap section below).
12. Update the one existing call site in `apps/api/services/campaign_sender.py` (the identified-
    visitor campaign send) to pass `custom_args={"site_id": campaign.site_id, "visitor_id": vid}`.
    Non-campaign sends (waitlist/admin/transactional notifications) pass no `custom_args` — the
    Phase 2 write path only ever activates for events that carry them.
13. In the `webhooks.py` open/click branch (step 5), derive `site_id`/`visitor_id` from the event
    payload's echoed custom_args keys (SendGrid's Event Webhook contract merges `custom_args` back
    as top-level keys on the event object — exact key casing/nesting to confirm against a real
    payload; folded into the existing SendGrid-payload-shape Known Gap, do not treat as a second
    separate unknown). If `site_id` is absent for any reason (event predates this change, or the
    send path that produced it didn't carry custom_args): **SKIP recording — do not guess via a
    reverse email lookup.** A wrong `site_id` write is worse than a missed corroborating signal;
    this matches the plan's existing "any gate failure = silent skip" design philosophy.
14. In `identity_signals.py`, implement the `do_not_resolve` sticky check as an inline query
    mirroring `apps/api/services/suppression.py`'s `_cascade_suppress` email→visitor join
    (`select(IdentifiedVisitor.site_id, IdentifiedVisitor.visitor_id).where(func.lower(IdentifiedVisitor.email) == norm)`,
    see `apps/api/services/suppression.py:57-64`), then check `Visitor.do_not_resolve` for the
    matched `(site_id, visitor_id)` pairs. There is no existing standalone reusable "email→visitor"
    lookup function — do not search for one; write this join directly in `identity_signals.py`.
15. Extend `tests/unit/test_email_sender_branding.py` (existing file, no new file needed) with a
    test asserting `custom_args` and `tracking_settings` are forwarded correctly into the SendGrid
    payload when `send()` is called with `custom_args` set, and that the payload is unchanged
    (backward compatible) when `custom_args` is omitted.

### Phase 2 Exit Criteria

- `identity_signals_enabled=False` (default): SendGrid webhook behavior byte-identical to today.
- `identity_signals_enabled=True` (test-only): open/click events from non-datacenter, non-proxy,
  non-suppressed, non-`do_not_resolve` sources, carrying valid `custom_args`-derived `site_id`,
  persist a signal row with encrypted email, never plaintext. Events missing `site_id` are skipped.
- `corroborate_identity()` never independently produces an `IdentifiedVisitor` — proven by a test
  that calls it in isolation and asserts zero `IdentifiedVisitor` writes.
- Existing bounce/dropped/spamreport suppression tests remain green (regression).

### Known Gap (flagged explicitly for VALIDATE)

**SendGrid open/click payload shape and site attribution are unverified against a live payload.**
The exact field names for `ip` and `useragent` per SendGrid Event Webhook docs are assumed (`ip`,
`useragent`) based on SendGrid's public Event Webhook schema, and the exact shape/casing in which
`custom_args` are echoed back on the event object (added at VALIDATE — checklist items 11-13) is
likewise unverified against a real payload. Both are folded into one known-gap since they are
resolved by the same mitigation path. Additionally:
- Apple Mail Privacy Protection (MPP) proxy-opens will pollute open-event IPs with Apple's proxy
  infrastructure IPs, not the recipient's real IP — the `is_datacenter_ip`/`is_proxy_or_vpn` gates
  should catch most of these, but Apple's MPP proxy ranges may not be classified as "datacenter" by
  the existing ASN-based classifier (untested against Apple's specific ranges).
- Click events may include SendGrid's own click-tracking redirect IP in some configurations rather
  than the true client IP, depending on account tracking settings.
- Whether SendGrid account/dashboard-level tracking settings override the explicit
  `tracking_settings` JSON now being set in the send payload (checklist item 11) cannot be verified
  without a live SendGrid account call — cost-class: needs-live-provider. Per VALIDATE policy this is
  NOT probed; it is accepted as a known-gap.
- This is a HYBRID-tier test (needs a live SendGrid account or the docs-seeker-verified payload
  schema) and is accepted as a known-gap for this plan. Resolution options: (A) write a new hybrid
  test once a live SendGrid sandbox/webhook replay is available — effort ~1-2h; (B) invoke
  `vc-docs-seeker` before EXECUTE to pull SendGrid's exact current Event Webhook JSON schema
  (including the `custom_args` echo shape) and build fixtures from it (cheapest, do this first); (C)
  accept as known-gap with the mitigation that `corroborate_identity` only ever bumps an ALREADY-
  fingerprint-matched identity — even a polluted IP/useragent or missing `site_id` (handled by the
  skip-on-absent rule in checklist item 13) cannot independently create a false identity, bounding
  the blast radius of this gap to "slightly wrong confidence bump" or "a missed signal," never "false
  identification" or "cross-tenant misattribution."

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `test_company_graph.py::test_upsert_on_conflict` | Fully-Automated | Phase 1: write-through persists and updates on repeat IP resolution |
| `test_company_graph.py::test_staleness_window_triggers_revalidation_flag` | Fully-Automated | Phase 1: lazy re-validation at read time when `last_verified` exceeds configured window |
| `test_company_graph.py::test_flag_off_is_noop` | Fully-Automated | Phase 1: `company_graph_enabled=False` default preserves current behavior |
| `test_company_graph_persistence.py::test_real_pg_insert_and_conflict_update` | Hybrid (needs PG+Redis) | Phase 1: durable persistence survives across a resolver call boundary |
| `test_identity_resolver.py` (existing suite, re-run unmodified) | Fully-Automated | Regression: existing free/paid waterfall behavior unchanged |
| `_graph_node_by_email` unit test (new, added to Phase 1 unit file) | Fully-Automated | Phase 1: cross-tenant email backfill returns full profile, not name-only |
| `test_identity_signals.py::test_decay_confidence_formula` | Fully-Automated | Phase 2: confidence decays correctly at read time (0/30/60/90d) |
| `test_identity_signals.py::test_record_signal_rejects_datacenter_ip` | Fully-Automated | Phase 2: write gate — datacenter IP rejected |
| `test_identity_signals.py::test_record_signal_rejects_proxy_vpn` | Fully-Automated | Phase 2: write gate — proxy/VPN rejected |
| `test_identity_signals.py::test_record_signal_rejects_suppressed_email` | Fully-Automated | Phase 2: write gate — suppression list enforced |
| `test_identity_signals.py::test_record_signal_rejects_do_not_resolve` | Fully-Automated | Phase 2: write gate — `do_not_resolve` sticky enforced |
| `test_identity_signals.py::test_corroborate_never_creates_identified_visitor` | Fully-Automated | Phase 2: corroborating-only invariant — never independently creates/upgrades identity |
| `test_sendgrid_open_click_webhook.py::test_existing_suppress_events_unchanged` | Fully-Automated | Regression: bounce/dropped/spamreport behavior byte-identical |
| `test_sendgrid_open_click_webhook.py::test_open_click_flag_off_noop` | Fully-Automated | Phase 2: `identity_signals_enabled=False` default preserves current webhook behavior |
| `test_sendgrid_open_click_webhook.py::test_site_id_from_custom_args_or_skip` (VALIDATE-added) | Fully-Automated | Phase 2: `site_id` derived from echoed `custom_args`; event silently skipped (no insert) when absent |
| `test_email_sender_branding.py::test_custom_args_and_tracking_settings_forwarded` (VALIDATE-added) | Fully-Automated | Phase 2: `custom_args`/`tracking_settings` correctly forwarded; omitted-case stays backward compatible |
| `test_identity_signals_persistence.py::test_pii_pattern_no_plaintext_email` | Hybrid (needs PG+Redis) | Phase 2: PII pattern — never stores plaintext email |
| `test_agent_origin_exclusion.py` (existing, unmodified) | Fully-Automated | Regression: agent-exclusion boundary untouched by new signal path |
| SendGrid live payload shape + custom_args echo shape verification | Agent-Probe (docs-seeker or manual sandbox) | Known-gap: `ip`/`useragent`/`custom_args` field presence and shape per event type — see Known Gap section |
| Alembic migration applies cleanly, chains after 3 pending migrations | Hybrid (needs PG) | Both phases: migration ordering correctness, no destructive schema change |

### Test Gate Commands

```bash
# Unit (no deps) — run first, fast signal
.venv/bin/python -m pytest tests/unit -m unit -q

# Integration (needs docker compose postgres + redis)
docker compose -f infra/docker-compose.yml up -d postgres redis
.venv/bin/python -m pytest tests/ -m integration -q

# Targeted new files only (during EXECUTE, per-section gate)
.venv/bin/python -m pytest tests/unit/test_company_graph.py -q
.venv/bin/python -m pytest tests/unit/test_identity_signals.py -q
.venv/bin/python -m pytest tests/unit/test_sendgrid_open_click_webhook.py -q
.venv/bin/python -m pytest tests/unit/test_email_sender_branding.py -q
.venv/bin/python -m pytest tests/integration/test_company_graph_persistence.py -q
.venv/bin/python -m pytest tests/integration/test_identity_signals_persistence.py -q

# Regression (must stay green, unmodified)
.venv/bin/python -m pytest tests/unit/test_agent_origin_exclusion.py -q
.venv/bin/python -m pytest tests/ -k identity_resolver -m integration -q
```

Migration dry-run (Docker-gated — never run against real/live Postgres per repo constraint; run
only inside the disposable test/integration Postgres container):

```bash
cd apps/api && ../../.venv/bin/alembic heads
cd apps/api && ../../.venv/bin/alembic upgrade head   # against disposable integration container only
```

**VALIDATE-confirmed baselines (run 23-07-26, before any Phase 1/2 code exists):**
- `.venv/bin/python -m pytest tests/unit -m unit -q` → `270 passed, 2 skipped, 554 deselected` (clean baseline)
- `.venv/bin/python -m pytest tests/unit/test_agent_origin_exclusion.py -q` → `18 passed` (regression baseline)

---

## Test Infra Improvement Notes

(none identified yet)

---

## Resume and Execution Handoff

1. **Selected plan file path:** `process/features/visitors-identity/active/owned-data-layer_23-07-26/owned-data-layer_PLAN_23-07-26.md`
2. **Last completed phase or step:** PLAN validated (VALIDATE Gate: PASS, 23-07-26). Neither internal
   phase (1 or 2) has started implementation.
3. **Validate-contract status:** written — see `## Validate Contract` below.
4. **Supporting context files loaded:** `process/context/all-context.md` (AI Layer, business
   guardrails, env var groups), `process/context/tests/all-tests.md` (test lane commands),
   `apps/api/services/company_resolver.py`, `apps/api/services/identity_classification.py`,
   `apps/api/services/identity_resolver.py` (lines 1-60, 200-400, 838-966),
   `apps/api/models/beam_identity.py`, `apps/api/models/agent_visit.py`,
   `apps/api/routers/webhooks.py` (SendGrid handler), `apps/api/services/email_sender.py`,
   `apps/api/services/suppression.py`, `apps/api/migrations/versions/` listing.
5. **Next step for a fresh agent picking up mid-execution:** Run `ENTER EXECUTE MODE` for this plan.
   If EXECUTE has already started, check which of Phase 1 / Phase 2 checklist items (including the
   VALIDATE-added items 11-15 in Phase 2) are complete via git diff against the Touchpoints list
   above, and resume at the first unchecked item. Always confirm `alembic heads` before writing a new
   migration's `down_revision` — the pending-migration chain (`d11b39a6c843` → `a1c7e4f92b83` →
   `b3f9a1d2c7e5`) may have advanced or been live-applied since this plan was written.

---

## Phase Loop Progress

- [x] Phase 1 — Durable company graph + cross-tenant full-profile reuse
  - [x] Step 1: RESEARCH (this plan's grounded facts are the initial research; re-confirm `alembic heads` + `BeamIdentityNode` current columns at EXECUTE time — VALIDATE independently re-confirmed both on 23-07-26)
  - [x] Step 2: INNOVATE (n/a — approach already decided, see task header)
  - [x] Step 3: PLAN-SUPPLEMENT (n/a — RESEARCH re-confirmation at VALIDATE surfaced no drift for Phase 1)
  - [x] Step 4: PVL (validate-contract — Gate: PASS, 23-07-26)
  - [x] Step 5: EXECUTE (commit `54cf384` — migration `f8a2c1d9b3e7`, code-complete)
  - [x] Step 6: EVL (unit gates green — see Closeout below; Hybrid/integration lane deferred, Docker-gated)
  - [x] Step 7: UPDATE PROCESS — archived; context updated; committed
- [x] Phase 2 — SendGrid open/click → identity_signals
  - [x] Step 1: RESEARCH (re-confirm SendGrid payload shape via vc-docs-seeker before EXECUTE — see Known Gap; VALIDATE additionally found and resolved the custom_args/site_id gap, checklist items 11-15)
  - [x] Step 2: INNOVATE (n/a — approach already decided)
  - [x] Step 3: PLAN-SUPPLEMENT (VALIDATE applied a plan-fix supplement directly — see Phase 2 Additional Checklist Items)
  - [x] Step 4: PVL (validate-contract — Gate: PASS, 23-07-26)
  - [x] Step 5: EXECUTE (commit `94852a9` — migration `a3e9f1c7d2b5`, code-complete)
  - [x] Step 6: EVL (unit gates green — see Closeout below; Hybrid/integration lane + SendGrid live-payload known-gap deferred)
  - [x] Step 7: UPDATE PROCESS — archived; context updated; committed

---

## Closeout (UPDATE PROCESS, 23-07-26; promoted to VERIFIED 24-07-26)

**Classification: VERIFIED — code-complete + unit-verified + Hybrid/Docker-gated gates now
independently confirmed green. Archived to `completed/`.**

**Docker-gate closure (EVL final run, 24-07-26 — independent):**
- Migration round-trip clean on the `infra-postgres-1` disposable container: `upgrade head` →
  `downgrade -1` → `upgrade head`, chain confirmed through to head `a9f2c1e7b4d6` (no destructive
  schema change, no data loss on round-trip).
- `tests/integration/test_company_graph.py` — 14/14 passed (double-run for stability; the
  ambient-Redis dependency that caused earlier flakiness was removed — see note below).
- Integration `company_graph` + `identity_signals` combined lane — 5/5 passed.
- Unit regression `test_agent_origin_exclusion.py` — 18/18 passed (agent-exclusion boundary
  unaffected).
- Donor regression `test_company_resolver.py` — 59/59 passed (no regression in the pre-existing
  free rDNS resolver this plan extends).
- 3 test-infra fixes landed in commit `8c7ac6e` (session-`expire_all` fix, AC11 `do_not_resolve`
  integration test, a `get_redis` mock for the unit lane) — see note below on what these fixed vs.
  what they mean for production.

**Test-infra self-poison, not a prod bug:** the original `test_company_graph.py` unit-lane
flakiness was caused by an ambient Redis container (`itemintern-redis-1`) occupying port 6379 in
this sandbox plus a missing `get_redis` mock in the unit test — the unit lane assumed Redis was
unreachable and exercised the "Redis down" branch, but a real (unrelated) container answered on
the default port instead. This is a **test-harness fixture gap**, not a defect in
`company_resolver.py`/`identity_resolver.py`. Production code at commit `54cf384` is
byte-identical to the code now marked VERIFIED — only the test's isolation was insufficient. See
the new backlog note (`post-docker-gate-followups_NOTE_24-07-26.md`) for the durable conftest fix
recommendation.

Original (23-07-26) rationale for keeping active before this promotion, retained for history: per
the vacuous-green ban, AC2b, AC3 (persistence half), AC8, and the identity_signals persistence
gate all had their proving test tier as Hybrid (needs real Postgres) — those gates had never
actually run. The plan was CODE DONE, not VERIFIED per this plan's own `## Phase Completion
Rules`. That gap is now closed as of the 24-07-26 EVL final run above.

**Commits:**
- `54cf384` — `feat(identity): durable company_graph + cross-tenant full-profile reuse` (Phase 1)
- `94852a9` — `feat(identity): identity_signals corroborating edges from SendGrid open/click` (Phase 2)
- `24a0dcd` — `process(visitors-identity): owned-data-layer plan + validate-contract`

**EVL (independent orchestrator confirmation run, 23-07-26):**
- `.venv/bin/python -m pytest tests/unit -q` → **875 passed, 2 skipped** (full `tests/unit/` collection, no marker filter)
- `.venv/bin/python -m pytest tests/unit -m unit -q` → 319 passed, 2 skipped, 556 deselected (marker-scoped subset; baseline at VALIDATE was 270 passed/2 skipped/554 deselected)
- `.venv/bin/python -m pytest tests/unit/test_agent_origin_exclusion.py -q` → **18 passed** (regression baseline held, file unmodified)
- Corroborating-only invariant (`corroborate_identity()` never creates/upgrades `IdentifiedVisitor`) — grep-verified: `apps/api/services/identity_signals.py` imports `IdentifiedVisitor`/`Visitor` for read-only SELECTs only (write-gate + join lookups), no write path imported. Matches the structural invariant required by AC5 and the plan's hard safety constraint.
- Both flags (`company_graph_enabled`, `identity_signals_enabled`) confirmed `False` (default) in `apps/api/config.py` — no real-environment behavior change shipped.
- **Deferred (Docker-gated, not run this session):** `tests/integration/test_company_graph_persistence.py`, `tests/integration/test_identity_signals_persistence.py`, `alembic upgrade head` against a disposable container. See `process/features/visitors-identity/backlog/owned-data-layer-docker-verification_NOTE_23-07-26.md`.
- **Known-gaps (accepted at VALIDATE, unchanged):** SendGrid live open/click payload shape + `custom_args` echo shape unverified against a real payload (Agent-Probe, docs-seeker route not yet run); account-level SendGrid tracking-settings override behavior (needs-live-provider, not probed per policy).

**Docker-verification gap note:** `process/features/visitors-identity/backlog/owned-data-layer-docker-verification_NOTE_23-07-26.md`

**Promoted to VERIFIED and archived 24-07-26.** Docker gate closure evidence above; commits
`54cf384`/`94852a9`/`24a0dcd`/`bd5e18a` (implementation + prior process) plus `8c7ac6e`
(test-infra fixes). Task folder moved `active/` → `completed/` this session. Backlog note
`owned-data-layer-docker-verification_NOTE_23-07-26.md` marked RESOLVED (see note header).

---

## Validate Contract

Status: PASS
Date: 23-07-26
date: 2026-07-23
generated-by: outer-pvl

Parallel strategy: sequential
Rationale: 7-signal score ≈ 1-2/7 (only S7 "5+ files in blast radius" present; no multi-package,
no auth/billing/schema-destructive/public-API-break, no phase-program classification, not
user-requested-depth). Single-plan, single-feature, MEDIUM blast radius — sequential in-session
V1-V7 analysis was appropriate; no parallel agent-team or workflow fan-out was warranted for this
VALIDATE pass.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC1 | `company_graph` populated write-through on free rDNS resolution, read before new lookup when fresh | Fully-Automated | `tests/unit/test_company_graph.py::test_upsert_on_conflict` | A |
| AC1b | Lazy read-time re-validation when row is stale | Fully-Automated | `tests/unit/test_company_graph.py::test_staleness_window_triggers_revalidation_flag` | A |
| AC2 | `company_graph_enabled=False` is byte-identical to current behavior | Fully-Automated | `tests/unit/test_company_graph.py::test_flag_off_is_noop` | A |
| AC2b | Durable persistence survives a real resolver call boundary | Hybrid (PG+Redis) | `tests/integration/test_company_graph_persistence.py::test_real_pg_insert_and_conflict_update` | B |
| AC3 | `_graph_node_by_email` returns full profile fields, not name-only | Fully-Automated | new unit test in Phase 1 unit file (`test_company_graph.py` or `test_identity_resolver.py`) | B |
| AC4 | `identity_signals` receives open/click events only when flag ON + all 4 write gates pass | Fully-Automated | `tests/unit/test_identity_signals.py::test_record_signal_rejects_datacenter_ip` / `_proxy_vpn` / `_suppressed_email` / `_do_not_resolve` | B |
| AC4b | `site_id` correctly derived from custom_args; skipped when absent | Fully-Automated | `tests/unit/test_sendgrid_open_click_webhook.py::test_site_id_from_custom_args_or_skip` (VALIDATE-added) | B |
| AC5 | `corroborate_identity()` never independently creates/upgrades an `IdentifiedVisitor` | Fully-Automated | `tests/unit/test_identity_signals.py::test_corroborate_never_creates_identified_visitor` | B |
| AC6 | Existing bounce/dropped/spamreport suppression unchanged | Fully-Automated | `tests/unit/test_sendgrid_open_click_webhook.py::test_existing_suppress_events_unchanged` | B |
| AC7 | `test_agent_origin_exclusion.py` stays green unmodified | Fully-Automated | `tests/unit/test_agent_origin_exclusion.py` (baseline confirmed 18 passed at VALIDATE) | A |
| AC8 | Both new migrations apply cleanly, chained after the 3 pending migrations, non-destructive | Hybrid (PG, disposable container only) | `cd apps/api && alembic upgrade head` against disposable integration container | B |
| — | `custom_args`/`tracking_settings` forwarded correctly by `email_sender.send()` | Fully-Automated | `tests/unit/test_email_sender_branding.py::test_custom_args_and_tracking_settings_forwarded` (VALIDATE-added) | B |
| — | SendGrid live payload shape (`ip`/`useragent`/`custom_args` echo) matches assumed fixture schema | Agent-Probe | `vc-docs-seeker` SendGrid Event Webhook schema pull before EXECUTE, or live sandbox replay | D — backlog test-building stub: `process/features/visitors-identity/backlog/sendgrid-payload-shape-live-verify_NOTE_23-07-26.md` (to be written at EXECUTE/EVL time if not resolved via docs-seeker) |
| — | Account-level SendGrid tracking-settings override vs explicit payload `tracking_settings` | Agent-Probe (needs-live-provider — NOT probed per VALIDATE cost-class policy) | manual live-account check, post migration-live-apply | D — named residual, deferred to operator action when `identity_signals_enabled` is flipped to `True` in a real environment |

gap-resolution legend:
- A — proven now (gate passes in this cycle; baselines captured at VALIDATE, see Test Gate Commands)
- B — fixed in this plan (gate added by this plan's checklist, including the VALIDATE-added items 11-15)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

Legacy line form (retained so existing validate-contract consumers still parse):
- Phase 1 core: Fully-automated: `.venv/bin/python -m pytest tests/unit/test_company_graph.py -q` | Hybrid: `tests/integration/test_company_graph_persistence.py -q` (needs docker compose postgres+redis) | Known-gap: none
- Phase 2 core: Fully-automated: `.venv/bin/python -m pytest tests/unit/test_identity_signals.py tests/unit/test_sendgrid_open_click_webhook.py tests/unit/test_email_sender_branding.py -q` | Hybrid: `tests/integration/test_identity_signals_persistence.py -q` (needs docker compose postgres+redis) | Agent-probe: SendGrid payload shape verification via vc-docs-seeker | Known-gap: account-level SendGrid tracking-settings override (needs-live-provider, not probed)
- Regression: Fully-automated: `.venv/bin/python -m pytest tests/unit/test_agent_origin_exclusion.py -q` (baseline: 18 passed) and `.venv/bin/python -m pytest tests/unit -m unit -q` (baseline: 270 passed, 2 skipped)
- Migration chain: Hybrid: `cd apps/api && alembic heads && alembic upgrade head` against disposable integration container only — never live Postgres

Dimension findings:
- Infra fit: PASS — no container/proxy/port/worker-lifecycle surface touched; pure DB models + service/router edits. No infra context group applicable.
- Test coverage: PASS — 19 verification-evidence rows across Fully-Automated/Hybrid/Agent-Probe tiers; both new migrations get a Hybrid gate (required minimum for the schema/migration High-Risk Class, even though additive); one Agent-Probe known-gap (SendGrid payload shape) has 3 documented resolution options per `vc-test-coverage-plan` format.
- Breaking changes: PASS — `POST /webhooks/sendgrid` extended, never narrowed; existing suppress behavior covered by an explicit regression test; no dashboard-facing API response shape changes; `email_sender.send()`'s new `custom_args` param is optional/additive, backward compatible (confirmed by VALIDATE-added test 15).
- Security surface: PASS (advisory note) — PII pattern (ciphertext + blind index) correctly reused from `beam_identity_graph`; `corroborate_identity()` has zero import access to `IdentifiedVisitor` writes, structurally enforcing the corroborating-only invariant; structlog logging is keys-only throughout (email_domain, not email). Advisory: the new `identity_signals` write path has no explicit rate-limit, but this matches the existing token-gated SendGrid webhook's pre-existing posture (bounce/dropped path has the same exposure today) — not a new regression, not blocking.
- Section 1 feasibility (Phase 1 — company_graph): PASS — all touchpoints confirmed to exist and match the described shapes (`is_proxy_or_vpn`/`is_datacenter_ip` at cited lines, `_upsert_beam_identity` upsert pattern, `_resolve_ip_company_parallel` paid-waterfall hook point, `BeamIdentityNode` confirmed missing city/region/country). No gaps found beyond what the plan already anticipated. Highest-risk edit: the `BeamIdentityNode` schema-column addition (step 6) landing in the same migration as `company_graph` creation — mitigation: EXECUTE may split into two additive migrations if isolating schema changes per table is preferred, both non-destructive either way.
- Section 2 feasibility (Phase 2 — identity_signals): CONCERN found and RESOLVED via plan update — original checklist assumed `site_id`/`visitor_id` availability on the webhook payload without a wiring path; `email_sender.py` sends no `custom_args` today. Fixed by adding checklist items 11-13 (custom_args + tracking_settings + skip-on-absent) directly to the plan at VALIDATE. Also flagged (and fixed via checklist item 14) that no reusable `do_not_resolve` email→visitor lookup helper exists — EXECUTE must write the join inline, pattern cited from `suppression.py:57-64`. Highest-risk edit: the new webhook branch — mitigation is the existing `elif` structural separation from `_SUPPRESS_EVENTS`, confirmed safe at VALIDATE by reading the current handler.

Open gaps:
- SendGrid live payload shape (including custom_args echo shape) — known-gap: documented as HYBRID/Agent-Probe, 3 resolution options in the plan's Known Gap section; mitigated by the design invariant that a wrong/missing signal can only ever "slightly wrong-bump" or "miss" a confidence score, never independently create or misattribute an identity.
- Account-level SendGrid tracking-settings override behavior — known-gap: documented as needs-live-provider (not probed per VALIDATE policy), deferred to the operator action of flipping `identity_signals_enabled=True` in a real environment (same precedent as `agent_detection_enabled`).

What this coverage does NOT prove:
- The Fully-Automated Phase 1/2 unit gates prove pure-logic correctness (upsert conflict handling, staleness math, decay formula, write-gate rejection logic, custom_args forwarding) with mocked DB/HTTP — they do NOT prove real Postgres constraint behavior, real SendGrid HTTP behavior, or real-account tracking-settings precedence.
- The Hybrid persistence gates (`test_company_graph_persistence.py`, `test_identity_signals_persistence.py`) prove behavior against a disposable Docker Postgres — they do NOT prove behavior against the production database's actual data volume, concurrent-write contention, or the live-apply migration path (Docker-gated, explicitly out of scope for this plan).
- The Agent-Probe SendGrid payload-shape check (docs-seeker or manual sandbox) proves the ASSUMED field names against SendGrid's PUBLISHED schema — it does NOT prove the account's actual live event payloads match that published schema at flip-on time, nor does it prove Apple MPP proxy-open IPs are correctly classified by the existing ASN-based datacenter classifier (untested against Apple's specific ranges).
- The regression gates (`test_agent_origin_exclusion.py`, `test_identity_resolver.py`, existing SendGrid suppress test) prove no observed behavior change in THIS repo state on 23-07-26 — they do not prove indefinite future non-regression as the codebase evolves; re-run at EVL and again before any future flag flip.
- No test in this plan proves cross-tenant `company_graph` data quality/accuracy at scale (the plan explicitly notes rDNS accuracy is ~30-50%, an existing known limitation, not newly introduced or newly tested here).

Gate: PASS (no FAILs, plan updated — Phase 2 concern resolved via direct plan-text fix: checklist items 11-15, expanded Known Gap, new Verification Evidence rows)
Accepted by: session (autonomous VALIDATE pass, 23-07-26) — no CONDITIONAL concerns remain open; the one Phase 2 mechanical-feasibility CONCERN found during Layer 2 fan-out was fixed directly in the plan text rather than carried forward as an accepted gap. The two Known Gaps (SendGrid payload shape; account-level tracking-settings override) are pre-classified known-gaps with documented resolution options and do not count toward the CONDITIONAL/BLOCKED gate per the Known-Gap exclusion rule.

---

## Autonomous Goal Block

SESSION GOAL: Ship the owned identity data layer — durable cross-tenant company_graph + SendGrid open/click identity_signals corroborating table — both behind default-OFF flags.
Charter + umbrella plan: N/A — single plan, not a phase program. This plan file is authoritative:
`process/features/visitors-identity/active/owned-data-layer_23-07-26/owned-data-layer_PLAN_23-07-26.md`
Autonomy: Standard /goal autonomous execution rules apply (see `process/development-protocols/orchestration.md` §Autonomy Mode). CONDITIONAL findings apply-and-proceed; BLOCKED items go to backlog and continue; irreversible/outward-facing actions without explicit contract instruction are a hard stop.
Hard stop conditions / safety constraints:
- Never flip `company_graph_enabled` or `identity_signals_enabled` to `True` in any real environment — that is an explicit out-of-scope, human, post-migration-live-apply operator action.
- Never run the Alembic migration upgrade against a real/live Postgres instance — only inside a disposable Docker integration container.
- Never let `corroborate_identity()` gain write access to `IdentifiedVisitor` — the module must import zero `IdentifiedVisitor`-write paths (structural invariant, test-enforced).
- Never store a plaintext email on `identity_signals` — ciphertext + blind index only, mirroring `beam_identity_graph`.
- Never modify existing SendGrid bounce/dropped/spamreport suppression behavior — additive only, regression-tested.
- Do not probe live SendGrid account behavior (needs-live-provider) — accept as known-gap per this contract.
Next phase: EXECUTE — `process/features/visitors-identity/active/owned-data-layer_23-07-26/owned-data-layer_PLAN_23-07-26.md` (Phase 1, then Phase 2; Phase 2 may start independently but should not be marked VERIFIED before Phase 1 if both execute in the same session).
Validate contract: inline in plan (see `## Validate Contract` above).
Execute start: `.venv/bin/python -m pytest tests/unit -m unit -q` (baseline 270 passed) | Hybrid gate: `docker compose -f infra/docker-compose.yml up -d postgres redis` then `.venv/bin/python -m pytest tests/ -m integration -q` | Agent-probe: `vc-docs-seeker` SendGrid Event Webhook schema pull before Phase 2 webhook branch is written | high-risk pack: no (no auth/billing/destructive-migration/secrets surface — additive schema only).

---

## Next Instruction

VALIDATE complete. Gate: PASS. Say **ENTER EXECUTE MODE** to begin implementation, starting with
Phase 1 (Implementation Checklist item 1) or Phase 2 (items may proceed independently).
