---
name: spec:ip-best-selection-retrigger
description: "SPEC — best-IP selection at resolve time + automatic re-trigger when a visitor appears from a new untried IP; 6 open decisions (D1-D6) for user pick"
date: 09-08-26
feature: visitors-identity
metadata:
  node_type: spec
  type: spec
  feature: visitors-identity
---

# SPEC — Best-IP Selection + New-IP Automatic Re-Trigger

**TL;DR:** Today, identity resolution uses whichever IP a visitor happened to be on *most recently*. If that was their home IP, resolution fails, the visitor is marked dead, and a 30-day IP-blind gate blocks any retry — even when they later show up from an office IP that would have resolved. This SPEC asks for two things: (a) pick the visitor's *most resolvable* IP at resolve time, and (b) automatically retry when a genuinely *new, untried* IP appears — with hard budget, privacy, and starvation guardrails. Six decisions (D1–D6) are presented below for you to pick; each has a recommendation.

## Summary

A single visitor browses from multiple IPs over time (home, office, mobile, VPN). Beam stores only the *latest* IP per visitor and resolves with that one. When the resolve moment lands on a residential or VPN IP, the attempt fails and the visitor is parked in a terminal state (`unresolvable` or `vpn_filtered`). A later visit from a resolvable office IP changes nothing: the retry gate is blind to IPs, the customer doesn't know a "Retry" button exists, and the lead is silently lost forever. This feature makes IP choice deliberate (use the best IP available, not the newest) and makes recovery automatic (a new untried IP re-opens the case), while keeping provider spend bounded and every existing privacy/safety invariant intact.

## User Stories / Jobs To Be Done

1. **As a Beam customer**, I want resolution to try my visitor's *most resolvable* IP (their office network, not their home Wi-Fi), so that a lead isn't wasted because of the timing of their last visit.
2. **As a Beam customer**, I want a visitor who failed on a home/VPN IP to be *automatically* retried when they later return from a new office IP, so that I don't have to know about — or remember to click — a manual Retry button.
3. **As a Beam customer**, I want automatic retries to be capped and observable, so that this feature cannot silently multiply my provider spend.
4. **As a visitor who opted out** (Global Privacy Control / do-not-resolve), I want Beam to never retry resolving me, no matter how many IPs I appear from.
5. **As the Beam operator**, I want the whole behavior behind a default-OFF flag, so nothing changes in production until I deliberately turn it on.

## What The User Wants (Behavioral Outcomes)

- When a visitor has been seen from more than one IP, the resolution attempt uses the IP most likely to identify a company (an office/organization IP), not simply the newest one. Privacy-relay/VPN IPs are never chosen when a cleaner IP is known.
- When a previously-failed visitor reappears from an IP Beam has *never tried for them*, they become eligible for resolution again — automatically, with no dashboard click.
- An IP that was already tried for that visitor is not tried again (no loop on the same failing IP).
- Retries stop when a daily retry allowance runs out, and stopping is the safe direction (when the counter can't be checked, don't retry).
- Visitors flagged as AI-agent traffic, and visitors with the do-not-resolve opt-out, are never selected by any part of this feature.
- Everything is inert until the operator flips a new flag; with the flag off, today's behavior is unchanged byte-for-byte.

**Locked scope (user decisions already made — not re-opened here):**
- BOTH halves are in scope: best-IP selection at resolve time AND automatic new-IP re-trigger.
- Retry policy: retry on **ANY new untried IP** (not only when the new IP looks "better").
  - **Cost consequence you must see:** this is the most expensive policy researched. Once the 30-day gate is bypassed for new IPs, the theoretical ceiling is 48 sweep runs/day × 20 visitors = **960 resolve() calls/site/day** vs. an intended 50 — and this burn is *invisible*: the daily meter counts distinct visitors (a retried visitor costs 0 meter units), and failed attempts are priced $0.00 in the logs. Only D6's separate retry cap makes the policy safe.
  - **Bounded variant offered (your explicit alternative, not a silent narrowing):** keep "any new untried IP" but cap untried-IP attempts per visitor (e.g. at most N distinct IPs tried per visitor per 30 days). This preserves your policy for the common 2–3-IP visitor while capping the pathological many-IP visitor. Pick it inside D6 if wanted.

