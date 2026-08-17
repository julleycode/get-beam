---
name: report:coop-credit-reversal-semantics
description: Deferred design for reversing co-op credit when an erasure lands after accrual — a Phase 2 spend-gate prerequisite
date: 16-08-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
  phase: phase-1-supplement
---

# Co-op credit reversal semantics — deferred (Phase 2 prerequisite)

**TL;DR** — Phase 1's supplement closed the erasure→accrual window *prospectively* (the suppression
tombstone is now written inside `enqueue_erasure`'s own transaction, so an erased person can never
mint a co-op row). It deliberately did NOT add the co-op tables to `ERASURE_TARGETS`. If that
retroactive repair is ever needed, this note specifies its shape so nobody improvises one.

## Why it was deferred (H2-D, shape (b) rejected)

1. With the enqueue-time tombstone, the window is closed going forward — there is nothing left for a
   retroactive repair to fix.
2. Both co-op flags (`identity_coop_enabled`, `Site.contribution_enabled`) have always defaulted OFF
   and neither co-op migration is live on prod, so **zero pre-existing co-op rows exist anywhere**
   that would need repairing.
3. A repair requires defining credit-reversal semantics, which is a real design question belonging
   to Phase 2's spend surface, not to a Phase 1 hotfix.

## Required shape when it is built

- **Reversal is a new ledger row, never a DELETE.** `identity_credit_ledger` is append-only; a
  `REVERSE` entry offsets the `ACCRUE` lot it names via `lot_id` / `contribution_event_id`. Deleting
  or mutating an `ACCRUE` row destroys the audit trail the ledger exists to provide.
- **Amount is the offset of the original accrual**, negative or explicitly typed, so
  `spendable_balance` nets to the correct value without special-casing.
- **Spend-gate interaction (Phase 2):** reversal must handle the case where the credit was ALREADY
  spent. Options to decide then — allow a negative balance, or record the reversal as a debt that
  blocks further spend. Do not pick one here; it depends on Phase 2's spend semantics.
- **The `identity_contribution_events` row stays**, stamped with an `excluded_reason` (e.g.
  `erased`), matching the existing `fraud_flagged` / `duplicate` precedent: the event is the audit
  trail, only the credit is withdrawn.
- **Erasure integration:** adding the co-op tables to `ERASURE_TARGETS` is only safe once the above
  exists — otherwise the sweep would delete accrual rows and silently corrupt balances.

## Trigger conditions

Build this before EITHER of:
- any co-op flag is enabled in an environment where erasure requests can occur, OR
- Phase 2's spend surface ships.

---

## OPEN DESIGN QUESTION — clawback / debt semantics (moved here 16-08-26 by Phase 2 PVL supplement cycle 2, F2-1)

Phase 2's P2-D1 originally decided a debt model: *"REVERSE always offsets the lot's FULL original
amount"* + *"allow negative balance as debt; future ACCRUEs pay it down."* **That model is
unachievable and has been retracted.** Phase 2 now ships REVERSE as an **audit-only** primitive whose
only balance-facing guarantee is "a REVERSE row never INCREASES spendable balance."

**WHY it is unachievable — record this before re-proposing any debt model.** Phase 2's P2-D5 adopted
**lot-symmetric stamping** (Constraint 12): every non-ACCRUE row — SPEND, EXPIRE, **and REVERSE** —
copies its source lot's `spendable_at`/`expires_at`. That rule exists to fix F-1 (an unstamped EXPIRE
row double-subtracts and drives every normal expiry to `−N` on the billing surface). Its unavoidable
consequence is that **every offsetting row is window-bound**:

| Ordering (`+N`, window `[S,E]`, spend `k`) | Actual effect | Intended by the old debt model |
|---|---|---|
| REVERSE while `S ≤ now < E` | `N − k − N = −k` — **but it evaporates at `E`**, since all rows leave the window together | a durable `−k` debt |
| SPEND → lot expires at `E` → REVERSE (erasure arrives late) | REVERSE stamped `[S,E]`, already outside the window → **contributes 0. Zero clawback, permanently.** | claw back the `k` actually consumed |

