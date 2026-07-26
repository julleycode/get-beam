---
name: spec:ingest-abuse-hardening
description: "Requirements for hardening POST /ingest against DDoS + rotating-IP flooding without dropping real traffic"
date: 25-07-26
feature: pixel
---

# Ingest Abuse Hardening — SPEC

## Summary

Beam's tracking pixel sends every page visit to one public endpoint, `POST /ingest`. Today that
endpoint stops obvious bots (known bot user-agents, datacenter IPs, proxy/VPN IPs) and throttles
each individual IP address to 100 requests/minute. But an attacker who spreads requests across many
different IP addresses — a "rotating-IP flood" using a residential proxy pool, which is cheap and
common — gets a fresh allowance on every IP and is never slowed down. Because Beam's paid lookups
(identity resolution, enrichment) are already budget-capped, this kind of attack can't run up an API
bill. What it CAN do is quietly fill a site owner's dashboard with thousands of fake "visitors,"
bloat the events database, and — at high enough volume — degrade the service for real customers.
This SPEC defines what the system must do to detect and contain that kind of flood, and where the
edges of that protection are (what stays a hosting/ops concern, not application code).

## User Stories / Jobs To Be Done

- As a **site owner**, I want my visitor dashboard to reflect real people who visited my site, so
  that the AI outreach/segmentation features work on real leads instead of being polluted by fake
  traffic.
- As a **site owner** with a high-traffic or bursty site (e.g. a product launch or a shared
  corporate/campus network sending many real visitors from one IP), I want my legitimate traffic
  never to be silently dropped by anti-abuse protections, so that I don't lose real visitor data
  during my best days.
- As the **Beam operator (founder)**, I want to be able to tell "we're being flooded by an
  attacker" apart from "a customer's site went viral," so that I can respond appropriately (block
  vs. celebrate) instead of guessing from raw event counts.
- As the **Beam operator**, I want confidence that a flood of ingest traffic cannot silently exhaust
  paid-provider budgets or leak visitor PII into logs, so that an attack is a nuisance, not a
  financial or compliance incident.
- As the **Beam operator**, I want the ingest endpoint's abuse defenses to keep working correctly
  when traffic is proxied through a CDN/WAF (e.g. Cloudflare in front of Railway), so that adding an
  edge layer later doesn't break IP-based logic or get spoofed by a malicious client.

## What The User Wants (Behavioral Outcomes)

- **Site-wide and global ingest ceilings exist**, not just per-IP. A flood distributed across many
  IPs must be recognizable as a flood at the site level (and, if the abuse is broad enough, at the
  Beam-wide level), not slip through because no single IP crossed its own limit.
- **Oversized request bodies are rejected outright** before they're processed, so a single crafted
  "batch" request can't consume disproportionate resources.
- **The real client IP cannot be spoofed.** If a request arrives via a trusted proxy/CDN, the system
  must use the proxy-verified client IP for all rate-limiting and reputation checks — not a
  client-supplied header that an attacker could forge to reset their own rate-limit bucket.
- **When a limit trips, the site owner's real data is protected first.** The system must have a
  defined, predictable behavior for "what happens to this specific request" (see Acceptance
  Criteria — this is a requirement to be decided here, not an implementation detail deferred to
  INNOVATE).
- **The operator has a clear signal of "abuse in progress" vs. "organic traffic spike,"** surfaced
  somewhere the operator can see it (dashboard, alert, or log-based query) — not something they have
  to reverse-engineer from raw event counts after the fact.
- **None of this changes what the paid-provider budget system does.** Identity resolution and
  enrichment budgets are already capped and already correctly gate money-spending calls; this work
  is about data/DB/availability protection, and must not touch or weaken those existing caps.
- **None of this logs PII.** Any new counters, flags, or alerts operate on IPs, counts, and
  site/tenant identifiers — never raw visitor PII (name, email, etc.) in logs, matching the existing
  guardrail.
- **Any new external service call (e.g. a reputation/velocity lookup) has a mock-mode path**, so
  dev/tests/demo continue to run keyless, matching the existing `MOCK_EXTERNAL_APIS=true` contract.
