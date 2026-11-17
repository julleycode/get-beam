# Phase 1 report — Leadpipe pixel PoC wiring

**Date:** 2026-08-02  
**Plan:** `identity-coverage-pixel-fppro_02-08-26`  
**Verdict:** DONE (code + unit); manual DevTools optional for operator

## Env (presence only)

- `LEADPIPE_API_KEY` / `LEADPIPE_DEFAULT_PIXEL_ID`: SET
- `LEADPIPE_ENABLED`: `true` (REST waterfall; unrelated to pixel stack load)
- Customers.ai / Capturify pixel: not configured → not emitted

## What changed

- `apps/api/routers/sites.py` `get_pixel_snippet`: emit `data-stack="1"` + `data-stack-leadpipe="<id>"` (and other vendors when configured). Removed ignored `data-identity-providers` JSON.
- New tests: `tests/unit/test_pixel_snippet_stack_attrs.py`
- `tracker.js` already correct — no change

## Verification

```
pytest tests/unit/test_pixel_snippet_stack_attrs.py tests/unit/test_pixel_fingerprint.py -q
→ 34 passed
```

## Manual leftover

On Lab site with snippet from API: DevTools Network should show `leadpipe.aws53.cloud/p/<pixel_id>.js`.

## Next

Phase 2 — ingest vendor callbacks → `provider_candidate` (pixel load alone does not create Beam identity rows).