`coop_credit_expiry_days = 90`, so the late-arrival ordering is ordinary — an abuser simply waits out
the window. The old defence (*"the lot's contribution was already 0, so there is nothing left to claw
back"*) holds only for an **unspent** lot; for a spent lot the site keeps `k` real resolutions bought
with credit earned from data that must now be erased.

**The two candidate designs, both requiring a decision that cannot be made until the erasure trigger
is designed:**

1. **Persistent-debt row class** — an unstamped (window-free) debt row. Reintroduces exactly the
   double-subtraction shape F-1 was fixed to remove, so it needs its own balance predicate.
2. **Consumed-portion algebra on a separate non-windowed surface** — track `k` (credits actually
   consumed from a repudiated lot) outside the balance window, e.g. a user-level debt column or a
   distinct table. New write surface; needs its own reconciliation story against AC-8.

**Do not pick one here.** Whichever is chosen must be gated by a test proving the
**spend → expire → REVERSE** ordering, which no Phase 2 gate exercises (F2-1 was found by algebra,
not by a test).

---

## REVERSE DROPPED FROM PHASE 2 ENTIRELY (17-08-26, at the 2a/2b split)

**Status change: this note is now the SOLE owner of every REVERSE artefact.** The pre-split Phase 2
plan was split into Phase 2a (consumption + FIFO expiry) and Phase 2b (spend wiring) by explicit user
decision. **REVERSE ships in neither.** `LEDGER_ENTRY_TYPES` stays `("ACCRUE","SPEND","EXPIRE")` —
no vocabulary change ships in 2a or 2b, and Phase 2a's Constraint 2 states that as a hard constraint.

**Why the split happened (context for whoever picks this up):** five PVL cycles + three independent
adversarial rounds produced a stable design core (savepoint posture, lock acyclicity, REVERSE
idempotence, and the K-4 orphan premise all survived repeated attack), but every fix cycle produced a
NEW defect of one class — **a gate that passes on the implementation it exists to forbid**. Root
cause was phase size. REVERSE was the single largest source of that surface growth: it forced the
debt model, then the stamping interaction, then the composition-of-clamps lock, then the ordering
gates — each one a fresh vacuous-green risk.

### Content moved here wholesale from the Phase 2 plan

| Artefact | What it was |
|---|---|
| **P2-D1** | The REVERSE vocabulary decision + the audit-only primitive framing (rewritten twice: debt model → audit-only) |
| **S-1** | `apps/api/models/identity_coop.py` — add `"REVERSE"` at **all three vocabulary sites**: (i) the `LEDGER_ENTRY_TYPES` tuple at `:57`; (ii) the inline enumeration comment at `:135`; (iii) the `CreditLedgerEntry` docstring at `:120-123`. **No migration** — no DB CHECK exists at `:135-136`; migration `e7b3d5f19c46:103` declares `entry_type` as plain `sa.String(10)`. Budget ~4 lines. |
| **S-2** | `async def reverse_credit(db, lot_id, reason) -> int` — writes ONE `REVERSE` audit row for the lot, `lot_id` set, `site_id` = the lot's own, **stamped with that lot's `spendable_at`/`expires_at`**, `amount = -max(0, remaining_at_write_time)` so the row can never increase spendable balance. Idempotent per `(lot_id)`. |
| **S-2b** | The obligation to record WHY the clawback/debt question is open (now satisfied by this note) |
| **S-2c** | `reverse_credit` must take the SAME user-keyed blocking `SELECT pg_advisory_xact_lock(hashtext(:key))` (`key = str(user_id)`, resolved via the lot's `site_id → sites.user_id`) that `spend_credits` takes |
| **G-1** | REVERSE primitive gate — 4 legs (row shape + stamps; idempotence; the spend→expire→REVERSE ordering leg; the zero-skip leg) |
| **G-2** | REVERSE-never-increases-balance gate — restated as `0 <= after <= before` on EVERY leg, plus the concurrency leg |
| **Constraint 12b** | "No writer may produce a negative spendable balance, and no EXPIRE row may be positive" — its **composition** clause and the `reverse_credit` lock requirement |

### Verified findings that travel with this work (do NOT re-derive)

**M-A — `remaining` was defined ONLY for `reverse_credit`.** The Phase 2 plan defined `remaining` as
the **window-BLIND** raw lot SUM (`SELECT SUM(amount) FROM identity_credit_ledger WHERE lot_id = :lot`
with **no** `spendable_at`/`expires_at` predicate) — but only inside S-2's `reverse_credit` text. The
expiry sweep (B3/S-11) then used a bare "remaining" with no local definition. **That ambiguity was a
live FAIL (F5-2)** and has been fixed in Phase 2a by restating the window-blind definition verbatim in
B3 and adding a mandatory positive leg to G-18. **Any REVERSE implementation must use the SAME
window-blind definition** — a window-aware reading makes `reverse_credit` a no-op on exactly the lots
that most need clawing back (already-lapsed ones).

**M-B — per-writer clamping does NOT compose.** "Each writer individually clamped ⇒ no negative
balance" holds **only under serialized writers**. `spendable_balance` is a frozen FLAT SUM with no
per-lot floor. Worked example: a concurrent `spend_credits` (holding the user lock) and an **unlocked**
`reverse_credit` can both read `remaining = 3` on a `+5` lot with `−2` already spent, then write
`SPEND −1` and `REVERSE −3` ⇒ in-window SUM `= −1`, a negative balance on the billing surface.
**DECIDED: require the lock** (S-2c) rather than narrowing Constraint 12b's claim — the alternative
leaves a documented path to a negative balance, which is exactly the F-1 class, and the lock costs
~2 lines on an already-rare audit path.

**M3-3 — sweep-then-REVERSE loses the audit trail.** Once `expire_lapsed_lots` has written its
`EXPIRE −max(0, remaining)` row, the lot's window-blind remaining is **0**, so a later `reverse_credit`
computes `-max(0, 0) = 0` and (per the zero-skip rule) writes **NO ROW AT ALL**. The erasure event
therefore leaves **no trace whatsoever** on a lot that was swept before the erasure arrived — which is
the ordinary case at `coop_credit_expiry_days = 90`. Any design that keeps the zero-skip rule must
either (a) accept that expired-then-erased lots are unauditable, or (b) introduce a zero-amount or
separately-typed audit row — which collides with the amount-sign contract below.

**Skip-when-zero vs the amount-sign contract.** `models/identity_coop.py` asserts on the `amount`
column: `# Positive for ACCRUE; negative for SPEND and EXPIRE.` A REVERSE audit row that wants to
record "erasure happened, nothing to claw back" has no legal value: `0` is neither positive nor
negative and would need the contract widened; a positive value is forbidden outright. The zero-skip
rule exists precisely to dodge this — but M3-3 is the cost. **Pick deliberately; do not let EXECUTE
resolve it by accident.**

### Why persistent debt remains undecidable

Lot-symmetric stamping (Phase 2a Constraint 12) makes **every offsetting row window-bound**, so
durable debt needs either (i) an **unstamped** row class — which reintroduces F-1's
double-subtraction — or (ii) consumed-portion algebra on a **separate, non-windowed** surface, which
is a new write surface needing its own AC-8 reconciliation story. Both failing orderings, verbatim:

| Ordering | Actual balance effect under stamping | What the retired debt model claimed |
|---|---|---|
| REVERSE while `S ≤ now < E` (live lot) | `N − k − N = −k`, **but the debt evaporates at `E`** — all rows leave the window together | a durable `−k` debt paid down by future ACCRUEs |
| SPEND → lot expires at `E` → REVERSE (erasure arrives late) | REVERSE is stamped `[S,E]`, already outside the window → **contributes 0. Zero clawback, permanently.** | claw back the `k` actually consumed |

At `coop_credit_expiry_days = 90` the late-arrival ordering is **ordinary, not exotic** — an abuser
simply waits out the window.

### Entry conditions for picking this up

1. Phase 2a and Phase 2b both LIVE (the stamping contract and the spend writer must both exist before
   REVERSE's interaction with them can be gated).
2. The erasure-sweep→REVERSE **trigger** design decided (still open — this note's original subject).
3. A decision on M3-3 / the amount-sign collision, made explicitly and written down.
4. Constraint 12b's composition requirement (S-2c lock) honored by whatever writer is built.
