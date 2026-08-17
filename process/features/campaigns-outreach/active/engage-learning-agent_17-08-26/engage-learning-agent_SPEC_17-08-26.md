---
name: spec:engage-learning-agent
description: "Product-discovery SPEC for a self-improving social Engage agent — learns from measured outcomes of its own replies (reply-back, likes, site visits), remembers what worked per contact / per site / cross-tenant, and earns bounded autonomous sending via an evidence-anchored confidence threshold"
date: 17-08-26
feature: campaigns-outreach
metadata:
  node_type: spec
  type: spec
  feature: campaigns-outreach
---

# Engage Learning Agent — SPEC

**TL;DR:** Beam's social Engage agent currently replies and forgets. This SPEC makes it remember: every reply it posts gets measured (did they reply back? like it? visit the site?), the outcome is stored as memory at three scopes (per-contact, per-site/use-case, cross-tenant), and the agent's approach gets smarter over time. Once a playbook has *enough measured wins* for a segment, the agent may send above-threshold replies autonomously; everything else still queues for human approval. This deliberately amends the repo's standing "never auto-send" guardrail — a change the user explicitly approved on 17-08-26 — and the SPEC requires the guardrail text itself to be updated so future agents don't fight the implementation.

---

## Summary

Beam customers use the Engage lever to reply to relevant social posts (today: X/Twitter live, LinkedIn partial). The AI drafts replies, a human approves, Beam posts — and then nothing. The platform's reaction to the reply (a reply back, a like, a repost, a resulting site visit) is never captured, so the agent cannot learn what actually works. This feature closes that loop: capture the outcome of every posted reply, remember what worked for *this contact*, *this site's use-case*, and (k-anonymously, consent-gated) *across all of Beam*, and use that memory to pick better approaches next time. When — and only when — the measured track record for a given approach and audience is strong enough, the agent earns the right to send without waiting for approval, inside hard safety rails (kill switches, rate ceiling, crisis-thread block, audit log, undo). The learning is strictly empirical — "what did *our own* replies measurably achieve" — never an attempt to reimplement X's ranking algorithm.

## User Stories / Jobs To Be Done

- **US-1 (site owner):** As a Beam customer, I want the Engage agent to learn from how people respond to its replies, so that its replies get measurably better over time instead of staying the same quality forever.
- **US-2 (site owner):** As a Beam customer, I want the agent to remember what worked with a specific person we've engaged before, so that follow-up interactions with that person build on what already landed.
- **US-3 (site owner):** As a Beam customer, I want the agent to send replies on its own once it has *proven* (with real measured outcomes, not self-assessed confidence) that a given approach works for my audience, so that I stop being a bottleneck on volume — while everything unproven still comes to me for approval.
- **US-4 (site owner):** As a Beam customer, I want to see *why* the agent sent something autonomously (which track record justified it) and be able to delete a posted reply, so that I stay in control of my brand's public voice.
- **US-5 (site owner):** As a Beam customer, I want to opt my site into (or out of) cross-tenant learning under a dedicated consent, so that I can benefit from what works across Beam without my data leaking to other tenants.
- **US-6 (operator):** As the Beam operator, I want a global kill switch and per-site flags that default OFF, so that a misbehaving autonomous sender can be stopped instantly and nothing sends autonomously without a deliberate enable.
- **US-7 (operator):** As the Beam operator, I want a full audit trail of every autonomous send and every learning-derived decision, so that I can reconstruct exactly what the agent did and why when a customer asks.
- **US-8 (engaged contact / data subject):** As a person the agent replied to, I want my erasure request to remove any per-contact memory Beam holds about me, so that Beam's GDPR obligations extend to this new memory too.

## What The User Wants (Behavioral Outcomes)

Observable, from the outside:

