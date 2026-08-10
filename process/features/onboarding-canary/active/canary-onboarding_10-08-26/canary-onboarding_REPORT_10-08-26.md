---
phase: canary-onboarding-phase-1-backend
date: 2026-08-10
status: COMPLETE_WITH_GAPS
feature: onboarding-canary
plan: process/features/onboarding-canary/active/canary-onboarding_10-08-26/canary-onboarding_PLAN_10-08-26.md
---

# Phase 1 — Backend (flag OFF)

## What Was Done

| File | Change |
|---|---|
| `apps/api/services/geoip.py` | Rewritten. `GeoResult` + `resolve_geoip_full`; `resolve_geoip` is now a thin wrapper with a frozen `(country_code, region)` return. Widened field mask to `status,countryCode,regionName,city,lat,lon,isp,org,as`. NEW `geoip2:` JSON Redis prefix (legacy `geoip:` still read AND written with the pipe format). Added `settings.mock_external_apis` short-circuit and HTTP 429 handling (`X-Ttl` → `geoip:backoff` key, clamped 1–300s). |
| `apps/api/services/onboarding_canary.py` | NEW. `fetch_journey(db, fp, site_id=None)` (extracted from `demo_journey`), `build_network` (ASN → org → isp → stripped `as` → omit), `build_geo` (Null-Island guard). |
| `apps/api/routers/onboarding.py` | NEW. `POST /canary` (30/min) + `POST /identity-feedback` (204). Authed, flag-off → 404, `resolve_client_ip`, IP logged truncated and never in the body. |
| `apps/api/routers/demo.py` | `demo_journey` now calls the shared `fetch_journey` with **no** `site_id` — behaviour unchanged. Dropped two now-unused imports. |
| `apps/api/main.py` | Router imported + mounted at `/api/v1/onboarding` beside demo. |
| `apps/api/config.py` | `beam_self_site_id`, `location_reveal_enabled = False`, house-style comment block (gates / why OFF / ROLLOUT ORDER / KNOWN LIMITATIONS). |
| `apps/api/models/identity_feedback.py` | NEW model + `FEEDBACK_REASONS` frozenset + `NOTE_MAX_CHARS`. |
| `apps/api/models/visitor.py` | Added `Index("idx_visitors_fingerprint", "fingerprint")` to `__table_args__`. |
| `apps/api/migrations/versions/a1c7f4e082d5_add_onboarding_canary_support.py` | NEW migration. |
| `tests/unit/test_geoip.py` | +10 tests. |
| `tests/unit/test_location_reveal.py` | NEW, 16 tests. |
| `tests/integration/test_onboarding_canary_api.py` | NEW, 9 tests. |

**Migration:** revision `a1c7f4e082d5`, `down_revision = d3f9a1c25e84`. Head re-derived live
(`alembic -c apps/api/alembic.ini heads` → `d3f9a1c25e84 (head)`), not taken from docs. Live
up/down/up round-trip on a disposable `canary_mig_smoke` DB with `DATABASE_URL` pinned to
`localhost:5433`: index + table present at head, both `GONE` after downgrade, clean re-upgrade,
`alembic_version = a1c7f4e082d5`. Scratch DB dropped.

## Test Gate Outcomes

| Gate | Result |
|---|---|
| `tests/unit/test_geoip.py` | **14 passed** (4 pre-existing + 10 new, incl. the byte-identical backward-compat assertion) |
| `tests/unit/test_location_reveal.py` | **16 passed** |
| `tests/integration/test_onboarding_canary_api.py` | **9 passed** |
| `tests/integration/test_demo_journey.py` | **3 passed** (regression net for the shared extraction) |
| `tests/integration/test_events_ingest.py` | **20 passed / 1 failed** — failure NOT from this phase (see below) |
| Full unit lane | **1652 passed / 2 skipped / 1 failed** — failure NOT from this phase (see below) |
| Migration live round-trip | PASS (disposable DB) |
| Full integration lane (`tests/ -m integration`) | **NOT OBSERVED.** Started and still running after ~25 min when this report was written; the per-test `drop_all`/`create_all` of 53 tables is very slow on this machine (3 tests in `test_demo_journey.py` alone took 4m21s). No result claimed. |