- **Multi-tenancy is preserved.** Any new counters, budgets, or thresholds are scoped per-`Site`
  (filtered by `Site.user_id` where the operator/dashboard-facing side is concerned) — one tenant's
  flood must not consume another tenant's ingest allowance or trip another tenant's alert.

## Flow / State Diagram

```
                         POST /ingest (site_id, visitor payload)
                                     |
                                     v
                     +-------------------------------+
                     | Resolve TRUE client IP          |
                     | (trusted-proxy-aware; cannot     |
                     |  be spoofed via client headers)  |
                     +-------------------------------+
                                     |
                                     v
                     +-------------------------------+
                     | Body size check                  |
                     | too large? --> REJECT (413-class) |
                     +-------------------------------+
                                     |  (size OK)
                                     v
              +----------------------------------------------+
              | Existing checks (unchanged):                    |
              |   - site_id must exist        --> 403 if not     |
              |   - bot UA regex               --> silent 204    |
              |   - datacenter IP drop         --> silent 204    |
              |   - proxy/VPN IP drop          --> silent 204    |
              +----------------------------------------------+
                                     |  (passes existing checks)
                                     v
              +----------------------------------------------+
              | Per-IP rate limit (existing, unchanged: 100/min) |
              +----------------------------------------------+
                                     |
                                     v
              +----------------------------------------------+
              |  NEW: Per-site ingest ceiling                    |
              |  (and, if broad enough, global ceiling)          |
              |  Are recent requests for this site/site-cluster  |
              |  exceeding a sane threshold regardless of        |
              |  per-IP spread?                                  |
              +----------------------------------------------+
                    |  under threshold          |  over threshold
                    v                           v
        +----------------------+   +--------------------------------+
        |  NEW: Behavioral       |   | Limit-tripped response          |
        |  velocity signal        |   | (exact behavior = Acceptance    |
        |  (distinct visitor_ids/ |   |  Criteria AC-1..AC-4 below —   |
        |  fingerprints per site  |   |  enumerated options, one        |
        |  per window) recorded   |   |  required by this SPEC)         |
        |  and available to       |   +--------------------------------+
        |  operator observability |
        +----------------------+
                    |
                    v
        Event insert + existing aggregation pipeline (unchanged)
                    |
                    v
        +----------------------------------------------+
        |  NEW: Operator observability surface             |
        |  "flood signature" vs "organic spike" signal      |
        |  (per-site + global view)                          |
        +----------------------------------------------+
```

## Acceptance Criteria (Testable Outcomes)

**AC-1 — Site-level ingest ceiling exists and is independent of IP diversity.**
A site that receives a high volume of ingest requests from many distinct IP addresses in a short
window is detected and acted on, even though no single IP ever crosses the existing per-IP
100/min limit.
`proven by:` integration test simulating N distinct source IPs against one `site_id` exceeding the
new site-level threshold within the window. `strategy:` Fully-Automated.

**AC-2 — Oversized request bodies are rejected before processing.**
A `POST /ingest` request whose body exceeds the defined size ceiling is rejected without being
parsed into an `Event` write, and without invoking downstream services (identity resolution,
aggregation).
`proven by:` integration test posting an oversized payload and asserting no `Event` row is created
and the response is a rejection (not 204/200). `strategy:` Fully-Automated.

**AC-3 — Client IP resolution cannot be spoofed via client-supplied headers.**
When Beam sits behind a trusted proxy/CDN, the IP used for all per-IP and per-site rate-limiting,
and for datacenter/proxy-VPN reputation checks, is the proxy-verified IP — not a value taken
verbatim from a client-controlled header (e.g. a forged `X-Forwarded-For`). A request that forges
this header to look like a "fresh" IP does not reset its own rate-limit bucket.
`proven by:` integration test sending requests with spoofed/forged forwarding headers from a
single real source and asserting the per-IP counter still accumulates against the true IP, not the
forged one. `strategy:` Fully-Automated.

