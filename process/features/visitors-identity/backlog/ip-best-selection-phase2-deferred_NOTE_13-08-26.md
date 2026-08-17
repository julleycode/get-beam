---
name: report:ip-best-selection-phase2-deferred
description: Phase-2 backlog for best-IP re-identify — items excluded from the descoped Phase-1 plan, with the blocker for each
date: 13-08-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
  phase: backlog
---

# Best-IP Re-Identify — Phase 2 backlog

**Parent (Phase 1):** `process/features/visitors-identity/active/ip-best-selection-phase1_13-08-26/ip-best-selection-phase1_PLAN_13-08-26.md`
**Origin of findings:** PVL cycle 7 of the superseded plan —
`process/features/visitors-identity/active/ip-best-selection-retrigger_09-08-26/ip-best-selection-retrigger-pvl-iteration-003_REPORT_13-08-26.md`

Every item below is **excluded from Phase 1 by locked scope**. None is closed. Do not fold any of
them into Phase 1 — each needs its own decision or a prerequisite that Phase 1 does not deliver.

---

## D-1 — `vpn_filtered` Retry button revival (verifier V6, P1)

`is_privacy_relay_ip` (`apps/api/services/company_resolver.py:233`) matches only `2a09:bac3:` —
iCloud **IPv6**. `apps/api/routers/events.py:346` already drops proxy/VPN/Tor/hosting at ingest
(`is_proxy_or_vpn` deliberately excludes `relay`), so the surviving `vpn_filtered` population is
relay-dominated and heavily **IPv4** (Cloudflare WARP). The manual lane passes no `override_ip`
(`routers/visitors.py:960`), so a widened button re-runs the guard at `identity_resolver.py:644`
and returns to the same badge — a visibly dead button plus one paid IPinfo call.

**Blocked on:** IPv4 relay coverage in `is_privacy_relay_ip`, and threading `override_ip` through
the manual lane (a 7th consumption site + an endpoint/UI change to choose the IP). Existing stub:
`process/features/visitors-identity/backlog/manual-retry-override-ip_NOTE_11-08-26.md`.

## D-2 — Relay/VPN attempt-accounting contract (verifier V7, P1)

The superseded plan asserted both sides: Public Contracts (`:175`) says a relay exit still counts
the attempt and appends `tried_ips`; S3-1 (`:1919`) says `provider_work_started` is false. Under the
S3-1 reading the ranker re-picks the same IP every tick.

**Needs:** one explicit decision, then one accounting row and one gate. Not a Phase-1 blocker
because Phase 1's ranker excludes relay IPs before selection (DR-11), so the exit is only reachable
via the IPinfo VPN check on a non-relay-prefix IP.

## D-3 — `auto_reidentify_skip_count` reset semantics (verifier V8, P2)

`skip_count` is never reset. A visitor with one IP for 56 days retires at `skip_count = 8` with
`count = 0`, and is then permanently excluded even when three new org-tier IPs later appear — exactly
the population the feature's Goal 2 names.

**Needs:** a reset rule (e.g. reset on observing an untried IP) plus its own bound so the reset
cannot re-open an unbounded loop.

## D-4 — Manual-retry leftover-`anonymous` (verifier V11, P2)

`apps/api/routers/visitors.py:911-914` flips a terminal status to `anonymous` **before** calling
`resolve()`. If `check_daily_budget` then refuses, the row is left permanently `anonymous` — silently
removed from the sweep's `identity_status IN ('unresolvable','vpn_filtered')` population with
`auto_reidentify_count` frozen. Phase 1's P18 reorders the *claim* relative to that mutation but does
not address the leftover case.

**Needs:** either restore the prior status on a refusal, or move the flip after a successful dispatch.

## D-5 — `provider_unavailable` budget-stamp accounting beyond Phase 1 (verifier V4 residual, P1)

Phase 1's P1-AD-4 closes the unbounded-re-dispatch half (per-tier verdict + capped 24h re-defer, no
write-off). The remaining half: `usage_limits.py` counts DISTINCT `visitor_id`, so an outage-only
attempt still consumes a daily budget slot even though no provider answered and no `ResolutionLog`
row exists.

**Needs:** a decision on whether an outage-only dispatch should be excluded from the distinct-visitor
meter — this touches the shared meter for all four lanes, so it cannot ride inside Phase 1's flag
boundary.

## D-6 — Web UI surface — **prod-enable precondition**

Excluded from Phase 1 because Phase 1 is backend-only and, with the flag OFF, nothing is observable:

- `VisitorOut.auto_reidentify_count` and the "tried N/4" counter on the visitor list row
  (`apps/web/src/app/dashboard/visitors/page.tsx`) and the detail page.
- The site-settings `auto_reidentify_opt_out` toggle (`apps/web/src/lib/api-types.ts`,
  `apps/web/src/components/site-settings-dialog.tsx`) — deliberately inverse-labelled.

Phase 1 ships the API plumbing (`SiteUpdate` / `SiteOut` / `update_site`), so an operator can
`PATCH /sites/{id}` meanwhile. **Ship D-6 or confirm operator PATCH before any prod flag flip.**

**Note (schema hazard):** new detail-only fields go on `VisitorDetailOut`, never on `VisitorOut` —
the P0 `GET /visitors` 500 of 07-08-26 was exactly this mistake.

## D-7 — Full-repo negative-cache re-key (newly identified 13-08-26)

Phase 1 site-scopes `resolution:{site_id}:{ip}` **only** for `auto_retry=True` calls, so the change
stays inside the flag boundary. The cross-tenant leak therefore persists for the three default lanes
(APScheduler, registered Celery, manual retry): site A's `__none__` sentinel suppresses site B's
dispatch for 30 days on a shared NAT/CGNAT IP.

**Needs:** re-key every caller at `apps/api/services/identity_resolver.py:694` plus a one-time
cold-cache cost disclosure (up to one extra provider call per `(site, ip)` within the TTL window).
Prefix is `resolution:` from `apps/api/services/identity_providers/base.py:16` — there is no `beam:`
client-side prefix.

## D-8 — Rollout-gate measurements (Known-Gap, keeps the Phase-1 rollout gate CONDITIONAL)

1. Eligible-backlog COUNT per site under the Phase-1 base predicate, measured with the flag OFF, so
   the cold-start drain time is known before the flip (a 5,000-row backlog drains in ~21 days at 24
   ticks/day).
2. Distinct-IPs-per-visitor distribution for the terminal population — quantifies whether attempts
   #2–#4 are worth anything.
3. Tune the 70% budget-reserve placeholder from measured per-site data.

These are the only Known-Gap rows in the Phase-1 verification table. They are **rollout** gates, not
behavior gates.