## Plan Deviations

1. `GeoResult` is a plain `__slots__` class, not a `@dataclass`. Same fields the plan names; chosen
   for trivial `to_dict`/`from_dict` JSON round-tripping through Redis. Within blast radius.
2. `resolve_geoip` still reads AND writes the legacy `geoip:` key (in addition to `geoip2:`). The
   plan only mandated not *overloading* it. Keeping the legacy write means a rolling deploy's old
   pods stay on the cheap cache path.
3. Feedback rate limit set to 30/minute (plan specified 30/min for `/canary` only, silent on
   feedback). Same limiter, one submission per user in practice.

## Test Infra Gaps Found

**Two failures in the worktree belong to a CONCURRENT, uncommitted session, not to this phase.**
Another agent is mid-edit on a `farbled` / `has_unstable_fingerprint` feature:

- `tests/integration/test_events_ingest.py::TestCookieFpPhase2::test_fingerprint_survives_aggregation_totals`
  — `asyncpg UndefinedColumnError: column "farbled" does not exist`.
- `tests/unit/test_aggregation_sql_shape.py::...::test_since_none_sql_is_byte_identical_to_the_frozen_query`
  — the frozen aggregator SQL now has `BOOL_OR(farbled) AS has_unstable_fingerprint` added.

Attribution evidence (read-only git):
- `git show HEAD:<file> | grep -c farbled` → **0** for `visitor_aggregator.py`, `event.py`,
  `visitor.py`; the worktree copies have 3 / 1 / 2. The symbol does not exist at HEAD.
- `git diff --stat apps/api/routers/events.py` → 47 added lines, **all** farbled; `git diff` on
  that file contains **zero** `geoip` hits, i.e. the `resolve_geoip` call site is untouched, which
  is exactly the backward-compat property this phase had to preserve.
- `tests/unit/test_aggregation_sql_shape.py` itself is listed as modified (` M`) — that session is
  still editing the frozen fixture.
- Their untracked migration `e2b7c94a1f38_add_farbled_browser_flag.py` chains
  `down_revision = a1c7f4e082d5` (onto this phase's revision), so the chain has a single head and
  no collision.

I did **not** attempt to fix or revert their work (read-only git only, shared worktree).

## Closeout Packet

- Selected plan: `process/features/onboarding-canary/active/canary-onboarding_10-08-26/canary-onboarding_PLAN_10-08-26.md`
- Finished: the entire "Backend" + "Migration (one)" sections of the plan.
- Verified: unit + integration gates listed above; live migration round-trip.
- Unverified: prod `resolve_client_ip` correctness behind Cloudflare; whether
  `maxmind_asn_db_path` is set in the deployed env (rung 1 of the network ladder is dead when it
  is `""`); the 24h `/ingest` geoip soak the plan's rollout order requires before step 2.
- Classification: **Keep in active/testing.** Phases 2-4 (React shell, Leaflet canary, follow-ups)
  are unstarted and the flag soak has not run.
- Next: Phase 2 (React chat shell) per the plan's §Suggested phasing.

## Forward Preview

**Test Infra Found** — integration lane needs `docker compose -f infra/docker-compose.yml up -d
postgres redis`; the Docker CLI is off PATH at
`/Applications/Docker.app/Contents/Resources/bin/docker` and the daemon needed `open -a Docker`
first. Use `.venv/bin/python3.11 -m pytest` (the `.venv/bin/pytest` shebang is broken).

**Blast Radius Changes** — `apps/api/services/geoip.py` is now shared between the ingest hot path
and the onboarding reveal. Any future edit must keep `resolve_geoip`'s 2-tuple contract.

**Commands to Stay Green**
```
.venv/bin/python3.11 -m pytest tests/unit/test_geoip.py tests/unit/test_location_reveal.py -q
.venv/bin/python3.11 -m pytest tests/integration/test_onboarding_canary_api.py tests/integration/test_demo_journey.py -q
```

**Dependency Changes** — none. No new Python packages. (Phase 3 adds `leaflet` on the web side.)
