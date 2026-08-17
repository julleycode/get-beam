---
name: report:cf-connecting-ip-forgeability-canary
description: Known-gap — CF-Connecting-IP is trusted unconditionally (forgeable off-CF) and collapses to the CF edge IP when absent; both break the per-IP limiters on the public canary routes
date: 11-08-26
metadata:
  node_type: memory
  type: report
  feature: onboarding-canary
  phase: backlog
---

# `CF-Connecting-IP` forgeability + colo-collapse on the public canary routes

**Status:** open known-gap · **Severity:** downgrades every per-IP control on the public surface to a
speed bump · **Raised by:** PVL cycle 1 adversarial pass on `public-canary-funnel_11-08-26` (S3).

## TL;DR

Two opposite failure modes of the same header, both live:

1. **Forgeable (header present, origin reachable off-CF).** `apps/api/services/ip_resolution.py:54-63`
   returns `CF-Connecting-IP` as the client IP whenever `ingest_trust_cf_connecting_ip` is on, with
   **no check that the peer is a Cloudflare edge**. If the Railway origin answers direct requests, a
   caller picks their own rate-limit bucket at will — defeating the 40/min canary limiter and the
   12/min feedback limiter completely.
2. **Colo-collapse (header absent).** `client_ip_key_func` falls back to the peer address, which is
   the Cloudflare edge IP. Every visitor behind one colo then shares **one** 40/min bucket, and the
   public funnel self-throttles under ordinary traffic. Symptom: 429s at a request rate far below
   40/min.

## Why it matters here specifically

The public canary plan cites the per-IP rate limit as a control in several places. It is not one.
The real bounds on the public write path are the input caps (`fingerprint` ≤64, `shown` 2 KB/16 keys,
`note` 500 chars), the 256 KB body guard, and the 90-day retention purge. Any text that presents the
rate limit as the defense is overstating it.

Note the second-order effect: because a flood can rotate the header freely, the aggregate geo budget
(parent plan Phase 1b / D7 half ii) is not a nice-to-have — it is the only ceiling a rotating-IP
caller cannot bypass.

## Class

Same defect class as the already-backlogged **ingest** forge-risk (see the CF proxy IP chain memory
note: `ingest_trust_cf_connecting_ip` was added to fix CF edge IPs being stored, and the forge-risk
was explicitly backlogged at the time). This is not created by the canary plan; the canary plan is
what puts a public unauthenticated funnel on top of it.

## What Phase 5 must record (not fix)

Parent plan Phase 5 step 20 requires the operator to record, in the phase report:

- Whether two requests from two genuinely different client IPs land in **two different rate-limit
  buckets** (proves the header is arriving and is per-visitor, not colo-collapsed).
- Whether the Railway origin is **reachable off-CF** (proves or disproves the forgeability half).

Both answers are needed either way — a "yes it's reachable" is not a blocker for the flip, it is a
documented acceptance.

## Resolution options

- **A —** Verify the peer address against Cloudflare's published IP ranges before trusting the
  header (the standard fix; needs a ranges refresh path, so it is real work).
- **B —** Make the origin unreachable off-CF at the network layer (Railway/CF config, no code).
  Cleanest if achievable.
- **C —** Add an aggregate (non-per-IP) ceiling on the public routes so the forgeable key stops being
  the only ceiling. The parent plan already does exactly this for the geo path (Phase 1b); extending
  the same idea to the feedback write is the natural follow-up if the soak shows abuse.
- **D —** This stub (chosen for now): documented known-gap, keeps AC-9's gate **CONDITIONAL**, and
  Phase 5 records the live answers.
