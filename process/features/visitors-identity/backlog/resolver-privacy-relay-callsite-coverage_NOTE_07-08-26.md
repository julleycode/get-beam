---
name: plan:resolver-privacy-relay-callsite-coverage
description: "Backlog: the is_privacy_relay_ip guard call site inside identity_resolver.py has no covering test — only the standalone helper function is tested, and one unrelated test patches a same-named function on a different module"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
---

# Resolver `is_privacy_relay_ip` Call-Site Coverage — NEW TEST REQUIRED

**Source:** `identity-vocab-reconcile_07-08-26` PVL cycle 8 (verifier V-A finding 1) + PVL cycle 9
(S20). Logged as a known-gap at PLAN supplement cycle 9 acceptance; carried into UPDATE PROCESS
closeout 07-08-26.

## Gap

`apps/api/services/identity_resolver.py` calls the fail-closed iCloud Private Relay guard at the
resolver's IP-based enrichment gate:

```python
# apps/api/services/identity_resolver.py:602
if is_privacy_relay_ip(visitor.ip_address):
```

(imported at line 37 from `apps/api/services/company_resolver.py:236`.)

**Verified 07-08-26 via `git grep` on `devjulley` — nothing exercises this call site:**

- `tests/unit/test_company_resolver.py` and `tests/unit/test_identity_quality_gates.py` test only
  the **standalone** `is_privacy_relay_ip()` function directly (IPv4/IPv6/`None`/empty-string
  cases) — neither imports or touches `identity_resolver.py`.
- `tests/unit/test_leadpipe_webhook.py` patches a function with the same name, but on a **different
  module**: `from apps.api.services import leadpipe_webhook as lw`, then
  `patch.object(lw, "is_privacy_relay_ip", ...)`. This is `leadpipe_webhook.py`'s own guard, not
  `identity_resolver.py`'s — a superficially similar test name that does not cover this gap.

Nothing asserts: (a) the guard is called at all inside the resolver's IP-based enrichment flow,
(b) it runs **before** the IPinfo/paid-provider check it is meant to gate, or (c) it correctly sets
`vpn_filtered` on the visitor when it trips.

## Why this matters

This is a fail-closed guard blocking Apple Private Relay (`2a09:bac3::/32`) traffic from reaching
paid enrichment providers. It sits **outside every git conflict hunk** produced by the
`identity-vocab-reconcile` rebase (both branches' code around it merged cleanly), so a rebase would
never surface its absence, and there is no test failure to catch a future regression that
accidentally removes or reorders the call. The guard is confirmed PRESENT on the executed
`identity-vocab-reconcile` result (`git grep -c "is_privacy_relay_ip" devjulley --
apps/api/services/identity_resolver.py` → 2 hits), but that is a point-in-time grep check, not
regression coverage.

## Recommended fix

Add a resolver-level unit test (likely in `tests/unit/test_identity_quality_gates.py` or a new
`identity_resolver`-scoped test file) that:

1. Constructs a `Visitor` (or minimal stub) with `ip_address` set to a known Private Relay range
   (e.g. `2a09:bac3:627a:3050::4d0:11`).
2. Drives the resolver's IP-based enrichment path far enough to observe that the paid-provider
   call is skipped and `vpn_filtered` is set.
3. Asserts ordering: the privacy-relay check runs before any IPinfo/paid-provider call, not after.

## Priority

Low-severity as filed (the guard is present and fail-closed by design — a missing test does not
mean the guard is broken today), but worth closing before any further `identity_resolver.py`
refactor, since this is exactly the kind of silent, outside-the-diff regression that unit tests
exist to catch.
