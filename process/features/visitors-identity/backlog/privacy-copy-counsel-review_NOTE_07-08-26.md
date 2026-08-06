---
name: plan:privacy-copy-counsel-review
description: "Backlog: the cross-tenant disclosure copy in privacy.html, terms.html and onboarding is a requirements placeholder and needs qualified privacy counsel review (KG-4)"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
---

# Cross-Tenant Disclosure Copy — Counsel Review Required (KG-4)

**Source:** `graph-erasure-compliance_07-08-26`, Known Gap KG-4. AC-7 / AC-8 content half.

## Gap

Three surfaces now carry a cross-tenant disclosure:

- `apps/web/public/beam/privacy.html` — new "cross-tenant identity network" section, and the
  previously unqualified "we do not share visitor data with third parties" sentence is now qualified
- `apps/web/public/beam/terms.html` — "you own the data you bring to beam" is now qualified
- `apps/web/src/app/dashboard/onboarding/page.tsx` — `data-testid="cross-tenant-disclosure"`

All three are **requirements placeholders written by an engineer**, marked as such in an inline
comment at each site. They state the four things that must be disclosed and carry the literal marker
string `cross-tenant identity` so presence is mechanically checkable.

## Why this stays CONDITIONAL

Presence is not correctness. Only a mechanical presence check (T-A1 / T-A2) is automatable; whether
the wording is legally adequate is a judgment gate, and counsel review is a hard SPEC constraint.
AC-7/AC-8 must never be marked PASS on the presence check alone.

## What closing it looks like

Qualified privacy counsel reviews and rewrites the three passages. Until then the copy is published
but unreviewed — which is still strictly better than the prior state, where the pages asserted the
opposite of what the code did.
