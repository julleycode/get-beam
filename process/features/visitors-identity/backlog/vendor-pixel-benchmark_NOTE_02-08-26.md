# NOTE: Vendor pixel benchmark (Customers.ai / OpenSend / Retention)

**Date:** 02-08-26 · **Status:** deferred  
**Parent:** `identity-p1p2-status-observability_02-08-26`

## Problem

Cold person-ID via REST IP APIs is probabilistic. Competitors match via **their** browser pixel + graph.

## Why deferred

- Needs US traffic + 30–50 ground-truth testers (coverage / precision / FPR).
- Pixel hook for Customers.ai already exists in `tracker.js` — enablement is config/ops, not a greenfield SDK.
- VN traffic will not validate US shopper graphs.

## Kill / revisit criteria

Start PoC when (a) Lab or pilot site has meaningful US sessions and (b) owner accepts third-party JS on page.