1. **Outcomes become visible.** After Beam posts a reply, the dashboard eventually shows what happened to it: replied-back yes/no, like/repost counts, and whether a site visit / lead followed from that engagement. Today all of these read as unknown/zero.
2. **The agent visibly adapts.** Over weeks of use on a site, the mix of reply approaches the agent proposes shifts toward the ones that measurably got responses for that site — and the owner can see the per-approach track record that drove the shift.
3. **Contact-level continuity.** When the agent drafts a reply to someone it has engaged before, the draft reflects what previously worked (or didn't) with that person, and the owner can see that history on the contact.
4. **Earned autonomy, not asserted confidence.** A brand-new site's agent never sends anything by itself — every reply queues for approval, exactly as today. Only after an approach accumulates a sufficient number of measured positive outcomes for that site/segment does the agent begin sending that kind of reply autonomously. The owner sees which playbooks have "earned autonomy" and can revoke it (per-site switch) at any time.
5. **Hard rails on the public surface.** Autonomous sends respect a per-site hourly ceiling; never fire into threads showing negative/crisis signals; never target suppressed or privacy-held contacts; every one is audit-logged; every one can be undone (platform post deleted) from the dashboard.
6. **Cross-tenant lift with zero leakage.** A consenting site's outcomes contribute to anonymous, aggregate "what works" knowledge that helps all consenting sites; a non-consenting site neither contributes nor leaves any trace; nothing identifying any tenant or contact ever crosses the boundary.
7. **The rulebook matches reality.** The repo's stated guardrail changes from "never build auto-send" to "auto-send only above an evidence-anchored confidence threshold, inside the rails of this SPEC" — so documentation and implementation agree.

## Flow / State Diagram

Reply lifecycle with the learning loop and the autonomy gate:

```
                        relevant post found (sync/feed)
                                    |
                                    v
                          agent drafts reply
                     (informed by memory: contact +
                      site/playbook + cross-tenant)
                                    |
                                    v
                     ┌──────────────────────────────┐
                     │  AUTONOMY GATE (per playbook  │
                     │  x site/segment)              │
                     │  - feature flags ON?          │
                     │  - >= N measured outcomes?    │
                     │  - positive-outcome rate >= R?│
                     │  - thread free of negative/   │
                     │    crisis signals?            │
                     │  - contact not suppressed /   │
                     │    not privacy-held?          │
                     │  - under hourly send ceiling? │
                     └──────┬────────────────┬──────┘
                       ALL yes            ANY no
                            |                |
                            v                v
                   AUTONOMOUS SEND      HUMAN QUEUE
                   (audit-logged)      (today's flow:
                            |          approve / edit /
                            |          reject ──> send
                            |          on approval)
                            └───────┬────────┘
                                    v
                        posted reply (platform id
                        PERSISTED — never discarded)
                                    |
             ┌──────────────────────┼──────────────────────┐
             v                      v                      v
      reply-received         like/repost/quote      site visit / lead
      (correlation           (metrics check on      (server-minted
      against later          our own posted         attribution tag
      inbound mentions)      reply)                 inside reply content)
             └──────────────────────┼──────────────────────┘
                                    v
                          OUTCOME RECORD (facts +
                          timestamps + counts only —
                          no third-party bodies)
                                    |
            ┌───────────────────────┼───────────────────────┐
            v                       v                       v
     per-contact memory      per-site/playbook       cross-tenant aggregate
     (PII-protected,         track record            (own consent flag,
     erasure-swept)          (drives gate above)     k>=5 sites, no deltas,
                                                     zero PII)

  Error/containment branches (any state):
    - global or site kill switch OFF  ──> no autonomous sends anywhere; queue-only
    - undo requested                  ──> platform post deleted + audit entry
    - erasure request for contact     ──> per-contact memory rows deleted by sweep
```

## Acceptance Criteria (Testable Outcomes)

Each criterion states the observable outcome AND what would prove it false. Scenario names are grounded in the repo's test conventions (`tests/unit/`, `tests/integration/`, mock-mode platform fakes) surfaced during RESEARCH.

**A. Outcome signals (the blocking gap)**

- **AC-1 — The platform id of every posted reply is persisted.** After any send (autonomous or approved), the platform-assigned id of Beam's own posted reply is stored and queryable. **False if:** a sent reply's stored record has no platform id (today's behavior — `sender.py:212` discards it).
  - proven by: integration scenario `test_engage_send_persists_platform_comment_id` (mock platform returns a known id; assert it lands in the DB row)
  - strategy: Fully-Automated
- **AC-2 — Reply-backs are detected and recorded.** When a contact later replies to Beam's posted reply, a reply-received outcome (fact + timestamp, linked to the original send) appears within one sweep interval. **False if:** a simulated inbound reply to a known posted-reply id produces no outcome record.
  - proven by: integration scenario `test_reply_received_correlation_sweep` (seed posted reply + mocked inbound mention carrying the reply-to linkage; run sweep; assert outcome row)
  - strategy: Fully-Automated (mock); the live X leg is Hybrid pending Open Question OQ-1
- **AC-3 — Public engagement metrics on our own replies are captured.** Like/repost/quote counts for Beam's own posted replies are periodically recorded as outcome facts. **False if:** a posted reply whose mocked metrics show nonzero likes still reads zero/unknown after the metrics job runs.
  - proven by: integration scenario `test_reply_public_metrics_poll_records_outcomes` (mock metrics response; assert counts recorded per posted reply)
  - strategy: Fully-Automated (mock); live-tier feasibility is OQ-1 (Hybrid residual)
- **AC-4 — Engagement→site-visit attribution is revived server-side.** The attribution tag is minted **in the server-side approve/send path** and embedded in the reply content *before* posting; a subsequent tagged site visit produces a non-zero engagement-ROI reading. **False if:** a reply can be posted with no tag minted, or if tag-minting depends on any frontend call (the exact failure mode that left `EngagementAttribution` dead — `api.trackEngagement()` has zero component callers).
  - proven by: integration scenario `test_send_path_mints_attribution_tag_server_side` (send via mock platform; assert tag present in posted content and an `EngagementAttribution` row exists) + regression `test_roi_nonzero_after_tagged_visit`
  - strategy: Fully-Automated

**B. Memory + privacy**

- **AC-5 — Per-contact memory is erasable PII.** Any table holding per-contact engagement memory uses the existing blind-index + ciphertext pattern and is registered in `ERASURE_TARGETS`; running the erasure sweep for a contact deletes their memory rows. **False if:** after an erasure request completes, any per-contact memory row for that blind index survives — or if the new table is absent from `ERASURE_TARGETS` (which would make it structurally un-erasable).
  - proven by: integration scenario `test_erasure_sweep_deletes_engage_memory` (write memory row, run `graph_erasure` sweep, assert 0 rows) + unit `test_erasure_targets_includes_engage_memory`
  - strategy: Fully-Automated
- **AC-6 — Fact-and-timestamp only; no third-party reply bodies stored.** Outcome and memory records hold facts, timestamps, counts, and Beam's own content references — never the text of a third party's reply (per the repo's standing standard, `backlog/reply-tracking_NOTE_16-08-26.md`). **False if:** any stored outcome/memory row contains third-party-authored message text.
  - proven by: unit scenario `test_engage_memory_schema_has_no_third_party_body_field` + integration `test_inbound_reply_body_not_persisted` (correlate a mocked inbound reply with a distinctive body string; assert that string appears in zero DB columns)
  - strategy: Fully-Automated
- **AC-7 — Privacy holds gate memory writes.** No per-contact memory is written for a contact whose visitor record carries `do_not_resolve`, or who is on the suppression list — mirroring the four write-gates pattern in `services/identity_signals.py`. **False if:** a held/suppressed contact accrues a memory row.
  - proven by: integration scenario `test_memory_write_gates_do_not_resolve_and_suppression` (non-vacuous: identical un-held control contact in the same test must accrue a row)
  - strategy: Fully-Automated
- **AC-8 — Site-scope memory drives visible track records.** Per-site, per-playbook outcome statistics (sends, replies-back, positive-outcome rate, sample size) are recorded and surfaced to the owner. **False if:** after a seeded set of outcomes, the owner-facing surface shows no per-playbook track record or shows numbers that don't match the seeded outcomes.
  - proven by: integration scenario `test_site_playbook_track_record_matches_seeded_outcomes`
  - strategy: Fully-Automated

**C. Cross-tenant learning**

- **AC-9 — Own third consent flag.** Cross-tenant engagement learning is gated by a NEW dedicated per-site consent flag — separate from both `Site.contribution_enabled` (identity co-op) and `benchmark_contribution_enabled` (campaign benchmarks), because purpose limitation forbids reusing either basis. **False if:** enabling either existing flag alone causes a site's engagement outcomes to cross the tenant boundary.
  - proven by: integration scenario `test_engage_sharing_requires_own_flag_not_coop_or_benchmark_flags` (both existing flags ON, new flag OFF → zero contribution)
  - strategy: Fully-Automated
- **AC-10 — k≥5 floor, no deltas, no trace, no PII.** Cross-tenant aggregates follow the `campaign_benchmark.py` posture: an aggregate exists only when ≥5 distinct consenting sites contribute; sub-floor computation writes NO row; a non-consenting site leaves NO trace anywhere in the aggregate pipeline; no period-over-period deltas are ever exposed; no contact PII, tenant identifier, or reply text crosses the boundary. **False if:** any aggregate row exists with <5 contributing sites, any non-consenting site's data is discoverable in the pipeline, any delta is derivable from the exposed surface, or any cross-boundary record contains PII/tenant identity.
  - proven by: integration scenarios `test_engage_benchmark_k_floor_writes_no_row_below_5`, `test_nonconsenting_site_leaves_no_trace`, `test_no_deltas_exposed`, unit `test_cross_tenant_payload_contains_no_pii_fields`
  - strategy: Fully-Automated

**D. Learning + the autonomy gate**

- **AC-11 — Confidence is observed history, never model self-assessment.** The autonomy decision for a (playbook × site/segment) pair is computed EXCLUSIVELY from stored outcome records: minimum sample count N of measured outcomes AND measured positive-outcome rate ≥ R (both operator-configurable, with conservative defaults). No model-emitted confidence value participates in the gate. **False if:** any code path can authorize an autonomous send using a model-asserted confidence score, or with fewer than N recorded outcomes for that pair.
  - proven by: unit scenario `test_autonomy_gate_pure_function_of_outcome_history` (exhaustive: below-N, at-N-below-R, at-N-at-R cases) + adversarial regression `test_model_confidence_field_cannot_unlock_autonomy` (feed a fabricated "0.99 confident" model output with zero history; assert queued-for-approval)
  - strategy: Fully-Automated
- **AC-12 — Cold start is always human-approved.** A site (or playbook, or segment) with insufficient measured history NEVER sends autonomously — every draft queues through today's approve path (`DraftStatus.approved` remains the only path to send for below-threshold replies). **False if:** any reply posts without approval on a site with zero outcome history.
  - proven by: integration scenario `test_fresh_site_never_autosends` (full pipeline on empty history; assert every draft lands in the approval queue and `sender` refuses unapproved drafts)
  - strategy: Fully-Automated
- **AC-13 — Measured outcomes change future behavior.** After outcome records show one approach outperforming another for a site, the agent's subsequent approach selection measurably shifts toward the winner (extending the existing `voice_examples` explore→exploit precedent to outcome-driven signals, not just human approve/edit/reject). **False if:** seeded strongly-divergent track records produce statistically identical approach selection before vs after.
  - proven by: unit scenario `test_approach_selection_shifts_with_outcome_history` (deterministic seed; assert selection distribution changes in the winner's favor)
  - strategy: Fully-Automated

**E. Safety on a public action surface**

- **AC-14 — OFF by default; dual kill switch.** All autonomous-send capability ships behind flags that default OFF: one global flag (operator) and one per-site switch (owner). Flipping either OFF stops autonomous sends immediately — in-flight queued items fall back to the human approval queue, and drafting/measuring may continue. **False if:** a fresh deploy with default config can autonomously post anything, or a send fires after either switch is OFF.
  - proven by: unit `test_engage_autonomy_flags_default_off` (config defaults) + integration `test_kill_switch_halts_autonomous_sends_immediately`
  - strategy: Fully-Automated
- **AC-15 — Social send-rate ceiling.** Autonomous social sends respect a per-site hourly ceiling (precedent: max 50 emails/hour/site; the social default must be equal or stricter). Above the ceiling, replies queue rather than post. **False if:** ceiling+1 autonomous sends post within one hour for one site.
  - proven by: integration scenario `test_social_send_ceiling_queues_excess`
  - strategy: Fully-Automated
- **AC-16 — Never auto-send into negative/crisis threads.** When the target thread carries negative-sentiment or crisis signals, the reply is NEVER sent autonomously — it routes to the human queue flagged with the reason, regardless of the playbook's track record. **False if:** a thread fixture with crisis markers receives an autonomous send.
  - proven by: integration scenario `test_crisis_thread_routes_to_human_queue` (non-vacuous: identical neutral-thread control in the same test must pass the gate)
  - strategy: Fully-Automated for the routing behavior; the sentiment-detector quality itself is Hybrid (human-reviewed sample set)
- **AC-17 — Full audit + undo.** Every autonomous send writes an audit record (site, contact reference, playbook, the sample count and outcome rate that satisfied the gate, timestamp, posted-reply platform id — no PII beyond the repo's audit conventions). The owner can undo any posted reply: Beam deletes the platform post and appends an undo audit entry. **False if:** any autonomous send lacks an audit record reconstructing WHY it was allowed, or if undo leaves the platform post live (mock) / leaves no audit trail.
  - proven by: integration scenarios `test_autonomous_send_audit_record_completeness` + `test_undo_deletes_platform_post_and_audits` (mock platform delete call asserted)
  - strategy: Fully-Automated (mock); live platform-delete is a Hybrid residual
- **AC-18 — Suppression list extends to social.** A contact suppressed at the email level (bounce/complaint/unsubscribe) is never targeted by an autonomous social send. **False if:** a suppressed contact receives an autonomous reply.
  - proven by: integration scenario `test_suppressed_contact_blocks_autonomous_social_send` (non-vacuous unsuppressed control)
  - strategy: Fully-Automated
- **AC-19 — Untrusted text entering prompts is fenced.** Any third-party-derived text used to inform drafting (thread content, outcome context) passes through `agents/prompt_safety.py` (`clean_text` / `wrap_untrusted`) before reaching a prompt — closing the known divergence where `ai_reply.py:111 _sanitize_content` does not strip `<`/`>`. **False if:** a crafted `<untrusted_visitor_data>`-spoofing payload in thread text reaches the model prompt with its angle brackets intact.
  - proven by: unit scenario `test_engage_prompt_inputs_pass_prompt_safety_fence` (injection-shaped fixture; assert fence unforgeable)
  - strategy: Fully-Automated

**F. Documentation guardrail**

- **AC-20 — The guardrail text is updated in the same change.** `process/context/all-context.md` — the "AI drafts, the human approves and sends. Never build auto-send." brand-stance line (§What Beam Is) AND §Business Guardrails item 1 ("never auto-send") — is amended to state the new rule: autonomous sending is permitted ONLY above the evidence-anchored threshold of this SPEC, inside its safety rails; everything else remains human-approved. **False if:** after the feature ships, `grep -n "Never build auto-send" process/context/all-context.md` still matches, or the Business Guardrails still state an unconditional "never auto-send."
  - proven by: doc-gate scenario `grep` check in the validate-contract (exact command above) run at EVL
  - strategy: Fully-Automated

## Out Of Scope

- **Implementing or approximating X's ranking algorithm.** Nothing about X's internal ranking exists in this repo; the agent learns exclusively from its own measured outcomes. Speculation about X internals is explicitly excluded.
- **Impressions and profile-visit signals.** Impressions need elevated/paid X access; profile visits are not exposed to third parties at all. Both are treated as unavailable.
- **Meta and TikTok.** Neither has a sync path in the codebase; adding one is its own feature.
- **Anything requiring a paid X API tier**, unless the user later approves the spend (see OQ-1).
- **Storing third-party reply bodies** (see AC-6 — fact-and-timestamp is the standard; changing that would need its own SPEC and privacy review).
- **Email reply tracking.** `backlog/reply-tracking_NOTE_16-08-26.md` is a separate future phase; this SPEC covers social outcomes only.
- **Auto-adjusting live email campaigns** based on social learning.
- **Rebuilding `voice_examples`.** The existing explore→exploit loop is a precedent to extend, not replace; human approve/edit/reject signals keep working as today.

## Constraints

- **User-settled decisions (17-08-26, treat as requirements):** (1) auto-send WITH an evidence-anchored confidence threshold, below-threshold queues for approval; (2) memory at all three scopes — per-contact, per-site/use-case, cross-tenant; (3) platform choice defers to what can actually observe outcomes (today that is X; LinkedIn pending OQ-2).
- **Repo flag posture:** every new capability flag defaults OFF; enabling in a real environment is an explicit operator action (matching `agent_detection_enabled` et al.).
- **Human approval machinery stays intact:** `sender.py`'s approved-status check and the drafts approval route remain the only path to send for anything below threshold; the autonomy gate is an additional path, not a replacement.
- **Extend, don't rebuild:** `voice_examples` (learning loop precedent), `campaign_benchmark.py` (k-anonymity precedent), `identity_signals.py` (write-gates precedent), `_handoff_correlation_sweep_job` (correlation-sweep precedent), `EngagementAttribution` (revive server-side, per AC-4).
- **Privacy machinery is mandatory, not optional:** `pii_crypto` blind index + ciphertext for anything contact-linked; `ERASURE_TARGETS` registration; the 90-day raw-event purge posture; GPC/DNT `do_not_resolve` respected.
- **Purpose limitation:** cross-tenant engagement learning gets its OWN consent flag (third basis, separate from identity co-op and campaign benchmarks).
- **Poll-only reality:** no social webhook exists; outcome capture must work within a polling/sweep model (and its rate limits — OQ-1).
- **Public-surface safety floor:** hourly send ceiling ≤ the email precedent (50/hour/site), crisis-thread block, suppression enforcement, audit log, undo path — all per §E above.
- **Anti-vacuity test standard:** this repo has had seven recurrences of gates that pass on the implementation they exist to forbid, and a flag-gated feature is unproven until the flag-ON path executes against real infra (icp_fit lesson, 17-08-26). Every AC above names its falsifier; PLAN/VALIDATE must carry flag-ON gates.

## Open Questions

Both are **empirical feasibility questions, not intent questions** — the user's intent is settled. Owner and disposition per item; neither blocks the SPEC (deferred to the next phases as instructed by the orchestrator; under the autonomous delegation they are recorded here and carried into RESEARCH/INNOVATE rather than pausing).

- **OQ-1 — X API tier + rate limits for a metrics/mentions poller.** (Owner: INNOVATE/PLAN research; likely a `vc-feasibility-test` probe, cost-class `needs-live-provider` — double opt-in required before any billed call.) The production sync path never requests `public_metrics` today; the demo path proves the call shape works, but the tier/limits for polling many posted replies per site are UNVERIFIED. Affects AC-2/AC-3 live legs and the poller cadence. Until verified, those ACs are proven in mock and carry a Hybrid live residual.
- **OQ-2 — Whether the `phantommm` LinkedIn sidecar exposes accepted/replied outcomes.** (Owner: RESEARCH, next phase.) `services/phantommm_client.py:265` returns opaque dicts and the sidecar is unconfigured in this environment. If it cannot report outcomes, LinkedIn stays draft-approve-only (no autonomy) under settled decision (3), and X is the sole v1 learning platform.

## Background / Research Findings

Key orchestrator-verified facts (17-08-26) that shaped these requirements:

- **The single blocking gap is signal acquisition.** No social webhook exists (`routers/webhooks.py` = SendGrid + Leadpipe only); social ingest is poll-only (`jobs/scheduler.py:635`); `FeedPost` carries no metric fields; and **`sender.py:212` receives the platform `comment_id` and discards it** (used only in a log line) — one discarded value that blocks nearly all outcome measurement. Hence AC-1 is the keystone criterion.
- **X exposes what we need and Beam already writes the exact call** — `routers/demo.py:603` requests `public_metrics` and reads `like_count` — but only in the public demo, never in production sync. So reply-back/like/repost signals are attainable on X; impressions/profile-visits are not (paid tier / not exposed) — hence the Out Of Scope lines.
- **`EngagementAttribution` is built but dead:** backend endpoint mounted, service has a caller, web client method exists — with ZERO component callers. No UTM tag has ever been minted; `/engagement/roi` necessarily returns zeros. Design lesson encoded in AC-4: mint the tag server-side in the approve/send path (it must be inside the content before posting; the frontend-owned call already drifted once).
- **A learning loop already exists to extend:** `voice_examples` (`services/ai_reply.py:134-292`) runs explore→exploit→staleness over 3 reply strategies, learning from human approve/edit/reject per `(user_id, platform)` — `CONFIDENCE_THRESHOLD = 5`, `STALENESS_CHECK_INTERVAL = 10`, last-8 exemplar injection. This SPEC adds *measured platform outcomes* as a signal class, at three memory scopes.
- **The approval gate is real and singular:** `sender.py:162-164` refuses non-approved drafts; `routers/drafts.py:249-273` is the only writer of `approved`, behind auth. AC-12 pins this as the below-threshold path.
- **k-anonymity machinery exists:** `campaign_benchmark.py` — `BENCHMARK_K_FLOOR = 5`, closed category vocabulary, sub-floor writes no row, non-consenting leaves no trace, no deltas ever; its consent flag is deliberately a separate legal basis from the identity co-op's. AC-9/AC-10 replicate this posture with a third flag.
- **Privacy machinery any per-contact memory must join:** blind index + ciphertext (`pii_crypto`); `ERASURE_TARGETS = ("beam_identity_graph","identity_signals")` (`models/erasure_request.py:35`) — the erasure sweep matches on blind index, so an unregistered memory table would be un-erasable PII (AC-5); 90-day purge; `do_not_resolve`; four write-gates (`identity_signals.py`) (AC-7).
- **Known pre-existing divergence:** `ai_reply.py:111 _sanitize_content` does not use `agents/prompt_safety.py` and does not strip `<`/`>` — the social path lacks the unforgeable fence the visitor-data path has. Becomes AC-19 the moment third-party text informs drafting.
- **Repo standard on reply bodies:** fact-and-timestamp only, never the body (`backlog/reply-tracking_NOTE_16-08-26.md`) → AC-6.
- **User decision on the guardrail (17-08-26):** shown `all-context.md`'s "Never build auto-send" line, the user chose to change it. Leaving the text stale would make every future agent fight the implementation → AC-20.
- **"Like X's algorithm"** framed as *learn empirically from our own measured outcomes* — nothing about X ranking internals is recorded in this repo and none is speculated here.

### Handoff note for the orchestrator (carry into INNOVATE/PLAN)

RESEARCH flagged this as a **phase program**: 3 independent workstreams with distinct blast radii —
1. **Signal acquisition** (persist `comment_id`, reply correlation sweep, metrics poller, server-side attribution revival),
2. **Memory + privacy** (three-scope memory tables, blind index, ERASURE_TARGETS, write gates, third consent flag + k-anonymous aggregates),
3. **Learning/ranking + autonomy gate** (outcome-driven approach selection, evidence-anchored gate, safety rails, guardrail-text update).

PLAN should use an **agent-team** (TeamCreate + shared task list + SendMessage — not fire-and-forget parallel subagents), because the workstreams must keep blast radii disjoint and coordinate mid-run.
