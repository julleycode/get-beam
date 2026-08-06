---
name: plan:graph-erasure-authorization-spoofing-gap
description: "Backlog: a client-supplied _fp at ingest lets an attacker create a visitor they own carrying a victim's fingerprint, then erase the victim's real graph row (KG-7)"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
---

# Erasure Authorization Is Mitigated, Not Prevented (KG-7)

**Source:** `graph-erasure-compliance_07-08-26`, Known Gap KG-7. SPEC Open Q1 / SPEC Risk §2.

## The attack

The producer requires the requesting site to OWN the `visitor_id`. It does NOT require that the
fingerprint on that visitor row was genuinely produced by the target person's browser.
`routers/events.py` accepts a **client-supplied `_fp`** on every ingest event with no server-side
re-derivation, signature, or session binding.

So: send one crafted ingest event carrying a victim's fingerprint from your own site (creating a
`Visitor` row you legitimately own), then call `DELETE /{your_site}/{that_visitor}/data`. The
producer collects the spoofed fingerprint and the sweep's
`DELETE ... WHERE fingerprint = ANY(:f)` — **no `source_site_id` filter, by design** — erases the
victim's real, paid-for graph row.

Cost: two HTTP requests, far inside the volume marker. The marker is a burst threshold and is
useless against a single precision request; it also enforces nothing (KG-8). Per the
existence-oracle rule the victim is never notified.

## Why not closed here

Closing it needs either server-side fingerprint corroboration (dwell / session-history minimums
before a visitor becomes erasure-eligible) or a different authorization model entirely. That is
product and security judgment, not an engineering-only fix.

**This is disclosed, not designed against.** The SPEC asked for it to be explicitly designed against
in PLAN; the plan chose disclosure and recorded the overclaim in earlier drafts as corrected.