**AC-4 — Limit-tripped behavior is explicit and consistent (this SPEC decides the default).**
When a request is identified as abusive by the new site-level or velocity checks, the system's
response is one of the following documented options — the SPEC requires **Option C (flag-but-store,
excluded from customer-facing counts and outreach eligibility)** as the default behavior, unless
INNOVATE identifies a stronger technical reason to choose otherwise for a specific sub-case (e.g.
volumetric floods may still warrant a hard reject at high enough severity):

  | Option | Behavior | User-visible consequence |
  |---|---|---|
  | A. Silent 204 (matches existing bot-filter pattern) | Request accepted at network level, dropped before DB write | Attacker gets no feedback (good — avoids tipping them off), but the operator has no data trail for what was blocked |
  | B. Explicit reject (429/403-class) | Request rejected with a real error status | Signals to any legitimate misconfigured client (rare, but possible) that something is wrong; also signals to a sophisticated attacker that they were caught, which may cause them to adapt |
  | C. Flag-but-store (accept the request, write the event, but mark it so it never counts toward customer-visible visitor totals or becomes an outreach-eligible identity) | Preserves complete audit trail and observability for the operator, protects site owner's dashboard/outreach data from pollution, at the cost of continuing to write DB rows for flagged traffic | Site owner's *visible* data stays clean even though the underlying event table keeps every row |
  | D. Sampled-accept (log 1-in-N of flagged requests, drop the rest) | Reduces DB growth from a sustained flood while preserving a representative sample for forensics | Fastest DB-growth mitigation, but operator loses some fidelity of the record |

`proven by:` integration test asserting flagged/abusive-pattern events are excluded from the
visitor-facing dashboard aggregate AND excluded from outreach-eligible identity resolution, while
still present in the raw event store for operator inspection. `strategy:` Fully-Automated.

**AC-5 — False-positive protection: high-traffic legitimate sites are not throttled.**
A single site receiving a large but organic traffic spike (e.g. many distinct real visitors,
realistic diversity of fingerprints/user-agents/referrers, consistent with a viral post or launch
day) does not trip the new site-level ceiling in a way that drops or flags its real visitors.
`proven by:` integration test comparing an "organic spike" traffic shape (high volume, high
diversity of behavioral signals) against a "flood" shape (high volume, low diversity / synthetic
signal pattern) and asserting only the flood shape trips the new controls. `strategy:` Hybrid
(automated shape-generation + documented threshold tuning rationale, since the exact numeric
threshold requires operator judgment call recorded in Open Questions/Constraints).

**AC-6 — False-positive protection: shared-IP legitimate traffic is not blanket-blocked.**
Many real visitors arriving from one shared IP (corporate NAT, campus network, CGNAT) are not
treated identically to a single attacker hammering that IP — the per-IP limit alone must not be
the sole signal used to flag a site as under attack, and the new site-level check must be able to
distinguish "many real users, one shared IP" from "one attacker, many spoofed identities" using
behavioral diversity signals (distinct fingerprints/visitor patterns), not IP count alone.
`proven by:` integration test simulating high request volume from one IP with high fingerprint/UA
diversity (shared-NAT shape) and asserting it is NOT flagged as abusive, contrasted with low
diversity from the same IP volume being flagged. `strategy:` Fully-Automated.

**AC-7 — Operator can distinguish "we are being flooded" from "a customer went viral."**
The operator has access to a signal — surfaced via dashboard, alert, or a documented log-based
query — that differentiates a flood pattern (high volume, low behavioral diversity, concentrated
per-site or cross-site pattern matching known abuse signatures) from an organic spike (high
volume, high behavioral diversity, consistent with real user variety). This signal is available
without the operator having to manually query raw event tables.
`proven by:` a defined observability check (dashboard panel, alert rule, or documented query) is
present and returns different results for a simulated flood dataset vs. a simulated organic-spike
dataset. `strategy:` Hybrid (automated backend signal computation; the surfacing/alerting UX may
require an Agent-Probe or manual verification if it's a dashboard visual, per INNOVATE's chosen
surface).

**AC-8 — Real client IP resolution is correct and works behind a proxy/CDN.**
Whether or not Cloudflare (or any edge/WAF) sits in front of Railway, the ingest endpoint resolves
the true client IP consistently and correctly for every downstream check (per-IP limit,
datacenter/proxy-VPN reputation, new site-level and velocity checks). This is the code-side
counterpart to the ops-level edge/WAF item (see Out Of Scope) — the application must be *ready* to
sit behind a trusted proxy correctly, independent of whether that proxy is deployed yet.
`proven by:` integration test asserting IP resolution logic correctly extracts the client IP from
a trusted-proxy header chain, and rejects/ignores untrusted header values when no trusted proxy is
configured. `strategy:` Fully-Automated.

