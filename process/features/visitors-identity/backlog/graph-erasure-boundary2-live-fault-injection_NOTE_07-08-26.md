---
name: plan:graph-erasure-boundary2-live-fault-injection
description: "Backlog: §4a Boundary 2's tombstone-INSERT + graph-DELETE atomicity has no live two-connection fault-injection gate against real Postgres — the unit gates T-U8/T-U8b prove code shape only"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
---

# Graph Erasure §4a Boundary 2 — Live Fault-Injection Gate Missing (KG-9)

**Source:** `graph-erasure-compliance_07-08-26` PVL supplement cycle 6 (S15), applying the parallel
INNOVATE verdict on §4a Boundary 2. Recorded as Known Gap **KG-9** in that plan.

## Gap

§4a Boundary 2 requires the tombstone `INSERT` (both `SuppressionEntry` rows) and the
`DELETE FROM beam_identity_graph` to occur in **one transaction with no intervening `commit()`**.

What is proven today:

- **T-U8 / T-U8b** (rewritten at cycle 6) assert **call sequence and call count on a mocked
  `AsyncSession`**: exactly one work-transaction `commit()`, strictly after both statements, never
  between them; on the failure path, zero work commits before the raise. These are legitimate — a
  mock genuinely can prove "the code never issues an early commit".
- **C-08's `async with db.begin():` wrapper** is binding as of cycle 6, making the single-transaction
  shape structurally obvious at the call site.

What is **not** proven — and is the whole of this gap:

> T-U8/T-U8b are **code-shape gates, not proof of real Postgres atomicity.** The safety argument is a
> chain: "the code never issues an early commit" **plus** "Postgres provides real ACID atomicity
> within one transaction" ⇒ *deleted-but-not-tombstoned* is unreachable. The unit gates prove only
> the first link. **Do not read them as covering this note.**

Nothing anywhere in the plan injects a fault *between* the two statements against a real Postgres.

## The missing gate

Against a real (disposable) Postgres:

1. Begin the sweep's work transaction; issue the tombstone `INSERT`.
2. Kill or fail the connection **between** the INSERT and the `DELETE FROM beam_identity_graph`
   (connection drop, forced server-side termination, or an injected exception at that exact point).
3. From a **second, independent connection**, assert committed state is all-or-nothing: either both
   the tombstone rows and the graph deletion are durable, or **neither** is. Any half-state is a
   FAIL.
4. Repeat with the fault injected after the DELETE but before the final `commit()`.

## Why it is deferred

- **Docker-gated** — needs a disposable Postgres plus a second observing connection. Same posture as
  every other Hybrid gate in the parent plan (T-I1…T-I10, T-M1).
- **Needs new test infrastructure, not just a new test.** `tests/integration/` has no mid-transaction
  fault-injection pattern anywhere today. Building it once would be reusable by any future plan that
  needs to assert a real multi-statement atomicity property — it is logged under the parent plan's
  **Test Infra Improvement Notes** for that reason.

## Interim accepted argument

Binding single-transaction wrapper (C-08) + call-sequence gates (T-U8/T-U8b) + Postgres's own ACID
guarantees. **Correction (PVL cycle 8, Execute-Agent Instruction E-1): those gates must assert on
`db.begin` / `db.begin().__aexit__` / `db.execute` ordering, NOT on `db.commit()` call count —
`AsyncSession.begin()` never routes through `AsyncSession.commit()` in `sqlalchemy==2.0.35`, so the
originally specified commit-count assertion was inverted (it failed on correct code).** This keeps AC-3's crash-safety claim honest and bounded rather than overstated — the
criterion is covered for code shape, and this note is the named residual.

## Priority

Medium. The interim argument is sound and the harmful state requires an implementation mistake the
binding wrapper and the call-sequence gates are specifically designed to catch. Worth closing
whenever mid-transaction fault-injection infra is built for any reason, since this is the canonical
first consumer.
