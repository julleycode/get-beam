---
name: note:benchmark-k-floor-review
description: "Revisit the campaign-benchmark k-anonymity floor (k=5) upward as Beam's tenant count grows"
date: 16-08-26
metadata:
  node_type: memory
  type: report
  feature: campaigns-outreach
---

# Campaign benchmark k-floor — revisit k=5 as tenants grow

**TL;DR:** `BENCHMARK_K_FLOOR = 5` in `apps/api/services/campaign_benchmark.py` is the smallest
floor that still prevents reading back a single tenant's numbers. It is a **young-product**
setting, not a permanent one. Raise it as the tenant count per category grows.

Recorded by marketing-claims-gap Phase 3 (decision D2, checklist E4).

## Why 5 today

- `services/traffic_fit.py`'s `MIN_SAMPLE = 50` is sometimes cited as precedent, but it counts a
  different unit: **events for one site**, not **tenants**. A tenant floor of 50 would mean no
  category ever clears it and the feature never emits a row — a feature that never ships.
- k=2 or k=3 makes a competitor's numbers too easy to infer: with 2 sites in a bucket, a tenant who
  knows their own numbers can subtract them and read the other's exactly.
- 5 is the smallest value where that subtraction still leaves genuine ambiguity.

## Trigger to revisit

Raise the floor when **any** of these becomes true:

- a category routinely pools 20+ opted-in sites (then k=10 costs nothing);
- a competitor pair is known to sit in the same low-population bucket;
- benchmark rows become externally publishable (marketing content, a public page) rather than
  owner-only digest/report copy.

## Related residual risk (already mitigated, keep in view)

**Period differencing.** Even at k=5, comparing two consecutive published periods can narrow one
tenant's numbers when membership changes. Current mitigations, both live:

1. rows with `site_count < 5` are discarded outright (never written suppressed/partial);
2. **no benchmark surface computes or publishes a period-over-period delta** — gated by AC-14's
   automated grep/AST assertion over the digest builder and the new modules, so it cannot be
   reintroduced silently.

If a delta view is ever requested, the correct threshold is `site_count >= 2 x floor` (i.e. >= 10 at
today's k=5) AND stable membership across both periods. Do not ship a delta without both.

`site_count` itself must stay out of every tenant-visible surface — it is an anonymity parameter,
not a statistic.

## What must NOT happen

Lowering the k-floor to make a test or a demo produce a row. If no category clears the floor in a
live environment, prove the behavior with a synthetic fixture and record the live-data gap — that
is exactly what this phase did.