**AC-9 — No PII in new logs, counters, or alerts.**
Any new logging, counters, or alert payloads introduced by this work contain only IPs, counts,
`site_id`/tenant identifiers, and non-PII metadata (timestamps, UA strings already treated as
non-PII today) — never visitor name, email, or other PII fields.
`proven by:` code-level regression test/lint asserting new structlog call sites do not pass raw
PII fields (mirrors the existing guardrail enforcement pattern). `strategy:` Fully-Automated.

**AC-10 — New external calls (if any) have a mock-mode path.**
If INNOVATE/PLAN introduces any new external service call (e.g. an IP-velocity/reputation
lookup), it has a deterministic mock path gated by `MOCK_EXTERNAL_APIS=true`, matching every other
external integration in the codebase.
`proven by:` unit test running the new call path with `MOCK_EXTERNAL_APIS=true` and asserting a
deterministic fake response with no network call attempted. `strategy:` Fully-Automated.

**AC-11 — Paid-provider budgets are untouched.**
The existing `daily_resolution_budget` (default 50/site/day) and `default_daily_enrichment_budget`
(default 3/day) behavior is unchanged by this work — this hardening operates upstream of and
independent from those budget gates.
`proven by:` regression run of existing budget-gate tests (`identity_resolver.py` budget tests)
confirming no behavior change. `strategy:` Fully-Automated.

## Out Of Scope

- **CAPTCHA / interactive challenge UX.** No client-facing challenge flow is introduced. The pixel
  is a passive, invisible tracker by design (see pixel `_GUIDE.md`); adding a visible challenge
  would break that model. If a future need arises, it is a separate SPEC.
- **Proof-of-work / client-side computational challenge.** Not evaluated or required here.
- **Any change to the paid-provider identity resolution or enrichment budget system.** Those caps
  already correctly bound financial exposure (see Summary — this is explicitly a data-integrity and
  availability problem, not a cost problem). Do not touch `daily_resolution_budget`,
  `default_daily_enrichment_budget`, or the 30-day no-retry rule as part of this work.
- **Deploying or configuring an edge/WAF/CDN layer (e.g. Cloudflare in front of Railway).** This is
  an operations/runbook decision, not application code, and is explicitly out of this SPEC's code
  blast radius. The code-side counterpart requirement (correct, unspoofable client-IP resolution
  when a trusted proxy IS present) is covered by AC-8 and AC-3. Standing up the edge layer itself is
  tracked as a separate ops action item, not implemented by this SPEC.
- **Volumetric (network-layer) DDoS protection.** Out of application-code reach entirely; depends on
  hosting-provider defaults (Railway) or a future edge layer. Noted as a known residual risk, not
  solved here.
- **Retroactive cleanup of already-polluted historical visitor/event data.** This SPEC hardens the
  ingest path going forward; backfilling or purging existing bad data (if any is found) is a
  separate, explicitly scoped follow-up if needed.
- **Changing the bot UA regex filter, datacenter-IP drop, or proxy/VPN-IP drop logic.** These exist
  today and work as designed; this SPEC adds new layers alongside them, not replacements.

## Constraints

- Must not weaken or bypass the existing per-IP rate limit, bot filter, datacenter-IP drop, or
  proxy/VPN-IP drop — new controls are additive.
- Must not introduce any change to `daily_resolution_budget`, `default_daily_enrichment_budget`, or
  the 30-day no-retry identity-resolution rule (see Out Of Scope).
- Must not log PII (visitor name, email, etc.) in any new log line, counter, or alert payload —
  matches existing repo-wide guardrail.
- Any new external call must support `MOCK_EXTERNAL_APIS=true` with a deterministic fake response,
  matching the existing mock-mode contract for every other external integration.
