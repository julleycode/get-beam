---
name: note:engage-live-x-metrics-tier
description: "OQ-1 — live X API tier + rate limits for engage metrics/mentions polling at scale; needs-live-provider, double opt-in before any billed call"
date: 17-08-26
feature: campaigns-outreach
metadata:
  node_type: memory
  type: report
  feature: campaigns-outreach
  phase: phase-1
---

# OQ-1 — Live X API tier + rate limits for outcome polling

**Status:** open known-gap. `known-gap: needs-live-provider`. NOT a blocking gate.
**Origin:** engage-learning-agent Phase 1 (signal acquisition), recorded at EXECUTE 17-08-26.

## What is unproven

Phase 1 added two outward READ paths to the X API that nothing in this repo had
ever exercised:

1. `TwitterService.fetch_reply_mentions` — `GET /2/tweets/search/recent` requesting
   **`referenced_tweets`**. No code in this repo has ever requested that field.
   Whether X returns it on this account's access tier is untested.
2. `TwitterService.get_tweets_metrics` — `GET /2/tweets?ids=…&tweet.fields=public_metrics`,
   batched ≤100 ids per call.

Unknown, in order of consequence:

- **Whether `referenced_tweets` is returned at all on our tier.** If it is not, AC-2
  reply-back correlation returns zero rows in production while every mocked gate
  stays green. This is the single highest-value thing to check first.
- The real rate-limit ceiling for both endpoints, and the window length.
- Whether `public_metrics` field names are exactly `like_count` / `retweet_count` /
  `quote_count` / `reply_count`. Only `like_count` has live-shape evidence anywhere
  in this repo (`apps/api/services/demo.py:614`); the other three are unverified.

## What IS proven (and what that does not cover)

AC-2 and AC-3 are proven in mock against real PG+Redis, flag-ON:
`tests/integration/test_engage_signal_acquisition.py` (16/16 green with
`ENGAGE_OUTCOME_CAPTURE_ENABLED=true`, 17-08-26). Every external call is stubbed
via the `_FakeService` monkeypatch precedent. **Flag-ON against real infra is not
the same as proven against the real provider** — the mocked fixture proves our
mapping, not X's response.

## Existing defenses (why this is not urgent)

- `engage_outcome_capture_enabled` defaults **OFF**. Nothing polls until an
  operator flips it.
- `engage_metrics_poll_max_calls_per_sweep` (default 10) hard-caps call VOLUME per
  sweep; on hitting it the sweep stops and logs the remaining backlog.
- `platforms/base.read_retry` backs off on 429 and 5xx (exponential, 2→30s, 3
  attempts). Separate from the write-only `post_retry`.
- Age tiering means a reply is polled every sweep only for its first 48h, daily to
  7d, then one terminal snapshot and never again.
- `engage_metrics_unrecognized_fields` is logged when a response carries no
  recognized counter key, so an X field rename surfaces as a warning rather than a
  silent skip — and no NULL-filled snapshot row is written.

## Clearing conditions

1. **Double opt-in required.** These are billed/live third-party calls. Do not
   dispatch a probe without explicit user opt-in; under `/goal` this does NOT
   auto-grant.
2. Probe order: `referenced_tweets` presence first (cheapest, highest value), then
   `public_metrics` field names, then the rate ceiling.
3. Regenerate the mock fixtures in `test_engage_signal_acquisition.py` from the real
   recorded response once obtained (execute-agent instruction E7) — the invented
   snake_case field is the exact ip-org defect that produced a 100% silent skip.
4. Only then consider flipping `engage_outcome_capture_enabled` in a real
   environment.

Until then AC-2 and AC-3 keep a Hybrid residual and the phase gate stays CONDITIONAL.
