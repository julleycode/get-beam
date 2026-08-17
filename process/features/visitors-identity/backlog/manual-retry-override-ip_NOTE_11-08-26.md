---
name: report:manual-retry-override-ip
description: "Backlog — thread override_ip through the MANUAL retry lane so a human can retry a historical non-relay IP (7th consumption site + endpoint change)"
date: 11-08-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
  phase: backlog
---

# Manual Retry cannot choose an IP — `override_ip` is sweep-only

**Origin:** PVL cycle 2 of
`process/features/visitors-identity/active/ip-best-selection-retrigger_09-08-26/ip-best-selection-retrigger_PLAN_09-08-26.md`
(defect ND-3, found by the adversarial verifier). Deliberately scoped OUT of that plan.

## TL;DR

The re-identify plan adds `override_ip` to `resolve()` and the five provider mixins, but only the
**automatic sweep** passes it. The **manual Retry endpoint** does not, so a human can never retry a
`vpn_filtered` visitor against one of that visitor's *historical* non-relay IPs — the stored IP is
the only one the manual lane can ever use.

## The kill chain (verified live 11-08-26)

1. `apps/api/routers/visitors.py:960` —
   `identified = await IdentityResolver(db).resolve(visitor, force_retry=is_retry)`.
   **No `override_ip` argument.**
2. `apps/api/services/identity_resolver.py:644` —
   `if is_privacy_relay_ip(visitor.ip_address):` → sets `identity_status = "vpn_filtered"`,
   commits, returns `None`.
3. So for a visitor whose *stored* IP is a relay, a Retry click re-runs the exact guard that
   produced the status: zero provider calls, zero state change, a button that visibly does nothing.

## What the parent plan shipped instead

It **narrowed** the D-C predicate: the manual Retry button renders for a `vpn_filtered` visitor
**only when the current `visitor.ip_address` is non-empty and non-relay** — i.e. only when the click
can actually reach a provider. Historical-IP retries are served by the automatic sweep, which does
pass `override_ip`.

## The deferred enhancement

Let a human retry a chosen historical non-relay IP. Requires:

- a **7th** `override_ip` consumption site — the manual lane's `resolve(...)` call at
  `routers/visitors.py:960`;
- an endpoint change to decide *which* IP: either an explicit client-supplied IP (needs
  tenant-scoped validation that the IP genuinely belongs to that visitor's events — an IP-injection
  surface) or a server-side call into `rank_candidate_ips(...)` to pick the best untried one
  (cleaner, no new input surface, but pulls the ranker into the request path);
- a UI affordance if the IP is user-selectable;
- gates: manual retry on a relay-stored visitor with a historical non-relay IP now succeeds; the
  chosen IP is still never persisted to `visitors.ip_address`; the cap-exemption and
  counter-non-reset rules for manual Retry are unchanged.

## Why it was deferred

It widens `apps/api/routers/visitors.py` — a file three active plans already hold unexecuted edits
to — and adds either a new validated input surface or a request-path dependency on the ranker.
Neither belongs in a plan whose central risk is footprint on contested identity files.