## Coverage Reality Check (product decision, read this)

The automatic resolution sweep only runs for sites with `auto_identify_enabled = True` — a setting that **defaults to False**. On a default site there is *no automatic resolution at all*, only the manual per-row button. Consequence: **if the re-trigger is hosted in the sweep (D5 option B), this entire feature is inert on most sites.** If it is hosted in the rollup revive path (D5 option A), it reaches every site because the rollup always runs. This is a product-coverage decision, not a technical detail: decide whether "automatic recovery" should be a benefit of opting into auto-identify, or a baseline behavior for everyone. It interacts directly with D5.

## Flow / State Diagram

Current miss chain vs. desired behavior:

```
TODAY (the miss):
 visitor @ home IP ──ingest──► visitor.ip_address = home IP  (newest wins)
        │
        ▼ intent ≥ 20, sweep picks visitor
 resolve(home IP) ──fails──► identity_status:
        │                      ├─ 'vpn_filtered'  ── DEAD FOREVER (no retry path at all)
        │                      └─ 'unresolvable'  ── dead unless narrow revive fires
        ▼ later
 visitor @ office IP ──ingest──► visitor.ip_address = office IP
        │
        ▼ 30-day gate: "attempted this VISITOR recently?" (IP-blind)
      BLOCKED ──► lead silently lost
      (only escape: manual Retry button the customer never clicks,
       or the narrow revive path: unresolvable-only + IP-*changed*-between-
       snapshots + deletes the failure evidence)

DESIRED:
 visitor seen from {home IP, office IP, ...}
        │
        ▼ resolve time
 BEST-IP SELECTION: rank known IPs (org > eyeball/datacenter/cdn;
 never a privacy relay when a cleaner IP exists) ──► resolve(best IP)
        │
        ├─ success ──► identified (unchanged downstream)
        └─ failure ──► record "tried (visitor, IP)"
                │
                ▼ visitor later appears from NEW UNTRIED IP
        RE-TRIGGER: eligible again (gate is per-(visitor, IP), per D3)
                │
                ├─ retry allowance available (D6) ──► resolve(new best IP)
                └─ allowance exhausted / unknown ──► do NOT retry (fail closed)

 Always excluded at every step: agent-origin visitors, do_not_resolve visitors.
 Everything above: flag default OFF.
```

## Decisions For You To Pick (D1–D6)

These six are open. Each block: the question, the options with cost/risk from verified research, and a recommendation. **You pick; the SPEC does not decide for you.**

### D1 — Where does per-visitor IP history live?

Answering "have we tried this visitor's office IP?" requires knowing which IPs a visitor has had and which were tried. No such record exists today (`ResolutionLog` has no IP column; there is no visitor-IP table).

- **Option A — scan the events table at resolve time.** Events already store one IP per event, indexed by (site, visitor). Free, no new schema, no new PII surface. Costs: no index on the IP column (per-visitor scans are fine, IP-wide queries are not); hard 90-day horizon (events auto-purge — history older than 90 days vanishes); still can't record "tried" per IP without D3's ledger anyway.
- **Option B — a new durable per-(visitor, IP) attempt ledger.** Survives the 90-day purge, indexable, and directly answers both "seen" and "tried". Costs: net-new schema/migration; creates a **new durable plaintext-PII surface** — IPs are stored unencrypted everywhere today, GDPR erasure currently matches on email blind-index only, so this table needs its own erasure coverage AND its own retention rule (a derived store must not outlive its source); interacts with the held pii-at-rest plan.
- **Option C — hybrid: scan events for "seen", small ledger for "tried".** Minimal durable footprint (only attempted IPs are stored, typically 1–3 rows per resolved-attempted visitor). Same PII/erasure obligations as B but on a much smaller row set.