- Every new per-site counter, threshold, or budget must be scoped to `Site` and filtered through
  `Site.user_id` on any operator/dashboard-facing read path — one tenant's flood data must not leak
  into or affect another tenant's view or limits (multi-tenancy guardrail).
- The rate-limiting storage concern already known from RESEARCH (Redis vs. in-process `memory://`
  fallback causing per-replica buckets in multi-replica deploys) must be accounted for by any new
  site-level/global counter design — a counter that silently becomes per-replica defeats its own
  purpose. This is a hard constraint on the *design*, decided in INNOVATE/PLAN, but the *requirement*
  that the counter behave correctly across replicas is locked here.
- Must not change the pixel's client-side behavior in a way that makes it a visible/interactive
  element (see Out Of Scope — no CAPTCHA/challenge).
- New thresholds (site-level ceiling, velocity-window definition, body-size cap) must be
  configurable via `pydantic-settings` env vars, matching the existing config pattern
  (`BLOCK_DATACENTER_TRAFFIC`, `BLOCK_PROXY_VPN_TRAFFIC`, etc.) — not hardcoded magic numbers.

## Open Questions

None — all decisions needed to lock this SPEC are resolved above (AC-4 sets the default
limit-tripped behavior; thresholds and exact numeric tuning are deferred to INNOVATE/PLAN as
implementation detail, not blocking intent). Numeric threshold tuning (exact requests/window,
exact body-size ceiling in bytes, exact velocity-window duration) is intentionally left to
INNOVATE/PLAN — this is a calibration decision, not an unresolved requirement.

## Background / Research Findings

Prior RESEARCH (verbatim summary) established:

- **Ingest endpoint:** `apps/api/routers/events.py` `POST /ingest`.
- **Existing protections:** per-IP rate limit (100/min, slowapi, `rate_limiter.py:31`, Redis-backed
  with a silent fallback to in-process `memory://` when Redis is unreachable — this fallback means
  multi-replica deploys can end up with one independent bucket per replica, a known design hazard
  for any new counter); datacenter-IP drop (default ON, MaxMind + IPinfo fallback, Redis-cached 30d,
  fail-open on error); proxy/VPN/Tor drop (default ON, IPinfo Privacy API, Redis-cached 7d, fail-open
  on error, deliberately excludes Apple Private Relay / CF WARP); bot UA regex filter; `site_id`
  existence check (403 if invalid); idempotent insert on `event_id` conflict.
- **Financial backstops already in place and correctly scoped:** `daily_resolution_budget` (default
  50/site/day), `default_daily_enrichment_budget` (default 3/day), 30-day no-retry per visitor.
  These gate only PAID provider calls; free prior-signal checks (form email match, fingerprint) run
  first with no cap.
- **Retention:** 90-day auto-purge on events and agent-fetch events, 24h purge cadence.
- **The 4 gaps this SPEC addresses:**
  1. No per-site or global ingest throttle — only per-IP; an attacker rotating IPs defeats the
     limiter entirely since every IP gets its own fresh 100/min bucket.
  2. No body-size cap on `/ingest` — no `TrustedHostMiddleware`, no max-content-length, no Starlette
     body limit anywhere in `apps/api/main.py`.
  3. No edge/WAF/CDN layer in the repo — volumetric DDoS protection currently depends entirely on
     unverified Railway hosting defaults. Cloudflare-in-front-of-Railway was floated as a candidate
     but is explicitly an ops/runbook decision, not application code (see Out Of Scope).
  4. No behavioral/velocity abuse detection — nothing counts "one `site_id` receiving N distinct
     `visitor_id`s/fingerprints in a short window"; no challenge or proof-of-work exists;
     client-side has only `navigator.webdriver` (trivially bypassed).
- **Research verdict:** an attacker rotating residential-proxy IPs with realistic browser UAs
  defeats every current IP-reputation check (residential pools are built to mimic real eyeballs),
  successfully lands rows in Postgres, but cannot burn meaningful money due to the existing budget
  caps. The damage is DB bloat + polluted analytics/visitor/outreach data, plus a secondary
  availability risk at high volume — not an API bill. This framing drove every user story and
  acceptance criterion above: the problem is data integrity and availability, and the SPEC
  deliberately protects the untouched budget system rather than re-solving an already-solved
  problem.