**Recommendation: C.** D3 and D4 both need a durable "tried" record (the events table can't carry it, and deleting logs to fake it is banned — see D3). But "seen" is already answered for free by events. Storing only attempted IPs keeps the new PII surface as small as it can be while still making the feature correct past the 90-day horizon.

### D2 — What does "best IP" mean?

Four composable ingredients exist; the question is which are baseline and which are later.

- **(i) org-kind classification** (local MaxMind ASN lookup + classifier: org / eyeball / datacenter / cdn). Zero flags, zero credits, sub-microsecond, works today. Prefer `org` over the rest.
- **(ii) fused IP→org confidence score.** Richer signal, but blocked behind a default-OFF flag AND the production tables it reads are currently **empty**. Not usable as a baseline dependency.
- **(iii) prior cross-tenant company-graph hit.** One free DB read — "we already know this IP maps to a company." Behind a default-OFF flag (`company_graph_enabled`).
- **(iv) exclude privacy-relay IPs.** Pure, free predicate. Never pick a relay IP when a non-relay is known.

**Recommendation: baseline = (i) + (iv); (iii) as an opportunistic bonus when its flag is on; (ii) explicitly later** (it's tracked by the ip-org enable runbook and is an operator step, out of scope here). This gives a real residential-vs-office discriminator on day one with zero cost and zero new dependencies.

### D3 — Does the 30-day no-retry gate become IP-scoped?

The gate today asks "was this *visitor* attempted in 30 days?" — a brand-new office IP is blocked exactly like a repeat of the same home IP.

- **Option A — widen the gate to (site, visitor, IP).** A new IP is retryable; a tried IP still waits 30 days. Requires D1's "tried" ledger. Clean semantics; preserves all attempt history.
- **Option B — replicate the revive path's trick: delete the visitor's failed log rows so the gate sees a fresh candidate.** No new storage. Costs: destroys the attempt evidence a correct design needs ("which IPs did we try?" becomes unanswerable), and touches the **immutability invariant** — resolution logs are deliberately treated as immutable because both the budget meter and the gate derive from them; a prior deletion here enabled a credit-re-burn loop. Extending the one sanctioned exception is the risky direction.
- **Option C — a distinct `auto_retry` bypass, separate from the manual `force_retry`,** so automatic and manual retries are capped and audited independently.

**Recommendation: A + C together.** A is the correct gate semantics (needs D1 ledger); C keeps automatic retry volume separately accountable from the human-clicked button instead of overloading one bypass flag. Reject B — evidence destruction and invariant erosion.

### D4 — Does `vpn_filtered` become retryable?

The real insight: **`vpn_filtered` is a fact about an IP, but it is stored as a fact about a visitor.** One visit through a home VPN permanently kills the visitor — excluded from the sweep, explicitly non-retryable in the API, untouched by the revive path. This is *exactly* your home-VPN scenario: the person is real and resolvable; only that one IP was masked.

- **Option A — leave it terminal.** No change, no risk; the user's scenario stays broken for VPN cases (only `unresolvable` benefits from this feature).
- **Option B — retryable only when a NEW non-relay IP appears.** The visitor stays parked until a clean untried IP shows up; the relay IP itself is never retried. Matches the per-IP truth without re-modeling anything.
- **Option C — re-model the state per-IP** (verdicts attach to IPs, visitor state is derived). Most correct, largest scope — touches how the status vocabulary is stored and every reader of it.

**Recommendation: B.** It fixes the user's exact scenario at minimal scope and is safe by construction (the trigger condition — new non-relay IP — is precisely the evidence that the visitor is no longer masked). C is a future re-model, not this feature.

### D5 — One re-trigger mechanism or two? (one must win)

Half of the re-trigger already ships: the rollup's revive path flips changed-IP `unresolvable` visitors back to eligible. Extending it vs. building a new sweep are both viable — but **two mechanisms owning the same re-trigger is a live conflict; one must be the owner.**

- **Option A — extend the existing revive path** (~small change). Pros: runs for EVERY site (rollup always runs — see Coverage Reality Check), inherits working snapshot plumbing. Cons: lives in the hot rollup path that a currently-active plan (ip-org-quality-pack) deliberately kept READ-ONLY; only reaches `unresolvable` today; its current design deletes failure logs (conflicts with D3-A); triggers on "IP changed," not "IP never tried."
- **Option B — a new flag-gated sweep** (same shape as the existing promotion sweep: own module, own flag, advisory lock, resolver untouched). Pros: isolated, flag-gated, doesn't touch the contested rollup or resolver files. Cons: must independently solve sweep starvation (a proven trap — the fix must live in the sweep query itself, like the existing deferral filter) and must not diverge from the dormant second sweep; **only runs on `auto_identify_enabled` sites** — inert for most customers.
- **Option C — B now, with A's revive path explicitly narrowed to defer to the new owner** (revive stops being extended; its overlap is resolved in PLAN so the two never double-fire).

**Recommendation: C.** The new sweep is the right owner (isolation, flag gating, no contested files), but the SPEC must be honest that this choice trades away default-site coverage (Coverage Reality Check above) — if you want every-site coverage, pick A and accept the rollup-path collision cost. Either way, exactly one owner; the loser is explicitly subordinated.

### D6 — Which meter does an auto-retry consume?

- **Option A — leave retries on the existing distinct-visitor daily meter.** Zero work. Consequence: a same-day retry of an already-counted visitor is **invisible** to the meter, and failed attempts cost $0.00 in the logs — so the 960-calls/day ceiling produces no visible spend signal anywhere. The user's chosen "any new untried IP" policy is unbounded under this option.
- **Option B — a separate daily retry allowance** (Redis counter per site per day, reserve-then-refund, **fail-CLOSED** — modeled on the existing job-change recheck budget precedent). Retries stop when the allowance is spent or the counter is unreachable. Optionally add the per-visitor untried-IP cap from the Locked-scope bounded variant.

**Recommendation: B, with the per-visitor cap included.** It is the only option that makes "retry on any new IP" affordable. **Important honesty note: no cap value anywhere in this repo has a measured basis** (the precedent's own cap is labelled a placeholder). Any number chosen now is a placeholder to be tuned from observed data — see Measurement Gap.

## Acceptance Criteria (Testable Outcomes)

Grounded in the repo's test lanes (unit: pure/no-deps pytest; integration: pytest vs real Postgres+Redis via the docker-compose harness in `process/context/tests/all-tests.md`; strategies per the 3-way split). Exact test file names are finalized in PLAN; scenarios below are the named gates.

1. **Best IP wins.** Given a visitor seen from both an office-classified IP and a residential-classified IP, the resolution attempt observably targets the office IP.
   - proven by: integration scenario `best-ip-selection: org-over-eyeball` (real PG, seeded events)
   - strategy: Fully-Automated
2. **Relays never chosen over clean IPs.** Given a visitor with one privacy-relay IP and one non-relay IP, the relay IP is never the attempted IP.
   - proven by: unit scenario `best-ip-selection: relay-excluded` (pure ranking predicate)
   - strategy: Fully-Automated
3. **New untried IP re-opens the case.** A visitor previously failed as `unresolvable` on IP A who later sends events from never-tried IP B becomes resolution-eligible and is attempted again with no manual action.
   - proven by: integration scenario `retrigger: new-ip-revives` (end-to-end through the chosen D5 owner)
   - strategy: Fully-Automated
4. **Tried IPs are not looped.** A visitor reappearing from an IP already attempted for them within the gate window is NOT re-attempted.
   - proven by: integration scenario `retrigger: tried-ip-blocked`
   - strategy: Fully-Automated
5. **`vpn_filtered` behavior matches the D4 pick.** If D4-B: a `vpn_filtered` visitor gains eligibility only when a new non-relay untried IP appears, and never for a new relay IP. If D4-A: existing terminality is regression-locked.
   - proven by: integration scenario `retrigger: vpn-filtered-policy`
   - strategy: Fully-Automated
6. **Budget non-regression.** The existing invariants hold unchanged: the daily meter counts distinct visitors (existing `test_counts_distinct_visitors_not_rows` stays green) and deterministic-only resolution never consults the daily budget (existing unit invariant stays green).
   - proven by: existing gates `tests/integration/test_resolution_budget.py::test_counts_distinct_visitors_not_rows` + `tests/unit/test_identity_resolver_parallel.py` deterministic-budget invariant
   - strategy: Fully-Automated
7. **Retry allowance is enforced and fail-closed (per D6 pick).** When the daily retry allowance is exhausted — or its counter is unreachable — no automatic retry runs.
   - proven by: integration scenario `retry-budget: exhausted-and-unreachable` (Redis stopped/keyed-out cases)
   - strategy: Fully-Automated
8. **Agent-origin exclusion.** Every new selection/eligibility query includes the human-only visitor filter; an agent-origin visitor is never selected for best-IP resolution or re-trigger.
   - proven by: integration scenario `exclusion: agent-origin-never-selected` + regression suite `test_agent_origin_exclusion.py` unchanged
   - strategy: Fully-Automated
9. **do_not_resolve honored.** A visitor with the sticky do-not-resolve flag is never retried by any new path, regardless of new IPs.
   - proven by: integration scenario `exclusion: do-not-resolve-never-retried`
   - strategy: Fully-Automated
10. **No PII in logs.** No IP address (and no email) appears in structlog output emitted by the new selection/re-trigger paths; log events carry keys/ids/counts only.
    - proven by: unit scenario `logging: no-pii-on-new-paths` (log-capture assertion)
    - strategy: Fully-Automated
11. **Sweep-starvation non-regression.** With a mixed population of retry-eligible and never-attempted visitors exceeding the sweep LIMIT, never-attempted visitors still get selected (the eligibility gate lives in the sweep query, matching the deferral-filter precedent).
    - proven by: integration scenario `starvation: retry-does-not-crowd-out-new`
    - strategy: Fully-Automated
12. **Flag default OFF, flag-off byte-identical.** The new flag defaults OFF; with it off, all existing unit + integration suites pass unchanged and no new selection/re-trigger behavior is observable.
    - proven by: full existing regression lanes run with flag unset + integration scenario `flag-off: inert`
    - strategy: Fully-Automated
13. **Erasure + retention cover the new store (if D1-B/C picked).** A GDPR erasure for a visitor removes their rows from the new attempt store, and the store has a stated retention rule not exceeding its purpose.
    - proven by: integration scenario `pii: ledger-erasure-and-retention`
    - strategy: Fully-Automated
14. **Real-world resolvability of a specific office IP.** Whether a given corporate IP actually resolves via paid providers is provider-dependent and cannot be automated without billed live calls.
    - proven by: none automatable — residual
    - strategy: Agent-Probe (explicitly-justified residual; live-provider double-opt-in policy applies)

## Out Of Scope

- **Paid provider selection changes.** Which providers run, their order, and their pricing are untouched.
- **The identity waterfall's non-IP checks** (fingerprint match, cross-tenant identity graph, email capture). These are IP-independent; a retry must NOT redundantly re-run them as if they were new evidence.
- **Anything requiring `ip_org_lookup_enabled=True` or populated prod `ip_org_prefixes`/fusion tables** (D2 option ii). Those are operator steps tracked in `ip-org-prod-enable_RUNBOOK_07-08-26.md`, not dependencies of this feature.
- **Changing the `auto_identify_enabled` default** or auto-enrolling sites into auto-identify (surfaced in Coverage Reality Check as a separate product decision).
- **Re-modeling identity status per-IP** (D4 option C) — future work.
- **IP encryption / blind-indexing at rest** — owned by the held pii-at-rest plan; this SPEC only obligates erasure + retention coverage for any new store (AC-13).
- **Back-pressure/alerting on budget exhaustion** beyond the fail-closed stop itself.

## Constraints

1. **Privacy first.** The sticky do-not-resolve check gates every new path (AC-9). Never log IPs (AC-10). Any new durable IP store gets explicit erasure coverage and its own retention rule (AC-13); note the pii-at-rest plan overlaps this surface.
2. **Agent-origin exclusion is the highest-priority invariant.** Every new selection query includes the human-only filter (AC-8).
3. **Budget invariants are load-bearing.** Resolution logs are treated as immutable (budget + gate derive from them); the revive path's targeted delete is the only sanctioned exception and must not be widened (D3). Existing budget tests must stay green (AC-6). Failed attempts are $0.00 by construction — dollar reports cannot be used as the safety net.
4. **Sweep starvation is a proven trap, not a hypothesis.** A prior circuit-breaker fix was built, tested green, and reverted on live evidence. The eligibility gate must live in the sweep query itself (AC-11).
5. **The dormant second sweep exists and diverges silently** if only the live sweep is changed — any query-semantics change must account for both.
6. **org_kind has five on-disk values** (org / eyeball / datacenter / cdn / registry — the model comment listing four is doc drift); ranking logic must handle all five.
7. **Migration discipline.** Prod alembic head moves; always re-derive heads live; never run bare alembic (repo `.env` points at Supabase PROD with no local-host guard — pin `DATABASE_URL=localhost:5433`).
8. **Multi-tenancy.** Every new query filters by site ownership; unknown ids return 404, never 403.
9. **Collision map.** Active plans already touch the shared chokepoints (resolver, rollup/revive, sweep runner, scheduler + its job-count gate, visitors router). ip-org-quality-pack kept the resolver and rollup READ-ONLY; graph-erasure warns that any increase in resolve() volume widens a DELETE race window; the resolver "has been rewritten three times in the last week" — PLAN must claim its chokepoints explicitly and re-derive every anchor.
10. **Flag posture.** All new behavior behind a new default-OFF flag, matching the repo's operator-gated precedent (AC-12).

## Measurement Gap

Nothing in this repo measures the **distinct-IPs-per-visitor distribution**. Therefore the blast radius of "retry on ANY new untried IP" is unquantified: we do not know whether the typical visitor has 2 IPs or 20, how often a new IP appears after a failure, or what share of new IPs are office-classified. Before any cap number in D6 is treated as more than a placeholder, measure (read-only, from existing events data): (a) distinct IPs per visitor per 30/90 days (p50/p95/max), (b) rate of "new IP after failed resolution" events per site per day, (c) org-kind mix of those new IPs. These three numbers turn the D6 cap and the per-visitor bound from guesses into tuned values. Until then, every cap is explicitly a placeholder — consistent with the repo's precedent that no existing cap value has a measured basis either.

## Open Questions

The six DECISION blocks (D1–D6) above are the open questions. Owner: **user** — to be picked at the SPEC review gate before this document is locked and PLAN begins. Each carries options, grounded costs, and a recommendation; skipping a pick defaults to the recommendation only with your explicit confirmation. No other open questions.

## Background / Research Findings

Key verified facts that shaped this SPEC (full anchors in the research findings; all path:line references were confirmed on disk):

- **The miss chain is real and complete.** Sites default to no automatic resolution (`auto_identify_enabled=False`). The rollup stores only the newest event IP per visitor ("latest", never "best"). The 30-minute sweep resolves the one stored IP. Failures land in `vpn_filtered` (permanently dead: excluded from sweep, non-retryable in the API, untouched by revive) or `unresolvable` (dead unless the narrow revive path fires). The 30-day retry gate is completely IP-blind — the resolution log has no IP column at all.
- **The Redis per-IP cache is NOT a blocker** — it is keyed by IP, so a new IP is a fresh key.
- **Half of the re-trigger already exists**: the rollup's revive path flips changed-IP `unresolvable` visitors back to eligible — but it is scoped to `unresolvable` only, triggers on "changed" not "never tried", and deletes the failed-log evidence a proper design needs.
- **A free residential-vs-office discriminator works today**: local ASN lookup + org-kind classifier (org/eyeball/datacenter/cdn), no flag, no credits. The richer fused IP→org score is flag-OFF with empty prod tables. The privacy-relay predicate is pure and free. A prior cross-tenant IP→company read exists behind a flag.
- **What does not exist** (searched, confirmed absent): any per-(visitor, IP) attempt record; any visitor-IP history table; any index on the events IP column; any IP-ranking/best-IP function (the primitives exist but are composed nowhere); any `resolve(ip=...)` override; any retry path for `vpn_filtered`; any IP hashing/encryption (IP is plaintext everywhere).
- **Budget asymmetry**: the daily meter counts distinct visitors (retries invisible), failures cost $0.00, the monthly plan cap counts successes only — so retry burn shows up nowhere. Ceiling once the gate is bypassed: ~960 resolve calls/site/day vs. an intended 50.
- **Two separate resolution ladders never meet**: the identity resolver never calls the ip-org lookup; its only consumer is the company-domain backfill.
- **Sweep starvation was proven live**: an out-of-query circuit breaker was built, tested green, and reverted; the deferral-watermark filter (in-query) is the surviving pattern.
- **User's verbatim intent** (translated): a visitor browses from multiple IPs; if resolution fires while they're on a home IP it fails; later they visit from an office IP that WOULD resolve, but the customer has no idea to click re-run, so the opportunity is silently lost forever. "Phải làm sao?" — what should we do? Locked answers: do both best-IP selection and automatic re-trigger; retry on any new untried IP (cost consequence surfaced above, bounded variant offered in D6); IP-history storage left to research → now D1.
